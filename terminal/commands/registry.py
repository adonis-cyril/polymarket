"""Command registry with autocomplete metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from terminal.core.interfaces import CommandResult
from terminal.events import EventBus, EventType
from terminal.state import LeftView, StateStore


@dataclass
class CommandContext:
    store: StateStore
    bus: EventBus
    args: list[str] = field(default_factory=list)


CommandHandler = Callable[[CommandContext], Awaitable[CommandResult] | CommandResult]


class CommandRegistry:
    """Central command dispatch with help and autocomplete."""

    def __init__(self) -> None:
        self._commands: dict[str, tuple[str, CommandHandler]] = {}
        self._register_defaults()

    def register(self, name: str, description: str, handler: CommandHandler) -> None:
        self._commands[name.lower()] = (description, handler)

    def names(self) -> list[str]:
        return sorted(self._commands.keys())

    @property
    def commands(self) -> dict[str, tuple[str, CommandHandler]]:
        return self._commands

    def autocomplete(self, partial: str) -> list[str]:
        partial = partial.lower().strip()
        if not partial:
            return self.names()
        return [n for n in self.names() if n.startswith(partial)]

    def help_text(self) -> str:
        lines = ["Available commands:"]
        for name, (desc, _) in sorted(self._commands.items()):
            lines.append(f"  {name:<16} {desc}")
        return "\n".join(lines)

    async def execute(self, line: str, ctx: CommandContext) -> CommandResult:
        parts = line.strip().split()
        if not parts:
            return CommandResult(False, "Empty command")
        cmd, *args = parts
        entry = self._commands.get(cmd.lower())
        if not entry:
            return CommandResult(False, f"Unknown command: {cmd}. Type 'help' for list.")
        ctx.args = args
        _, handler = entry
        try:
            result = handler(ctx)
            if hasattr(result, "__await__"):
                result = await result
            await ctx.bus.emit(
                EventType.COMMAND_EXECUTED,
                {"command": cmd, "success": result.success, "message": result.message},
            )
            return result
        except Exception as exc:
            logger.exception("Command {} failed: {}", cmd, exc)
            return CommandResult(False, f"Error: {exc}")

    def _register_defaults(self) -> None:
        self.register("help", "Show available commands", self._cmd_help)
        self.register("clear", "Clear log pane", self._cmd_clear)
        self.register("refresh", "Force data refresh", self._cmd_refresh)
        self.register("theme", "Switch theme (polyadonis|bloomberg|midnight|light)", self._cmd_theme)
        self.register("markets", "Show/focus markets in left pane", self._cmd_markets)
        self.register("quit", "Exit the application", self._cmd_quit)
        self.register("exit", "Exit the application", self._cmd_quit)

    @staticmethod
    def _cmd_help(ctx: CommandContext) -> CommandResult:
        return CommandResult(True, "Type 'help' — see ? for keyboard shortcuts")

    @staticmethod
    async def _cmd_clear(ctx: CommandContext) -> CommandResult:
        ctx.store.state.logs.clear()
        return CommandResult(True, "Output cleared", {"action": "clear_output"})

    @staticmethod
    async def _cmd_refresh(ctx: CommandContext) -> CommandResult:
        await ctx.bus.emit(EventType.REFRESH_REQUESTED)
        return CommandResult(True, "Refresh requested")

    @staticmethod
    async def _cmd_theme(ctx: CommandContext) -> CommandResult:
        if not ctx.args:
            return CommandResult(False, "Usage: theme <polyadonis|bloomberg|midnight|light>")
        theme = ctx.args[0].lower()
        if theme not in ("polyadonis", "bloomberg", "midnight", "light"):
            return CommandResult(False, f"Unknown theme: {theme}")
        ctx.store.set_theme(theme)
        await ctx.bus.emit(EventType.THEME_CHANGED, {"theme": theme})
        return CommandResult(True, f"Theme set to {theme}")

    @staticmethod
    async def _cmd_markets(ctx: CommandContext) -> CommandResult:
        filt = ""
        for arg in ctx.args:
            if not arg.startswith("-"):
                filt = arg
                break
        ctx.store.state.search_filter = filt
        ctx.store.set_left_view(LeftView.MARKETS)
        await ctx.bus.emit(EventType.LEFT_VIEW_CHANGED, {"view": LeftView.MARKETS.value})
        await ctx.bus.emit(EventType.REFRESH_REQUESTED, {"slug_filter": filt})
        count = len(ctx.store.state.markets)
        return CommandResult(True, f"Markets view — filter '{filt or '(none)'}' ({count} loaded)")

    @staticmethod
    def _cmd_quit(ctx: CommandContext) -> CommandResult:
        return CommandResult(True, "quit", {"action": "quit"})
