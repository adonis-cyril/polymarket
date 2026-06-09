"""Centralized application state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd

from terminal.core.models import (
    BotStateSnapshot,
    ConnectivityStatus,
    LogEntry,
    MarketRow,
    MetricPoint,
    PositionRow,
    TradeRow,
)


class LeftView(str, Enum):
    OVERVIEW = "overview"
    MARKETS = "markets"
    POSITIONS = "positions"


@dataclass
class AppState:
    bot: BotStateSnapshot = field(default_factory=BotStateSnapshot)
    connectivity: ConnectivityStatus = field(default_factory=ConnectivityStatus)
    trades: list[TradeRow] = field(default_factory=list)
    markets: list[MarketRow] = field(default_factory=list)
    positions: list[PositionRow] = field(default_factory=list)
    logs: list[LogEntry] = field(default_factory=list)
    metrics: list[MetricPoint] = field(default_factory=list)
    theme: str = "bloomberg"
    loading: bool = False
    last_refresh: Optional[datetime] = None
    session_started: datetime = field(default_factory=datetime.now)
    command_history: list[str] = field(default_factory=list)
    search_filter: str = ""
    left_view: LeftView = LeftView.OVERVIEW
    connected: bool = False
    mode: str = "paper"
    strategy: str = "standard"

    @property
    def trades_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(
                columns=["id", "asset", "direction", "result", "pnl", "bet_size", "regime"]
            )
        return pd.DataFrame([t.model_dump() for t in self.trades])

    @property
    def markets_df(self) -> pd.DataFrame:
        if not self.markets:
            return pd.DataFrame(columns=["slug", "question", "volume_24hr", "liquidity"])
        return pd.DataFrame([m.model_dump() for m in self.markets])


class StateStore:
    """Thread-safe-ish state container with mutation helpers."""

    def __init__(self) -> None:
        self._state = AppState()

    @property
    def state(self) -> AppState:
        return self._state

    def set_bot(self, snapshot: BotStateSnapshot) -> None:
        self._state.bot = snapshot
        self._append_metric(snapshot.balance)

    def set_connectivity(self, status: ConnectivityStatus) -> None:
        self._state.connectivity = status

    def set_trades(self, trades: list[TradeRow]) -> None:
        self._state.trades = trades

    def set_markets(self, markets: list[MarketRow]) -> None:
        self._state.markets = markets

    def set_positions(self, positions: list[PositionRow]) -> None:
        self._state.positions = positions

    def set_left_view(self, view: LeftView) -> None:
        self._state.left_view = view

    def set_connected(self, connected: bool) -> None:
        self._state.connected = connected

    def set_mode(self, mode: str, strategy: str = "") -> None:
        self._state.mode = mode
        if strategy:
            self._state.strategy = strategy

    def add_log(self, entry: LogEntry) -> None:
        self._state.logs.append(entry)
        if len(self._state.logs) > 500:
            self._state.logs = self._state.logs[-500:]

    def set_theme(self, theme: str) -> None:
        self._state.theme = theme

    def set_loading(self, loading: bool) -> None:
        self._state.loading = loading

    def touch_refresh(self) -> None:
        self._state.last_refresh = datetime.now()

    def _append_metric(self, balance: float) -> None:
        from time import time

        from terminal.config import get_settings

        settings = get_settings()
        self._state.metrics.append(
            MetricPoint(timestamp=time(), value=balance, label="balance")
        )
        max_pts = settings.tui_chart_history
        if len(self._state.metrics) > max_pts:
            self._state.metrics = self._state.metrics[-max_pts:]
