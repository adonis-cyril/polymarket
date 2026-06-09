"""Abstract interfaces for data providers and services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from terminal.core.models import (
    BotStateSnapshot,
    ConnectivityStatus,
    MarketRow,
    TradeRow,
)


class BotStateProvider(ABC):
    @abstractmethod
    async def get_state(self) -> BotStateSnapshot:
        ...

    @abstractmethod
    async def get_recent_trades(self, limit: int = 50) -> list[TradeRow]:
        ...


class MarketDataProvider(ABC):
    @abstractmethod
    async def get_markets(self, limit: int = 50, slug_filter: str = "") -> list[MarketRow]:
        ...


class ConnectivityProvider(ABC):
    @abstractmethod
    async def check(self) -> ConnectivityStatus:
        ...


class CommandResult:
    def __init__(self, success: bool, message: str, data: Optional[dict] = None):
        self.success = success
        self.message = message
        self.data = data or {}
