"""Trading engine — wraps execution/order.py with paper/live awareness."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from loguru import logger

from terminal.core.interfaces import CommandResult


@dataclass
class OrderRequest:
    side: str = "up"  # up | down
    size_usdc: float = 2.0
    shares: float | None = None
    urgent: bool = False
    live: bool = False
    order_id: str | None = None


class TradingEngine:
    """Async facade over CLOB order placement."""

    def __init__(self) -> None:
        self._paper_mode = os.getenv("BOT_MODE", "standard") != "live"

    @property
    def is_live_capable(self) -> bool:
        return bool(os.getenv("POLY_PRIVATE_KEY"))

    async def buy(self, req: OrderRequest) -> CommandResult:
        return await asyncio.to_thread(self._buy_sync, req)

    async def sell(self, req: OrderRequest) -> CommandResult:
        return await asyncio.to_thread(self._sell_sync, req)

    async def cancel(self, req: OrderRequest) -> CommandResult:
        return await asyncio.to_thread(self._cancel_sync, req)

    def _resolve_market(self):
        from tests.live_staircase.helpers import discover_btc_market

        market = discover_btc_market()
        if not market:
            raise RuntimeError("No active BTC 5m market found")
        return market

    def _buy_sync(self, req: OrderRequest) -> CommandResult:
        from tests.live_staircase.helpers import (
            fetch_book,
            normalize_side,
            token_for_side,
        )

        market = self._resolve_market()
        side = normalize_side(req.side)
        token_id = token_for_side(market, side)
        book = fetch_book(token_id)
        best_ask = book.best_ask if book.best_ask < 1 else book.mid
        size = req.size_usdc

        if not req.live:
            msg = (
                f"[PAPER] BUY {side.upper()} ${size:.2f} @ {best_ask:.3f} "
                f"(~{size / best_ask:.1f} shares) — use 'buy --live' for real orders"
            )
            logger.info(msg)
            return CommandResult(True, msg, {"paper": True, "side": side, "price": best_ask})

        if not self.is_live_capable:
            return CommandResult(False, "POLY_PRIVATE_KEY not set — cannot place live orders")

        from execution.order import place_buy_order

        result = place_buy_order(token_id, size, best_ask)
        if result.success:
            msg = (
                f"BUY {side.upper()} filled {result.fill_size:.2f} @ ${result.fill_price:.3f} "
                f"({result.execution_type}) id={result.order_id[:8] if result.order_id else '—'}"
            )
            logger.info(msg)
            return CommandResult(True, msg, {"order_id": result.order_id})
        return CommandResult(False, f"Buy failed: {result.error}")

    def _sell_sync(self, req: OrderRequest) -> CommandResult:
        from tests.live_staircase.helpers import (
            fetch_book,
            normalize_side,
            resolve_shares,
            token_for_side,
        )
        from tests.live_staircase.helpers import RunContext

        market = self._resolve_market()
        side = normalize_side(req.side)
        token_id = token_for_side(market, side)
        book = fetch_book(token_id)
        target = book.best_bid if book.best_bid > 0 else book.mid

        ctx = RunContext(live=req.live, shares=req.shares)
        try:
            shares = resolve_shares(ctx, token_id)
        except ValueError as exc:
            return CommandResult(False, str(exc))

        if not req.live:
            label = "urgent exit" if req.urgent else "sell"
            msg = f"[PAPER] {label.upper()} {side.upper()} {shares:.2f} shares @ {target:.3f}"
            logger.info(msg)
            return CommandResult(True, msg, {"paper": True})

        if not self.is_live_capable:
            return CommandResult(False, "POLY_PRIVATE_KEY not set — cannot place live orders")

        from execution.order import place_sell_order

        result = place_sell_order(token_id, shares, target, urgent=req.urgent)
        if result.success:
            msg = (
                f"SELL {side.upper()} {result.fill_size:.2f} @ ${result.fill_price:.3f} "
                f"({result.execution_type})"
            )
            logger.info(msg)
            return CommandResult(True, msg)
        return CommandResult(False, f"Sell failed: {result.error}")

    def _cancel_sync(self, req: OrderRequest) -> CommandResult:
        if not req.live:
            target = req.order_id or "all open orders"
            msg = f"[PAPER] Cancel {target} — use 'cancel --live' for real cancellation"
            logger.info(msg)
            return CommandResult(True, msg, {"paper": True})

        if not self.is_live_capable:
            return CommandResult(False, "POLY_PRIVATE_KEY not set — cannot cancel orders")

        try:
            from execution.order import cancel_all_orders, get_clob_client

            if req.order_id:
                client = get_clob_client()
                client.cancel(req.order_id)
                return CommandResult(True, f"Cancelled order {req.order_id[:12]}")
            cancel_all_orders()
            return CommandResult(True, "Cancelled all open orders")
        except Exception as exc:
            logger.exception("Cancel failed")
            return CommandResult(False, f"Cancel failed: {exc}")
