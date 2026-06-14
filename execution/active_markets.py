"""
Adapter for the market registry: exposes fetch_all_active_markets() returning
ActiveMarketRecord rows expected by data.market_registry.

Pagination and Gamma HTTP live in data.active_markets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from data.active_markets import ActiveMarket, fetch_all_active_markets as _fetch_raw
from data.market_types import ActiveMarketRecord


def _parse_end_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _to_record(market: ActiveMarket) -> ActiveMarketRecord:
    return ActiveMarketRecord(
        condition_id=market.condition_id,
        event_id=market.event_id or "",
        event_slug=market.event_slug or "",
        market_slug=market.slug,
        question=market.question or market.event_title or "",
        outcomes=list(market.outcomes),
        clob_token_ids=list(market.clob_token_ids),
        active=market.active and not market.archived,
        closed=market.closed,
        end_date=_parse_end_date(market.end_date),
        volume_24hr=market.volume_24hr or None,
        liquidity=market.liquidity or None,
    )


def fetch_all_active_markets(
    *,
    page_size: int = 100,
    on_page: Callable[[int], None] | None = None,
) -> list[ActiveMarketRecord]:
    """Fetch all active Polymarket markets (registry contract)."""
    del page_size  # keyset endpoint caps at 100; page size is not configurable

    def _on_page(page_index: int, _batch: list[ActiveMarket], _cursor: Optional[str]) -> None:
        if on_page:
            on_page(page_index)

    result = _fetch_raw(on_page=_on_page if on_page else None)
    return [_to_record(m) for m in result.markets]
