"""Route command and log output to short zone vs activity pane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from terminal.core.interfaces import CommandResult

SHORT_LINE_LIMIT = 15

# Commands whose output always streams to the activity pane.
LONG_OUTPUT_COMMANDS = frozenset(
    {
        "connect",
        "preflight",
        "check",
        "staircase",
        "backtest",
        "logs",
        "test",
        "tests",
    }
)

# Summary-style commands shown below the >>> prompt when reasonably short.
PREFER_SHORT_COMMANDS = frozenset(
    {
        "status",
        "balance",
        "config",
        "mode",
        "bot",
        "run",
        "stop",
        "pause",
        "resume",
        "positions",
        "markets",
        "help",
        "theme",
        "buy",
        "sell",
        "cancel",
        "refresh",
        "clear",
    }
)

PREFER_SHORT_LINE_LIMIT = 20


@dataclass
class OutputRouter:
    """Decide whether text belongs below the command bar or in the activity pane."""

    on_short: Callable[[str, str], None]
    on_activity: Callable[[str, str, str], None]
    short_line_limit: int = SHORT_LINE_LIMIT

    def route_command(self, command: str, result: CommandResult) -> None:
        if result.data.get("suppress_output"):
            return
        message = (result.message or "").strip()
        if not message:
            return

        level = "INFO" if result.success else "WARNING"
        cmd = (command.strip().split()[0] if command.strip() else "").lower()

        if result.data.get("route") == "activity":
            self._to_activity(message, level, "command")
            return
        if result.data.get("route") == "short":
            self._to_short(message, level)
            return

        lines = [ln for ln in message.splitlines() if ln.strip()]
        force_long = cmd in LONG_OUTPUT_COMMANDS

        if cmd in PREFER_SHORT_COMMANDS and len(lines) <= PREFER_SHORT_LINE_LIMIT:
            self._to_short(message, level)
        elif force_long or len(lines) > self.short_line_limit:
            self._to_activity(message, level, "command")
        else:
            self._to_short(message, level)

    def route_stream(self, message: str, *, level: str = "INFO", source: str = "bot") -> None:
        """Streaming logs, bot stdout/stderr, and preflight always go right."""
        text = (message or "").strip()
        if text:
            self._to_activity(text, level, source)

    def route_log(self, message: str, *, level: str = "INFO", source: str = "app") -> None:
        """Loguru sink — activity pane only."""
        text = (message or "").strip()
        if text:
            self._to_activity(text, level, source)

    def _to_short(self, message: str, level: str) -> None:
        self.on_short(message, level)

    def _to_activity(self, message: str, level: str, source: str) -> None:
        for line in message.splitlines():
            stripped = line.rstrip()
            if stripped:
                self.on_activity(stripped, level, source)
        if not message.strip():
            self.on_activity("(done)", level, source)


def command_base(line: str) -> str:
    return line.strip().split()[0].lower() if line.strip() else ""
