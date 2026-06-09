"""Bot control screen — start/stop/pause/resume."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from terminal.commands.extended import get_bot_control
from terminal.core.models import BotStateSnapshot


class BotControlScreen(Screen):
    """Interactive bot control panel."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("f5", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    BotControlScreen {
        align: center middle;
    }
    #bot-panel {
        width: 80;
        height: auto;
        max-height: 90%;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #bot-actions {
        height: auto;
        margin-top: 1;
    }
    #bot-actions Button {
        margin: 0 1 1 0;
    }
    #bot-output {
        height: 12;
        border: solid $border;
        overflow-y: auto;
        padding: 0 1;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="bot-panel"):
            yield Static("[bold orange1]Bot Control[/]", id="bot-title")
            yield Static("", id="bot-status")
            with Horizontal(id="bot-actions"):
                yield Button("Start Paper", id="btn-start-paper", variant="success")
                yield Button("Start Live", id="btn-start-live", variant="warning")
                yield Button("Start HFT", id="btn-start-hft", variant="primary")
                yield Button("Stop", id="btn-stop", variant="error")
            with Horizontal():
                yield Button("Pause", id="btn-pause")
                yield Button("Resume", id="btn-resume")
                yield Button("Force Skip", id="btn-skip")
            yield Static("[dim]Recent bot output[/]", id="output-label")
            yield Static("", id="bot-output")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_display()

    def _refresh_display(self) -> None:
        ctrl = get_bot_control()
        info = ctrl.process_info
        try:
            bot: BotStateSnapshot = self.app.store.state.bot  # type: ignore[attr-defined]
        except Exception:
            bot = BotStateSnapshot()

        status = (
            f"Process: [cyan]{'RUNNING' if info.running else 'STOPPED'}[/] "
            f"(pid {info.pid or '—'})\n"
            f"Launch mode: {info.mode} / {info.strategy}\n"
            f"DB state: [bold]{bot.status}[/] | Balance: ${bot.balance:,.2f} | "
            f"Trades: {bot.total_trades} | Win: {bot.win_rate:.1f}%"
        )
        self.query_one("#bot-status", Static).update(status)

        lines = ctrl.recent_output(15)
        self.query_one("#bot-output", Static).update(
            "\n".join(lines) if lines else "[dim]No bot output yet[/]"
        )

    async def _run_action(self, coro) -> None:
        msg = await coro
        self.app._append_log("INFO", msg, "bot")  # type: ignore[attr-defined]
        self._refresh_display()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        ctrl = get_bot_control()
        bid = event.button.id or ""

        if bid == "btn-start-paper":
            self.run_worker(self._run_action(ctrl.start_bot(mode="paper", strategy="standard")))
        elif bid == "btn-start-live":
            self.run_worker(self._run_action(ctrl.start_bot(mode="live", strategy="standard")))
        elif bid == "btn-start-hft":
            self.run_worker(self._run_action(ctrl.start_bot(mode="paper", strategy="hft")))
        elif bid == "btn-stop":
            self.run_worker(self._run_action(ctrl.stop_bot()))
        elif bid == "btn-pause":
            self.run_worker(self._run_action(ctrl.send_admin_command("PAUSE")))
        elif bid == "btn-resume":
            self.run_worker(self._run_action(ctrl.send_admin_command("RESUME")))
        elif bid == "btn-skip":
            self.run_worker(self._run_action(ctrl.send_admin_command("FORCE_SKIP")))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._refresh_display()
