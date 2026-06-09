"""Left pane — welcome screen, markets, positions."""

from __future__ import annotations

from textual.widgets import DataTable, Static

from terminal.core.models import BotStateSnapshot, MarketRow, PositionRow, TradeRow
from terminal.state import LeftView
from terminal.ui.widgets.welcome_art import build_welcome_panel


class LeftPane(Static):
    """Switchable data view — overview (welcome) | markets | positions."""

    DEFAULT_CSS = """
    LeftPane {
        height: 1fr;
        width: 1fr;
        border: solid $border;
    }
    LeftPane .pane-title {
        height: 1;
        background: $surface;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    LeftPane .overview-panel {
        height: 1fr;
        padding: 0 1;
    }
    LeftPane DataTable {
        height: 1fr;
    }
    LeftPane .hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._view = LeftView.OVERVIEW
        self._connected = False
        self._bot = BotStateSnapshot()
        self._markets: list[MarketRow] = []
        self._positions: list[PositionRow] = []
        self._trades: list[TradeRow] = []

    def compose(self):
        yield Static(" POLYADONIS ", classes="pane-title", id="left-title")
        yield Static("", classes="overview-panel", id="overview")
        yield DataTable(id="markets-table", zebra_stripes=True, cursor_type="row", classes="hidden")
        yield DataTable(id="positions-table", zebra_stripes=True, cursor_type="row", classes="hidden")

    def on_mount(self) -> None:
        self._apply_view()
        self._refresh_content()

    def set_view(self, view: LeftView) -> None:
        self._view = view
        self._apply_view()

    def update_data(
        self,
        bot: BotStateSnapshot,
        markets: list[MarketRow],
        positions: list[PositionRow],
        trades: list[TradeRow],
        view: LeftView | None = None,
        *,
        connected: bool = False,
    ) -> None:
        self._bot = bot
        self._markets = markets
        self._positions = positions
        self._trades = trades
        self._connected = connected
        if view is not None and view != self._view:
            self._view = view
            self._apply_view()
        self._refresh_content()

    def _apply_view(self) -> None:
        titles = {
            LeftView.OVERVIEW: " POLYADONIS ",
            LeftView.MARKETS: " MARKETS ",
            LeftView.POSITIONS: " POSITIONS ",
        }
        self.query_one("#left-title", Static).update(titles[self._view])
        overview = self.query_one("#overview", Static)
        markets = self.query_one("#markets-table", DataTable)
        positions = self.query_one("#positions-table", DataTable)
        overview.set_class(self._view != LeftView.OVERVIEW, "hidden")
        markets.set_class(self._view != LeftView.MARKETS, "hidden")
        positions.set_class(self._view != LeftView.POSITIONS, "hidden")

    def _refresh_content(self) -> None:
        if self._view == LeftView.OVERVIEW:
            self.query_one("#overview", Static).update(self._welcome_panel())
        elif self._view == LeftView.MARKETS:
            self._load_markets(self.query_one("#markets-table", DataTable))
        else:
            self._load_positions(self.query_one("#positions-table", DataTable))

    def _welcome_panel(self):
        panel = build_welcome_panel()
        if self._connected:
            panel.subtitle = "[dim]connected — type status for health[/]"
        return panel

    def _load_markets(self, table: DataTable) -> None:
        table.clear(columns=True)
        table.add_columns("Slug", "Question", "Vol", "Liq", "Outcomes")
        for m in self._markets[:40]:
            table.add_row(
                m.slug[:28],
                m.question[:36],
                f"${m.volume_24hr:,.0f}",
                f"${m.liquidity:,.0f}",
                m.outcomes[:16],
                key=m.slug,
            )

    def _load_positions(self, table: DataTable) -> None:
        table.clear(columns=True)
        if self._positions:
            table.add_columns("Outcome", "Size", "Avg", "Value", "PnL")
            for i, p in enumerate(self._positions[:30]):
                table.add_row(
                    p.outcome[:12],
                    f"{p.size:.1f}",
                    f"{p.avg_price:.3f}",
                    f"${p.current_value:.2f}",
                    f"${p.pnl:+.2f}",
                    key=str(i),
                )
            return
        table.add_columns("Asset", "Dir", "Result", "PnL", "Size")
        for t in self._trades[:20]:
            table.add_row(
                t.asset.upper(),
                t.direction.upper(),
                t.result,
                f"${t.pnl:+.2f}",
                f"${t.bet_size:.2f}",
                key=str(t.id),
            )
