"""Searchable data table backed by pandas."""

from __future__ import annotations

import pandas as pd
from textual.widgets import DataTable

from terminal.core.models import MarketRow, TradeRow


class SearchableDataTable(DataTable):
    """DataTable with filter support and typed row loading."""

    def __init__(self, *args, searchable: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.searchable = searchable
        self._filter = ""
        self.zebra_stripes = True
        self.cursor_type = "row"

    def set_filter(self, text: str) -> None:
        self._filter = text.lower().strip()

    def load_trades(self, trades: list[TradeRow]) -> None:
        self.clear(columns=True)
        self.add_columns("ID", "Asset", "Dir", "Type", "Result", "PnL", "Size", "Regime")
        for t in trades:
            row_text = f"{t.asset} {t.direction} {t.result} {t.regime}".lower()
            if self._filter and self._filter not in row_text:
                continue
            pnl_style = "metric-positive" if t.pnl >= 0 else "metric-negative"
            self.add_row(
                str(t.id),
                t.asset.upper(),
                t.direction.upper(),
                t.trade_type,
                t.result,
                f"${t.pnl:+.2f}",
                f"${t.bet_size:.2f}",
                t.regime,
                key=str(t.id),
            )

    def load_markets(self, markets: list[MarketRow]) -> None:
        self.clear(columns=True)
        self.add_columns("Slug", "Question", "Vol 24h", "Liquidity", "Outcomes")
        for m in markets:
            hay = f"{m.slug} {m.question}".lower()
            if self._filter and self._filter not in hay:
                continue
            self.add_row(
                m.slug[:30],
                m.question[:40],
                f"${m.volume_24hr:,.0f}",
                f"${m.liquidity:,.0f}",
                m.outcomes[:20],
                key=m.slug,
            )

    def load_dataframe(self, df: pd.DataFrame, columns: list[str] | None = None) -> None:
        self.clear(columns=True)
        if df.empty:
            return
        cols = columns or list(df.columns)
        self.add_columns(*[str(c) for c in cols])
        for _, row in df.iterrows():
            values = [str(row.get(c, ""))[:40] for c in cols]
            if self._filter:
                if self._filter not in " ".join(values).lower():
                    continue
            self.add_row(*values)
