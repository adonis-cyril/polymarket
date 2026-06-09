"""Scrollable log pane with Rich formatting."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import RichLog

from terminal.core.models import LogEntry


class LogPane(RichLog):
    """Live log viewer — integrates with loguru sink."""

    DEFAULT_CSS = """
    LogPane {
        height: 1fr;
        scrollbar-gutter: stable;
    }
    """

    def append_entry(self, entry: LogEntry) -> None:
        ts = entry.timestamp.strftime("%H:%M:%S") if entry.timestamp else ""
        style_map = {
            "DEBUG": "log-debug",
            "INFO": "log-info",
            "WARNING": "log-warning",
            "ERROR": "log-error",
        }
        style = style_map.get(entry.level.upper(), "log-info")
        text = Text()
        text.append(f"{ts} ", style="dim")
        text.append(f"[{entry.level[:4]}] ", style=style)
        text.append(f"{entry.source}: ", style="dim")
        text.append(entry.message, style=style)
        self.write(text)

    def append_line(self, level: str, message: str, source: str = "tui") -> None:
        self.append_entry(
            LogEntry(timestamp=datetime.now(), level=level, message=message, source=source)
        )
