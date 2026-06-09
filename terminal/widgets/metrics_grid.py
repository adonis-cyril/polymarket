"""Key metrics dashboard grid."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from terminal.core.models import BotStateSnapshot


class MetricsGrid(Static):
    """Compact KPI panel rendered with Rich."""

    DEFAULT_CSS = """
    MetricsGrid {
        height: auto;
        min-height: 7;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._bot = BotStateSnapshot()

    def update_bot(self, bot: BotStateSnapshot) -> None:
        self._bot = bot
        self.refresh()

    def render(self) -> Panel:
        b = self._bot
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold orange1")
        table.add_column()
        table.add_column(style="bold orange1")
        table.add_column()

        pnl_color = "green" if b.balance >= b.peak_balance * 0.95 else "yellow"
        table.add_row(
            "Balance", f"[bold]${b.balance:,.2f}[/]",
            "Status", f"[cyan]{b.status}[/]",
        )
        table.add_row(
            "Win Rate", f"{b.win_rate:.1f}%",
            "Trades", f"{b.total_wins}/{b.total_trades}",
        )
        table.add_row(
            "Level", f"{b.level} → ${b.level_target:,.0f}",
            "Phase", str(b.current_phase),
        )
        table.add_row(
            "Regime", f"[magenta]{b.regime}[/]",
            "Loss Streak", f"[red]{b.consecutive_losses}[/]" if b.consecutive_losses else "0",
        )
        table.add_row(
            "Brier", f"{b.brier_score:.4f}",
            "Peak", f"[{pnl_color}]${b.peak_balance:,.2f}[/]",
        )
        return Panel(table, title="[bold]Bot Metrics[/]", border_style="orange1")
