"""Orchestrates data refresh cycles and publishes events."""

from __future__ import annotations

import asyncio

from loguru import logger

from terminal.config import get_settings
from terminal.core.models import LogEntry, PositionRow
from terminal.events import EventBus, EventType
from terminal.market_data.providers import PolymarketProvider, PostgresProvider
from terminal.state import StateStore


class DataOrchestrator:
    """Background polling service — non-blocking UI refresh."""

    def __init__(
        self,
        store: StateStore,
        bus: EventBus,
        postgres: PostgresProvider | None = None,
        polymarket: PolymarketProvider | None = None,
    ) -> None:
        self.store = store
        self.bus = bus
        self.postgres = postgres or PostgresProvider()
        self.polymarket = polymarket or PolymarketProvider()
        self._task: asyncio.Task | None = None
        self._running = False
        self._settings = get_settings()

    async def start(self) -> None:
        """Start background polling (call after connect)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        await self.bus.emit(
            EventType.LOG_MESSAGE,
            {"entry": LogEntry(level="INFO", message="Data orchestrator started", source="orchestrator")},
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def refresh_all(self) -> None:
        self.store.set_loading(True)
        try:
            await asyncio.gather(
                self._refresh_bot_state(),
                self._refresh_trades(),
                self._refresh_markets(),
                self._refresh_positions(),
                self._refresh_connectivity(),
            )
            self.store.touch_refresh()
        finally:
            self.store.set_loading(False)

    async def _poll_loop(self) -> None:
        interval = self._settings.tui_refresh_interval
        while self._running:
            try:
                await self.refresh_all()
            except Exception as exc:
                logger.exception("Refresh cycle failed: {}", exc)
                await self.bus.emit(
                    EventType.ERROR,
                    {"message": str(exc)},
                    source="orchestrator",
                )
            await asyncio.sleep(interval)

    async def _refresh_bot_state(self) -> None:
        snapshot = await self.postgres.get_state()
        self.store.set_bot(snapshot)
        await self.bus.emit(EventType.STATE_UPDATED, {"bot": snapshot.model_dump()})

    async def _refresh_trades(self) -> None:
        trades = await self.postgres.get_recent_trades(self._settings.tui_trades_limit)
        self.store.set_trades(trades)
        await self.bus.emit(EventType.TRADES_UPDATED, {"count": len(trades)})

    async def _refresh_markets(self) -> None:
        filt = self.store.state.search_filter
        markets = await self.polymarket.get_markets(
            self._settings.tui_markets_limit,
            slug_filter=filt,
        )
        self.store.set_markets(markets)
        await self.bus.emit(EventType.MARKETS_UPDATED, {"count": len(markets)})

    async def _refresh_positions(self) -> None:
        positions = await asyncio.to_thread(self._fetch_positions_sync)
        self.store.set_positions(positions)
        await self.bus.emit(EventType.POSITIONS_UPDATED, {"count": len(positions)})

    async def _refresh_connectivity(self) -> None:
        status = await self.polymarket.check()
        self.store.set_connectivity(status)
        await self.bus.emit(EventType.CONNECTIVITY_UPDATED, {"status": status.model_dump()})

    @staticmethod
    def _fetch_positions_sync() -> list[PositionRow]:
        try:
            from execution.balance import get_positions

            raw = get_positions()
            rows: list[PositionRow] = []
            for p in raw:
                rows.append(
                    PositionRow(
                        title=str(p.get("title") or p.get("slug") or "")[:60],
                        outcome=str(p.get("outcome") or ""),
                        size=float(p.get("size") or 0),
                        avg_price=float(p.get("avgPrice") or p.get("avg_price") or 0),
                        current_value=float(p.get("currentValue") or p.get("current_value") or 0),
                        pnl=float(p.get("cashPnl") or p.get("pnl") or 0),
                    )
                )
            return rows
        except Exception as exc:
            logger.debug("Positions fetch failed: {}", exc)
            return []
