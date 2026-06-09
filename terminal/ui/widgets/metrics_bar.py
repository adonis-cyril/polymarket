"""Bottom metrics bar — trades, P&L, return%, duration, mem."""

from __future__ import annotations

import resource
import threading
from datetime import datetime

from textual.reactive import reactive
from textual.widgets import Static

from terminal.core.models import BotStateSnapshot
from terminal.config import get_settings


class MetricsBar(Static):
    """Hummingbot-style bottom navigation metrics."""

    DEFAULT_CSS = """
    MetricsBar {
        dock: bottom;
        height: 1;
        width: 100%;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    trades: reactive[int] = reactive(0)
    pnl: reactive[float] = reactive(0.0)
    return_pct: reactive[float] = reactive(0.0)
    duration: reactive[str] = reactive("00:00:00")
    threads: reactive[int] = reactive(1)
    mem_mb: reactive[float] = reactive(0.0)

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick_duration)

    def _tick_duration(self) -> None:
        started = getattr(self, "_session_started", datetime.now())
        delta = datetime.now() - started
        hrs, rem = divmod(int(delta.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        self.duration = f"{hrs:02d}:{mins:02d}:{secs:02d}"
        self.threads = threading.active_count()
        try:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # macOS: bytes; Linux: kilobytes
            self.mem_mb = rss / (1024 * 1024) if rss > 10_000_000 else rss / 1024
        except Exception:
            self.mem_mb = 0.0

    def render(self) -> str:
        pnl_style = "+" if self.pnl >= 0 else ""
        return (
            f"Trades {self.trades} │ "
            f"P&L {pnl_style}${self.pnl:,.2f} │ "
            f"Return {self.return_pct:+.1f}% │ "
            f"Duration {self.duration} │ "
            f"Thr {self.threads} │ "
            f"Mem {self.mem_mb:.0f}MB"
        )

    def update_from_bot(self, bot: BotStateSnapshot, session_started: datetime) -> None:
        self._session_started = session_started
        self.trades = bot.total_trades
        settings = get_settings()
        start_bal = settings.starting_bankroll or settings.initial_bankroll or 20.0
        self.pnl = bot.balance - start_bal
        self.return_pct = ((bot.balance / start_bal) - 1) * 100 if start_bal else 0.0
        self._tick_duration()
