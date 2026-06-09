"""
Integration service for the full Polymarket active-market list.

The paginated Gamma fetcher lives in execution.active_markets (parallel work).
This module owns cache policy, DB persistence, and consumer-facing accessors.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from config import (
    ACTIVE_MARKETS_CACHE_ENABLED,
    ACTIVE_MARKETS_CACHE_TTL,
    ACTIVE_MARKETS_DB_PERSIST,
    ACTIVE_MARKETS_FETCH_PAGE_SIZE,
)
from data import market_cache
from data.market_types import ActiveMarketRecord

logger = logging.getLogger(__name__)

_mem_records: list[ActiveMarketRecord] | None = None
_mem_fetched_at: float = 0.0


@dataclass
class RefreshResult:
    source: str
    count: int
    inserted_or_updated: int
    deactivated: int
    duration_seconds: float
    fetched_at: datetime


def _cache_is_fresh(fetched_at: Optional[datetime], ttl: int) -> bool:
    if fetched_at is None:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    return age < ttl


def _load_fetcher() -> Callable[..., list[ActiveMarketRecord]]:
    """
    Fetcher contract (execution.active_markets):

        def fetch_all_active_markets(
            *,
            page_size: int = 100,
            on_page: Callable[[int], None] | None = None,
        ) -> list[ActiveMarketRecord]:
            ...
    """
    try:
        from execution.active_markets import fetch_all_active_markets
    except ImportError as exc:
        raise RuntimeError(
            "execution.active_markets.fetch_all_active_markets is not available. "
            "Ensure the active markets fetcher module is installed."
        ) from exc
    return fetch_all_active_markets


def _set_memory_cache(records: list[ActiveMarketRecord]) -> None:
    global _mem_records, _mem_fetched_at
    _mem_records = records
    _mem_fetched_at = time.time()


def _get_memory_cache(ttl: int) -> Optional[list[ActiveMarketRecord]]:
    if _mem_records is None:
        return None
    if time.time() - _mem_fetched_at >= ttl:
        return None
    return list(_mem_records)


def get_active_markets(
    *,
    force_refresh: bool = False,
    event_slug_contains: str = "",
    limit: Optional[int] = None,
) -> list[ActiveMarketRecord]:
    """
    Return active markets, preferring in-memory then DB cache, then Gamma fetch.
    """
    if not ACTIVE_MARKETS_CACHE_ENABLED:
        return _fetch_live(event_slug_contains=event_slug_contains, limit=limit)

    ttl = ACTIVE_MARKETS_CACHE_TTL
    if not force_refresh:
        cached = _get_memory_cache(ttl)
        if cached is not None:
            return _filter_records(cached, event_slug_contains, limit)

        if ACTIVE_MARKETS_DB_PERSIST:
            meta = market_cache.get_cache_meta()
            if _cache_is_fresh(meta.get("last_full_sync_at"), ttl):
                full = _get_memory_cache(ttl)
                if full is None:
                    full = market_cache.list_active_markets()
                    _set_memory_cache(full)
                return _filter_records(full, event_slug_contains, limit)

    result = refresh_active_markets(force=True)
    records = get_active_markets_from_cache(
        event_slug_contains=event_slug_contains,
        limit=limit,
    )
    logger.info(
        "Active market registry refreshed (%d markets, %.1fs via %s)",
        result.count,
        result.duration_seconds,
        result.source,
    )
    return records


def get_active_markets_from_cache(
    *,
    event_slug_contains: str = "",
    limit: Optional[int] = None,
) -> list[ActiveMarketRecord]:
    cached = _get_memory_cache(ACTIVE_MARKETS_CACHE_TTL)
    if cached is not None:
        return _filter_records(cached, event_slug_contains, limit)

    if ACTIVE_MARKETS_DB_PERSIST:
        full = market_cache.list_active_markets()
        if full:
            _set_memory_cache(full)
        return _filter_records(full, event_slug_contains, limit)
    return []


def refresh_active_markets(*, force: bool = False) -> RefreshResult:
    """
    Pull the full active market list from Gamma and persist cache deltas.

    Delta strategy:
    - Upsert only records returned by the fetcher.
    - Deactivate DB rows missing from the latest full sync.
    - Skip network fetch when DB cache is still within TTL unless force=True.
    """
    started = time.time()
    ttl = ACTIVE_MARKETS_CACHE_TTL

    if not force and ACTIVE_MARKETS_CACHE_ENABLED and ACTIVE_MARKETS_DB_PERSIST:
        meta = market_cache.get_cache_meta()
        if _cache_is_fresh(meta.get("last_full_sync_at"), ttl):
            count = market_cache.count_active_markets()
            fetched_at = meta.get("last_full_sync_at") or datetime.now(timezone.utc)
            records = market_cache.list_active_markets()
            _set_memory_cache(records)
            return RefreshResult(
                source="db-cache",
                count=count,
                inserted_or_updated=0,
                deactivated=0,
                duration_seconds=time.time() - started,
                fetched_at=fetched_at,
            )

    market_cache.update_cache_meta(sync_status="running")
    fetcher = _load_fetcher()
    records = fetcher(page_size=ACTIVE_MARKETS_FETCH_PAGE_SIZE)
    fetched_at = datetime.now(timezone.utc)

    inserted_or_updated = 0
    deactivated = 0
    if ACTIVE_MARKETS_DB_PERSIST:
        inserted_or_updated = market_cache.upsert_markets(records, fetched_at=fetched_at)
        deactivated = market_cache.deactivate_missing(
            {record.condition_id for record in records},
            deactivated_at=fetched_at,
        )
        market_cache.update_cache_meta(
            last_full_sync_at=fetched_at,
            last_sync_count=len(records),
            sync_status="idle",
        )

    _set_memory_cache(records)
    duration = time.time() - started
    logger.info(
        "Synced %d active markets (%d upserted, %d deactivated) in %.1fs",
        len(records),
        inserted_or_updated,
        deactivated,
        duration,
    )
    return RefreshResult(
        source="gamma",
        count=len(records),
        inserted_or_updated=inserted_or_updated,
        deactivated=deactivated,
        duration_seconds=duration,
        fetched_at=fetched_at,
    )


def _fetch_live(
    *,
    event_slug_contains: str = "",
    limit: Optional[int] = None,
) -> list[ActiveMarketRecord]:
    fetcher = _load_fetcher()
    records = fetcher(page_size=ACTIVE_MARKETS_FETCH_PAGE_SIZE)
    return _filter_records(records, event_slug_contains, limit)


def _filter_records(
    records: list[ActiveMarketRecord],
    event_slug_contains: str,
    limit: Optional[int],
) -> list[ActiveMarketRecord]:
    if event_slug_contains:
        needle = event_slug_contains.lower()
        records = [
            record
            for record in records
            if needle in record.event_slug.lower() or needle in record.market_slug.lower()
        ]
    if limit is not None:
        records = records[:limit]
    return records


def get_active_5min_markets(*, force_refresh: bool = False) -> list[ActiveMarketRecord]:
    """Convenience accessor for crypto 5-min UP/DOWN slugs."""
    return get_active_markets(
        force_refresh=force_refresh,
        event_slug_contains="-updown-5m",
    )


def get_cache_status() -> dict:
    meta = market_cache.get_cache_meta() if ACTIVE_MARKETS_DB_PERSIST else {}
    return {
        "cache_enabled": ACTIVE_MARKETS_CACHE_ENABLED,
        "db_persist": ACTIVE_MARKETS_DB_PERSIST,
        "ttl_seconds": ACTIVE_MARKETS_CACHE_TTL,
        "page_size": ACTIVE_MARKETS_FETCH_PAGE_SIZE,
        "memory_cached": _mem_records is not None,
        "memory_age_seconds": round(time.time() - _mem_fetched_at, 1) if _mem_records else None,
        "db_active_count": market_cache.count_active_markets() if ACTIVE_MARKETS_DB_PERSIST else None,
        "last_full_sync_at": meta.get("last_full_sync_at"),
        "last_sync_count": meta.get("last_sync_count"),
        "sync_status": meta.get("sync_status"),
    }
