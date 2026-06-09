"""Core domain models for the TUI."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConnectionState(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class BotStateSnapshot(BaseModel):
    status: str = "OFFLINE"
    balance: float = 0.0
    level: int = 0
    level_target: float = 0.0
    peak_balance: float = 0.0
    total_trades: int = 0
    total_wins: int = 0
    win_rate: float = 0.0
    brier_score: float = 0.0
    regime: str = "UNKNOWN"
    consecutive_losses: int = 0
    current_phase: int = 1
    updated_at: Optional[datetime] = None

    @classmethod
    def from_db(cls, row: dict[str, Any]) -> "BotStateSnapshot":
        if not row:
            return cls()
        return cls(
            status=str(row.get("status", "OFFLINE")),
            balance=float(row.get("current_balance") or 0),
            level=int(row.get("current_level") or 0),
            level_target=float(row.get("level_target") or 0),
            peak_balance=float(row.get("peak_balance") or 0),
            total_trades=int(row.get("total_trades") or 0),
            total_wins=int(row.get("total_wins") or 0),
            win_rate=float(row.get("win_rate") or 0) * 100,
            brier_score=float(row.get("brier_score") or 0),
            regime=str(row.get("current_regime") or "UNKNOWN"),
            consecutive_losses=int(row.get("consecutive_losses") or 0),
            current_phase=int(row.get("current_phase") or 1),
            updated_at=row.get("updated_at"),
        )


class TradeRow(BaseModel):
    id: int
    timestamp: Optional[datetime] = None
    asset: str = ""
    direction: str = ""
    trade_type: str = ""
    result: str = ""
    pnl: float = 0.0
    bet_size: float = 0.0
    signal_score: float = 0.0
    regime: str = ""
    exit_reason: str = ""


class MarketRow(BaseModel):
    slug: str
    question: str
    volume_24hr: float = 0.0
    liquidity: float = 0.0
    outcomes: str = ""
    active: bool = True


class PositionRow(BaseModel):
    title: str = ""
    outcome: str = ""
    size: float = 0.0
    avg_price: float = 0.0
    current_value: float = 0.0
    pnl: float = 0.0


class ConnectivityStatus(BaseModel):
    gamma_api: ConnectionState = ConnectionState.UNKNOWN
    clob_api: ConnectionState = ConnectionState.UNKNOWN
    database: ConnectionState = ConnectionState.UNKNOWN
    gamma_latency_ms: Optional[float] = None
    clob_latency_ms: Optional[float] = None
    message: str = ""


class MetricPoint(BaseModel):
    timestamp: float
    value: float
    label: str = "balance"


class LogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    level: str = "INFO"
    message: str = ""
    source: str = "tui"
