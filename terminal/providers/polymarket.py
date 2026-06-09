"""Polymarket API connectivity and market data."""

from __future__ import annotations

import asyncio
import time

from loguru import logger

from terminal.core.interfaces import ConnectivityProvider, MarketDataProvider
from terminal.core.models import ConnectionState, ConnectivityStatus, MarketRow


class PolymarketProvider(ConnectivityProvider, MarketDataProvider):
    """Wraps utils.polymarket_connectivity and market registry."""

    async def check(self) -> ConnectivityStatus:
        return await asyncio.to_thread(self._check_sync)

    async def get_markets(self, limit: int = 50, slug_filter: str = "") -> list[MarketRow]:
        return await asyncio.to_thread(self._get_markets_sync, limit, slug_filter)

    def _check_sync(self) -> ConnectivityStatus:
        status = ConnectivityStatus()
        try:
            from utils.polymarket_connectivity import clob_get, gamma_get, install_dns_patch

            install_dns_patch()

            t0 = time.perf_counter()
            resp = gamma_get("/events", params={"limit": 1})
            resp.raise_for_status()
            status.gamma_latency_ms = (time.perf_counter() - t0) * 1000
            status.gamma_api = ConnectionState.OK
        except Exception as exc:
            status.gamma_api = ConnectionState.FAIL
            status.message = f"Gamma: {exc}"

        try:
            from utils.polymarket_connectivity import clob_get

            t0 = time.perf_counter()
            resp = clob_get("/time")
            resp.raise_for_status()
            status.clob_latency_ms = (time.perf_counter() - t0) * 1000
            status.clob_api = ConnectionState.OK
        except Exception as exc:
            status.clob_api = ConnectionState.FAIL
            if status.message:
                status.message += f"; CLOB: {exc}"
            else:
                status.message = f"CLOB: {exc}"

        try:
            from data.pg import get_connection

            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
            status.database = ConnectionState.OK
        except Exception:
            status.database = ConnectionState.FAIL

        return status

    def _get_markets_sync(self, limit: int, slug_filter: str) -> list[MarketRow]:
        # Fast path first — avoids full-catalog sync on cold cache
        rows = self._fetch_gamma_fallback(limit, slug_filter)
        if rows:
            return rows
        try:
            from data.market_registry import get_active_markets

            kwargs: dict = {}
            if slug_filter:
                kwargs["event_slug_contains"] = slug_filter
            records = get_active_markets(**kwargs)
            for rec in records[:limit]:
                outcomes = "/".join(rec.outcomes) if rec.outcomes else ""
                rows.append(
                    MarketRow(
                        slug=rec.market_slug or rec.event_slug,
                        question=rec.question[:80] if rec.question else "",
                        volume_24hr=float(rec.volume_24hr or 0),
                        liquidity=float(rec.liquidity or 0),
                        outcomes=outcomes,
                        active=rec.active,
                    )
                )
        except Exception as exc:
            logger.debug("Market registry unavailable: {}", exc)
        return rows

    def _fetch_gamma_fallback(self, limit: int, slug_filter: str) -> list[MarketRow]:
        try:
            from utils.polymarket_connectivity import gamma_get, install_dns_patch

            install_dns_patch()
            params: dict = {"active": "true", "closed": "false", "limit": min(limit, 100)}
            if slug_filter:
                params["slug"] = slug_filter
            resp = gamma_get("/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
            markets = data if isinstance(data, list) else data.get("markets", [])
            rows = []
            for m in markets[:limit]:
                outcomes_raw = m.get("outcomes", [])
                if isinstance(outcomes_raw, str):
                    import json

                    try:
                        outcomes_raw = json.loads(outcomes_raw)
                    except json.JSONDecodeError:
                        outcomes_raw = []
                rows.append(
                    MarketRow(
                        slug=str(m.get("slug") or ""),
                        question=str(m.get("question") or "")[:80],
                        volume_24hr=float(m.get("volume24hr") or 0),
                        liquidity=float(m.get("liquidity") or 0),
                        outcomes="/".join(str(o) for o in outcomes_raw),
                        active=bool(m.get("active", True)),
                    )
                )
            return rows
        except Exception as exc:
            logger.warning("Gamma fallback failed: {}", exc)
            return []
