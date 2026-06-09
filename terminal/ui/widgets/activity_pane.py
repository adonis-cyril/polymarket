"""Right pane — live activity console (logs, trades, events)."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import RichLog, Static

from terminal.core.models import LogEntry, TradeRow


class ActivityLog(RichLog):
    """Scrollable log stream inside the activity pane."""

    DEFAULT_CSS = """
    ActivityLog {
        height: 1fr;
        width: 1fr;
        scrollbar-gutter: stable;
        padding: 0 1;
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
        self.scroll_end(animate=False)

    def append_activity(self, message: str, level: str = "INFO", source: str = "event") -> None:
        self.append_entry(
            LogEntry(timestamp=datetime.now(), level=level, message=message, source=source)
        )

    def append_trade(self, trade: TradeRow) -> None:
        pnl_style = "log-info" if trade.pnl >= 0 else "log-error"
        text = Text()
        text.append(f"{datetime.now().strftime('%H:%M:%S')} ", style="dim")
        text.append("[FILL] ", style="log-info")
        text.append(
            f"{trade.asset.upper()} {trade.direction.upper()} {trade.result} "
            f"pnl=${trade.pnl:+.2f} size=${trade.bet_size:.2f}",
            style=pnl_style,
        )
        self.write(text)
        self.scroll_end(animate=False)

    def sync_trades(self, trades: list[TradeRow], last_seen_id: int = 0) -> int:
        if not trades:
            return last_seen_id
        newest_id = trades[0].id
        for t in reversed(trades):
            if t.id > last_seen_id:
                self.append_trade(t)
        return newest_id


class ActivityPane(Vertical):
    """Live activity console — trades, fills, signals, bot logs."""

    DEFAULT_CSS = """
    ActivityPane {
        height: 1fr;
        width: 1fr;
        border: solid $border;
        background: $background;
    }
    ActivityPane .activity-header {
        height: 1;
        background: $surface;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(" ACTIVITY / LOGS ", classes="activity-header", id="activity-header")
        yield ActivityLog(id="activity-log", markup=True, highlight=True, wrap=True)

    def _log(self) -> ActivityLog:
        return self.query_one("#activity-log", ActivityLog)

    def append_entry(self, entry: LogEntry) -> None:
        try:
            self._log().append_entry(entry)
        except Exception:
            pass

    def append_activity(self, message: str, level: str = "INFO", source: str = "event") -> None:
        try:
            self._log().append_activity(message, level, source)
        except Exception:
            pass

    def append_trade(self, trade: TradeRow) -> None:
        try:
            self._log().append_trade(trade)
        except Exception:
            pass

    def sync_trades(self, trades: list[TradeRow], last_seen_id: int = 0) -> int:
        try:
            return self._log().sync_trades(trades, last_seen_id)
        except Exception:
            return last_seen_id
