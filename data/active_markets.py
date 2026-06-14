"""
Fetch all active Polymarket markets via the Gamma API.

Uses cursor-based (keyset) pagination on GET /markets/keyset — the recommended
approach for large result sets. Offset-based pagination is rejected (HTTP 422)
on the keyset endpoint and is unreliable for bulk syncs.

Gamma API: https://gamma-api.polymarket.com (no auth required)
Rate limits (documented): /markets 300 req/10s; combined /markets+/events 900/10s.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests

from utils.polymarket_connectivity import gamma_get

logger = logging.getLogger(__name__)

KEYSET_PATH = "/markets/keyset"
DEFAULT_PAGE_LIMIT = 100  # keyset endpoint caps at 100 regardless of higher limit
DEFAULT_PAGE_DELAY = 0.1  # ~10 req/s, well under 300 req/10s /markets limit
DEFAULT_CACHE_TTL = 300  # seconds


@dataclass(frozen=True)
class ActiveMarket:
    """Normalized view of a single tradeable Polymarket market."""

    market_id: str
    question: str
    condition_id: str
    slug: str
    active: bool
    closed: bool
    archived: bool
    clob_token_ids: tuple[str, ...]
    outcomes: tuple[str, ...]
    outcome_prices: tuple[float, ...]
    volume: float
    volume_24hr: float
    liquidity: float
    end_date: str
    event_id: Optional[str] = None
    event_slug: Optional[str] = None
    event_title: Optional[str] = None


@dataclass
class ActiveMarketsResult:
    """Result of a full active-markets fetch."""

    markets: list[ActiveMarket] = field(default_factory=list)
    pages_fetched: int = 0
    fetched_at: float = 0.0
    duration_seconds: float = 0.0
    truncated: bool = False

    @property
    def total(self) -> int:
        return len(self.markets)


def _parse_json_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _parse_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_market(raw: dict) -> Optional[ActiveMarket]:
    """Convert a Gamma API market object into ActiveMarket."""
    condition_id = raw.get("conditionId") or raw.get("condition_id") or ""
    if not condition_id:
        return None

    clob_token_ids = tuple(str(t) for t in _parse_json_list(raw.get("clobTokenIds")))
    outcomes = tuple(str(o) for o in _parse_json_list(raw.get("outcomes")))
    outcome_prices = tuple(
        _parse_float(p) for p in _parse_json_list(raw.get("outcomePrices"))
    )

    events = raw.get("events") or []
    event = events[0] if events else {}

    return ActiveMarket(
        market_id=str(raw.get("id", "")),
        question=str(raw.get("question", "")),
        condition_id=condition_id,
        slug=str(raw.get("slug", "")),
        active=bool(raw.get("active", False)),
        closed=bool(raw.get("closed", False)),
        archived=bool(raw.get("archived", False)),
        clob_token_ids=clob_token_ids,
        outcomes=outcomes,
        outcome_prices=outcome_prices,
        volume=_parse_float(raw.get("volume")),
        volume_24hr=_parse_float(raw.get("volume24hr")),
        liquidity=_parse_float(raw.get("liquidity")),
        end_date=str(raw.get("endDate", "")),
        event_id=str(event.get("id")) if event.get("id") is not None else None,
        event_slug=event.get("slug"),
        event_title=event.get("title"),
    )


def fetch_active_markets_page(
    *,
    after_cursor: Optional[str] = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    include_archived: bool = False,
    timeout: Optional[float] = None,
) -> tuple[list[ActiveMarket], Optional[str]]:
    """
    Fetch one page of active markets.

    Returns:
        (markets, next_cursor) — next_cursor is None when there are no more pages.
    """
    params: dict[str, object] = {
        "active": "true",
        "closed": "false",
        "limit": min(limit, DEFAULT_PAGE_LIMIT),
    }
    if not include_archived:
        params["archived"] = "false"
    if after_cursor:
        params["after_cursor"] = after_cursor

    kwargs: dict = {"params": params}
    if timeout is not None:
        kwargs["timeout"] = timeout

    resp = gamma_get(KEYSET_PATH, **kwargs)
    resp.raise_for_status()
    payload = resp.json()

    if isinstance(payload, list):
        raw_markets = payload
        next_cursor = None
    elif isinstance(payload, dict):
        raw_markets = payload.get("markets") or payload.get("data") or []
        next_cursor = payload.get("next_cursor") or payload.get("nextCursor")
    else:
        raw_markets = []
        next_cursor = None

    markets: list[ActiveMarket] = []
    for raw in raw_markets:
        if not isinstance(raw, dict):
            continue
        market = parse_market(raw)
        if market is not None:
            markets.append(market)

    return markets, next_cursor


def fetch_all_active_markets(
    *,
    include_archived: bool = False,
    max_pages: Optional[int] = None,
    page_delay: float = DEFAULT_PAGE_DELAY,
    on_page: Optional[Callable[[int, list[ActiveMarket], Optional[str]], None]] = None,
) -> ActiveMarketsResult:
    """
    Fetch all currently active Polymarket markets using keyset pagination.

    Args:
        include_archived: Include archived markets that are still marked active.
        max_pages: Stop after this many pages (for testing or partial syncs).
        page_delay: Seconds to sleep between page requests (rate limiting).
        on_page: Optional callback(page_index, markets, next_cursor) after each page.
    """
    started = time.time()
    all_markets: list[ActiveMarket] = []
    cursor: Optional[str] = None
    page_index = 0
    truncated = False

    while True:
        if max_pages is not None and page_index >= max_pages:
            truncated = True
            break

        try:
            batch, cursor = fetch_active_markets_page(
                after_cursor=cursor,
                include_archived=include_archived,
            )
        except requests.RequestException as exc:
            logger.error("Failed fetching active markets page %d: %s", page_index + 1, exc)
            raise

        all_markets.extend(batch)
        page_index += 1

        if on_page:
            on_page(page_index, batch, cursor)

        logger.debug(
            "Fetched page %d (%d markets, total %d, more=%s)",
            page_index, len(batch), len(all_markets), bool(cursor),
        )

        if not cursor or not batch:
            break

        if page_delay > 0:
            time.sleep(page_delay)

    result = ActiveMarketsResult(
        markets=all_markets,
        pages_fetched=page_index,
        fetched_at=time.time(),
        duration_seconds=time.time() - started,
        truncated=truncated,
    )
    logger.info(
        "Fetched %d active markets in %d pages (%.1fs)%s",
        result.total,
        result.pages_fetched,
        result.duration_seconds,
        " [truncated]" if truncated else "",
    )
    return result


def markets_to_dicts(markets: list[ActiveMarket]) -> list[dict]:
    """Serialize ActiveMarket list for JSON export."""
    return [
        {
            "market_id": m.market_id,
            "question": m.question,
            "condition_id": m.condition_id,
            "slug": m.slug,
            "active": m.active,
            "closed": m.closed,
            "archived": m.archived,
            "clob_token_ids": list(m.clob_token_ids),
            "outcomes": list(m.outcomes),
            "outcome_prices": list(m.outcome_prices),
            "volume": m.volume,
            "volume_24hr": m.volume_24hr,
            "liquidity": m.liquidity,
            "end_date": m.end_date,
            "event_id": m.event_id,
            "event_slug": m.event_slug,
            "event_title": m.event_title,
        }
        for m in markets
    ]


def load_cached_markets(
    path: Path,
    *,
    ttl_seconds: float = DEFAULT_CACHE_TTL,
) -> Optional[ActiveMarketsResult]:
    """Load markets from a JSON cache file if fresh enough."""
    if not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read cache %s: %s", path, exc)
        return None

    fetched_at = payload.get("fetched_at", 0.0)
    if time.time() - fetched_at > ttl_seconds:
        return None

    markets = []
    for item in payload.get("markets", []):
        if not isinstance(item, dict):
            continue
        market = parse_market(item) or _market_from_export(item)
        if market:
            markets.append(market)

    return ActiveMarketsResult(
        markets=markets,
        pages_fetched=payload.get("pages_fetched", 0),
        fetched_at=fetched_at,
        duration_seconds=payload.get("duration_seconds", 0.0),
        truncated=bool(payload.get("truncated", False)),
    )


def _market_from_export(item: dict) -> Optional[ActiveMarket]:
    """Rebuild ActiveMarket from our export format (flat dict)."""
    condition_id = item.get("condition_id", "")
    if not condition_id:
        return None
    return ActiveMarket(
        market_id=str(item.get("market_id", "")),
        question=str(item.get("question", "")),
        condition_id=condition_id,
        slug=str(item.get("slug", "")),
        active=bool(item.get("active", False)),
        closed=bool(item.get("closed", False)),
        archived=bool(item.get("archived", False)),
        clob_token_ids=tuple(item.get("clob_token_ids", [])),
        outcomes=tuple(item.get("outcomes", [])),
        outcome_prices=tuple(item.get("outcome_prices", [])),
        volume=_parse_float(item.get("volume")),
        volume_24hr=_parse_float(item.get("volume_24hr")),
        liquidity=_parse_float(item.get("liquidity")),
        end_date=str(item.get("end_date", "")),
        event_id=item.get("event_id"),
        event_slug=item.get("event_slug"),
        event_title=item.get("event_title"),
    )


def save_markets_cache(path: Path, result: ActiveMarketsResult) -> None:
    """Write fetch result to a JSON cache file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": result.fetched_at,
        "pages_fetched": result.pages_fetched,
        "duration_seconds": result.duration_seconds,
        "truncated": result.truncated,
        "total": result.total,
        "markets": markets_to_dicts(result.markets),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
