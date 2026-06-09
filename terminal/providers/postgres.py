"""PostgreSQL data provider — wraps existing data/db.py."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from terminal.core.interfaces import BotStateProvider
from terminal.core.models import BotStateSnapshot, TradeRow


class PostgresProvider(BotStateProvider):
    """Async wrapper around synchronous db module."""

    async def get_state(self) -> BotStateSnapshot:
        return await asyncio.to_thread(self._get_state_sync)

    async def get_recent_trades(self, limit: int = 50) -> list[TradeRow]:
        return await asyncio.to_thread(self._get_trades_sync, limit)

    def _get_state_sync(self) -> BotStateSnapshot:
        try:
            from data.db import get_bot_state

            row = get_bot_state()
            return BotStateSnapshot.from_db(row)
        except Exception as exc:
            logger.warning("Failed to fetch bot state: {}", exc)
            return BotStateSnapshot(status="DB_ERROR")

    def _get_trades_sync(self, limit: int) -> list[TradeRow]:
        try:
            from data.pg import dict_cursor, get_connection

            with get_connection() as conn:
                cur = dict_cursor(conn)
                cur.execute(
                    """
                    SELECT id, timestamp, asset, direction, trade_type, result,
                           pnl, bet_size, signal_score, regime, exit_reason
                    FROM trades ORDER BY id DESC LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            return [self._row_to_trade(r) for r in rows]
        except Exception as exc:
            logger.warning("Failed to fetch trades: {}", exc)
            return []

    @staticmethod
    def _row_to_trade(row: dict[str, Any]) -> TradeRow:
        return TradeRow(
            id=int(row["id"]),
            timestamp=row.get("timestamp"),
            asset=str(row.get("asset") or ""),
            direction=str(row.get("direction") or ""),
            trade_type=str(row.get("trade_type") or ""),
            result=str(row.get("result") or ""),
            pnl=float(row.get("pnl") or 0),
            bet_size=float(row.get("bet_size") or 0),
            signal_score=float(row.get("signal_score") or 0),
            regime=str(row.get("regime") or ""),
            exit_reason=str(row.get("exit_reason") or ""),
        )
