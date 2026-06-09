"""Textual application root — Hummingbot-inspired 2-pane TUI."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import TypeVar

from dotenv import load_dotenv
from loguru import logger
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widget import Widget

from terminal import __version__
from terminal.commands import CommandContext, CommandRegistry, CommandPromptSession
from terminal.commands.connection import register_connection_commands, set_orchestrator
from terminal.commands.extended import register_extended_commands, get_bot_control
from terminal.commands.trading import register_trading_commands
from terminal.config import get_settings
from terminal.core.interfaces import CommandResult
from terminal.core.models import LogEntry
from terminal.events import Event, EventBus, EventType
from terminal.logging import setup_logging
from terminal.market_data import DataOrchestrator
from terminal.screens import BotControlScreen, HelpModal, SettingsScreen, TestRunnerScreen
from terminal.state import StateStore
from terminal.themes import get_theme_css
from terminal.ui.layout import WorkstationLayout
from terminal.ui.output_router import OutputRouter
from terminal.ui.widgets import ActivityPane, CommandBar, LeftPane, MetricsBar, TopBar
from terminal.ui.widgets.command_bar import CommandSubmitted

load_dotenv()

_QueryType = TypeVar("_QueryType", bound=Widget)


class PolymarketTUI(App):
    """Polymarket terminal — keyboard-first trading console."""

    TITLE = "Polymarket Terminal"
    SUB_TITLE = "Trading Console"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("q", "quit", "Quit", show=False),
        Binding("f5", "refresh", "Refresh", show=True),
        Binding("ctrl+t", "focus_activity", "Activity", show=True),
        Binding("ctrl+s", "run_status", "Status", show=True),
        Binding("question_mark", "help", "Help", show=False),
        Binding("ctrl+p", "command_palette", "Palette", show=False),
    ]

    CSS = """
    Screen { overflow: hidden; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.settings = get_settings()
        self.store = StateStore()
        self.bus = EventBus()
        self.registry = CommandRegistry()
        self.prompt_session = CommandPromptSession(self.registry)
        self.orchestrator = DataOrchestrator(self.store, self.bus)
        set_orchestrator(self.orchestrator)
        self._theme_tie = 0
        self._last_trade_id = 0
        self._router: OutputRouter | None = None
        self._patch_registry()
        register_trading_commands(self.registry)
        register_extended_commands(self.registry)
        register_connection_commands(self.registry)

    def compose(self) -> ComposeResult:
        """Flat workstation layout — widgets are direct descendants (Hummingbot-style)."""
        yield WorkstationLayout(self.registry)

    def _patch_registry(self) -> None:
        async def help_handler(ctx: CommandContext) -> CommandResult:
            return CommandResult(True, self.registry.help_text())

        self.registry.register("help", "List commands", help_handler)

    def _build_router(self) -> OutputRouter:
        return OutputRouter(
            on_short=self._show_short_output,
            on_activity=self._append_activity,
        )

    def _query(self, selector: str, expect_type: type[_QueryType]) -> _QueryType:
        """Query workstation widgets anywhere in the app DOM."""
        return self.query_one(selector, expect_type)

    def on_mount(self) -> None:
        self._router = self._build_router()
        self._apply_theme(self.settings.tui_theme)
        setup_logging(on_log=self._on_log_entry)
        get_bot_control().set_output_handler(self._on_bot_line)
        self._subscribe_events()
        self.run_worker(self._startup(), exclusive=True)

    def _apply_theme(self, name: str) -> None:
        self.store.set_theme(name)
        self._theme_tie += 1
        self.stylesheet.add_source(get_theme_css(name), tie_breaker=self._theme_tie)

    def _subscribe_events(self) -> None:
        self.bus.subscribe(EventType.STATE_UPDATED, self._on_state_updated)
        self.bus.subscribe(EventType.TRADES_UPDATED, self._on_trades_updated)
        self.bus.subscribe(EventType.MARKETS_UPDATED, self._on_markets_updated)
        self.bus.subscribe(EventType.POSITIONS_UPDATED, self._on_positions_updated)
        self.bus.subscribe(EventType.CONNECTIVITY_UPDATED, self._on_connectivity_updated)
        self.bus.subscribe(EventType.REFRESH_REQUESTED, self._on_refresh_requested)
        self.bus.subscribe(EventType.LEFT_VIEW_CHANGED, self._on_left_view_changed)
        self.bus.subscribe(EventType.ACTIVITY_EVENT, self._on_activity_event)
        self.bus.subscribe(EventType.THEME_CHANGED, self._on_theme_changed)
        self.bus.subscribe(EventType.ERROR, self._on_error)

    async def _startup(self) -> None:
        logger.info("Polymarket Terminal v{} — theme={}", __version__, self.settings.tui_theme)
        self._sync_ui(full=True)
        self._append_activity(
            "POLYADONIS ready — type connect to link services, or help for commands",
            "INFO",
            "system",
        )
        self._refocus_command_input()

    async def _on_state_updated(self, event: Event) -> None:
        self._sync_ui()

    async def _on_trades_updated(self, event: Event) -> None:
        self._sync_trades_activity()
        self._update_left_pane()

    async def _on_markets_updated(self, event: Event) -> None:
        self._update_left_pane()

    async def _on_positions_updated(self, event: Event) -> None:
        self._update_left_pane()

    async def _on_connectivity_updated(self, event: Event) -> None:
        self._update_top_bar()

    async def _on_refresh_requested(self, event: Event) -> None:
        filt = event.payload.get("slug_filter")
        if filt is not None:
            markets = await self.orchestrator.polymarket.get_markets(
                self.settings.tui_markets_limit, slug_filter=filt
            )
            self.store.set_markets(markets)
            self._update_left_pane()
        await self.orchestrator.refresh_all()

    async def _on_left_view_changed(self, event: Event) -> None:
        self._update_left_pane()

    async def _on_activity_event(self, event: Event) -> None:
        if self._router:
            self._router.route_stream(
                event.payload.get("message", ""),
                level=event.payload.get("level", "INFO"),
                source=event.payload.get("source", "event"),
            )

    async def _on_theme_changed(self, event: Event) -> None:
        self._apply_theme(event.payload.get("theme", "polyadonis"))

    async def _on_error(self, event: Event) -> None:
        self._append_activity(event.payload.get("message", "Unknown error"), "ERROR", "system")

    def _call_on_app_thread(self, callback) -> None:
        """Schedule UI work from loguru/bot threads without crashing in tests."""
        if threading.get_ident() == self._thread_id:
            callback()
        else:
            self.call_from_thread(callback)

    def _on_log_entry(self, entry: LogEntry) -> None:
        self.store.add_log(entry)
        self._call_on_app_thread(lambda: self._dispatch_log(entry))

    def _on_bot_line(self, line: str) -> None:
        self._call_on_app_thread(lambda: self._dispatch_bot_line(line))

    def _dispatch_log(self, entry: LogEntry) -> None:
        if self._router:
            self._router.route_log(
                entry.message,
                level=entry.level,
                source=entry.source or "app",
            )

    def _dispatch_bot_line(self, line: str) -> None:
        if self._router:
            self._router.route_stream(line, source="bot")

    def _show_short_output(self, message: str, level: str) -> None:
        try:
            self._query("#command-bar", CommandBar).show_output(message, level)
        except Exception as exc:
            logger.warning("Short output failed: {}", exc)

    def _append_activity(self, message: str, level: str = "INFO", source: str = "tui") -> None:
        entry = LogEntry(timestamp=datetime.now(), level=level, message=message, source=source)
        self.store.add_log(entry)
        try:
            self._query("#activity", ActivityPane).append_activity(message, level, source)
        except Exception as exc:
            logger.warning("Activity append failed: {}", exc)

    def _clear_outputs(self) -> None:
        try:
            self._query("#activity", ActivityPane).query_one("#activity-log").clear()
        except Exception as exc:
            logger.warning("Clear activity failed: {}", exc)
        try:
            self._query("#command-bar", CommandBar).clear_output()
        except Exception as exc:
            logger.warning("Clear command output failed: {}", exc)

    def _refocus_command_input(self) -> None:
        try:
            self._query("#command-bar", CommandBar).focus_input()
        except Exception as exc:
            logger.warning("Command input focus failed: {}", exc)

    def _sync_ui(self, full: bool = False) -> None:
        self._update_top_bar()
        self._update_metrics_bar()
        self._update_left_pane()
        if full:
            self._sync_trades_activity()

    def _update_top_bar(self) -> None:
        try:
            info = get_bot_control().process_info
            self.store.set_mode(info.mode, info.strategy)
            self._query("#top-bar", TopBar).update_from_state(
                self.store.state.bot,
                self.store.state.connectivity,
                mode=info.mode,
                strategy=info.strategy,
                loading=self.store.state.loading,
                version=f"v{__version__}",
            )
        except Exception as exc:
            logger.warning("Top bar update failed: {}", exc)

    def _update_metrics_bar(self) -> None:
        try:
            self._query("#metrics-bar", MetricsBar).update_from_bot(
                self.store.state.bot,
                self.store.state.session_started,
            )
        except Exception as exc:
            logger.warning("Metrics bar update failed: {}", exc)

    def _update_left_pane(self) -> None:
        try:
            s = self.store.state
            self._query("#left-pane", LeftPane).update_data(
                s.bot,
                s.markets,
                s.positions,
                s.trades,
                view=s.left_view,
                connected=s.connected,
            )
        except Exception as exc:
            logger.warning("Left pane update failed: {}", exc)

    def _sync_trades_activity(self) -> None:
        try:
            pane = self._query("#activity", ActivityPane)
            self._last_trade_id = pane.sync_trades(self.store.state.trades, self._last_trade_id)
        except Exception as exc:
            logger.warning("Trade sync failed: {}", exc)

    def action_refresh(self) -> None:
        self.run_worker(self.orchestrator.refresh_all())

    def refresh_data(self) -> None:
        self.action_refresh()

    def action_focus_activity(self) -> None:
        try:
            self._query("#activity", ActivityPane).query_one("#activity-log").focus()
        except Exception as exc:
            logger.warning("Focus activity failed: {}", exc)

    def action_run_status(self) -> None:
        self.run_worker(self.run_command("status"))

    def action_help(self) -> None:
        self.push_screen(HelpModal(self.registry))

    def action_command_palette(self) -> None:
        self.run_worker(self.run_command("help"))

    async def run_command(self, line: str) -> None:
        await self._execute_command(line)

    async def _execute_command(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            self._refocus_command_input()
            return

        cmd_base = stripped.split()[0].lower()
        self._append_activity(f">>> {stripped}", "INFO", "command")
        self._show_short_output(f"Running {cmd_base}…", "INFO")
        self.store.set_loading(True)
        self._update_top_bar()

        result: CommandResult | None = None
        ctx = CommandContext(store=self.store, bus=self.bus)
        try:
            result = await self.registry.execute(line, ctx)
        except Exception as exc:
            logger.exception("Command dispatch failed: {}", exc)
            self._append_activity(f"Error: {exc}", "ERROR", "command")
            self._show_short_output(f"Error: {exc}", "ERROR")
        finally:
            self.store.set_loading(False)
            self._update_top_bar()

        if result is None:
            self._refocus_command_input()
            return

        self.prompt_session.add_to_history(line)

        if result.data.get("action") == "clear_output":
            self._clear_outputs()
        elif self._router:
            self._router.route_command(line, result)

        if not result.success and result.message:
            self._append_activity(result.message, "WARNING" if result.success else "ERROR", "command")

        if result.data.get("action") == "quit":
            self.exit()
        elif result.data.get("action") == "screen":
            self._open_screen(result.data.get("screen", ""))
        elif line.strip().lower() == "help":
            self.action_help()
        else:
            self._update_top_bar()
            self._update_left_pane()

        self._refocus_command_input()

    @on(CommandSubmitted)
    def on_command_submitted(self, event: CommandSubmitted) -> None:
        """Textual 8 dispatches custom messages as on_<message_class>, not on_<widget>_<message>."""
        self.run_worker(self._execute_command(event.command))

    def _open_screen(self, name: str) -> None:
        screens = {
            "bot": BotControlScreen,
            "tests": TestRunnerScreen,
            "test": TestRunnerScreen,
            "settings": SettingsScreen,
            "config": SettingsScreen,
        }
        cls = screens.get(name.lower())
        if cls:
            self.push_screen(cls())

    async def on_unmount(self) -> None:
        get_bot_control().set_output_handler(None)
        await get_bot_control().stop_bot()
        await self.orchestrator.stop()
