"""Short command output zone — sits below the >>> prompt."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import RichLog


class CommandOutput(RichLog):
    """Displays brief command responses (status, balance, config summary)."""

    MAX_LINES = 12

    DEFAULT_CSS = """
    CommandOutput {
        height: 8;
        min-height: 6;
        max-height: 10;
        width: 1fr;
        border-top: solid $border;
        background: $surface;
        padding: 0 1;
        scrollbar-gutter: stable;
    }
    """

    def show_result(self, message: str, level: str = "INFO") -> None:
        self.clear()
        style_map = {
            "DEBUG": "log-debug",
            "INFO": "log-info",
            "WARNING": "log-warning",
            "ERROR": "log-error",
        }
        style = style_map.get(level.upper(), "log-info")
        lines = message.splitlines() or [message]
        for line in lines[: self.MAX_LINES]:
            text = Text()
            text.append("  ", style="dim")
            text.append(line.rstrip(), style=style)
            self.write(text)
        if len(lines) > self.MAX_LINES:
            extra = Text()
            extra.append(f"  … +{len(lines) - self.MAX_LINES} lines (see Activity pane)", style="dim")
            self.write(extra)

    def clear_output(self) -> None:
        self.clear()
