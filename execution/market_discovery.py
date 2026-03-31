"""
Gamma API market discovery for Polymarket 5-min UP/DOWN markets.

5-min markets use deterministic slugs based on Unix timestamps.
Every 5 minutes (timestamps divisible by 300), new markets spawn
for BTC, ETH, SOL, and XRP.

Gamma API: https://gamma-api.polymarket.com
- No auth required
- Returns market metadata including condition IDs and token IDs
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

ASSET_SLUGS = {
    "btc": "btc-updown-5m",
    "eth": "eth-updown-5m",
    "sol": "sol-updown-5m",
    "xrp": "xrp-updown-5m",
}

REQUEST_TIMEOUT = 10


@dataclass
class Market:
    """A single 5-min UP/DOWN market."""
    asset: str
    slug: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    window_ts: int
    close_time: int
    question: str = ""
    active: bool = True


def get_current_window_ts() -> int:
    """Get the current 5-min window start timestamp."""
    now = int(time.time())
    return now - (now % 300)


def get_next_window_ts() -> int:
    """Get the next 5-min window start timestamp."""
    return get_current_window_ts() + 300


def seconds_until_close() -> float:
    """Seconds remaining in the current 5-min window."""
    now = time.time()
    window_ts = int(now) - (int(now) % 300)
    close_time = window_ts + 300
    return max(0, close_time - now)


def fetch_market_by_slug(slug: str) -> Optional[dict]:
    """Fetch a single market event from Gamma API by slug."""
    try:
        resp = requests.get(
            f"{GAMMA_API_BASE}/events",
            params={"slug": slug},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]
        return None
    except requests.RequestException as e:
        logger.error("Failed to fetch market %s: %s", slug, e)
        return None


def discover_market(asset: str, window_ts: Optional[int] = None) -> Optional[Market]:
    """
    Discover the current 5-min market for a given asset.

    Args:
        asset: Asset key ('btc', 'eth', 'sol', 'xrp')
        window_ts: Window timestamp (default: current window)

    Returns:
        Market object or None if not found.
    """
    if window_ts is None:
        window_ts = get_current_window_ts()

    slug_prefix = ASSET_SLUGS.get(asset)
    if not slug_prefix:
        logger.error("Unknown asset: %s", asset)
        return None

    slug = f"{slug_prefix}-{window_ts}"
    event = fetch_market_by_slug(slug)

    if not event:
        logger.debug("No market found for slug: %s", slug)
        return None

    markets = event.get("markets", [])
    if not markets:
        logger.warning("Event %s has no markets", slug)
        return None

    market_data = markets[0]
    clob_token_ids = market_data.get("clobTokenIds", [])

    if len(clob_token_ids) < 2:
        logger.warning("Market %s missing token IDs", slug)
        return None

    return Market(
        asset=asset,
        slug=slug,
        condition_id=market_data.get("conditionId", ""),
        up_token_id=clob_token_ids[0],
        down_token_id=clob_token_ids[1],
        window_ts=window_ts,
        close_time=window_ts + 300,
        question=market_data.get("question", ""),
        active=market_data.get("active", True),
    )


def discover_all_markets(window_ts: Optional[int] = None) -> dict[str, Market]:
    """
    Discover current 5-min markets for all assets.

    Returns:
        Dict mapping asset key to Market object.
        Only includes assets where a market was found.
    """
    if window_ts is None:
        window_ts = get_current_window_ts()

    markets = {}
    for asset in ASSET_SLUGS:
        market = discover_market(asset, window_ts)
        if market:
            markets[asset] = market

    logger.info(
        "Discovered %d/%d markets for window %d",
        len(markets), len(ASSET_SLUGS), window_ts,
    )
    return markets


def get_market_prices(condition_id: str) -> Optional[dict]:
    """
    Fetch current prices for a market from Gamma API.

    Returns dict with 'up_price' and 'down_price' or None.
    """
    try:
        resp = requests.get(
            f"{GAMMA_API_BASE}/markets",
            params={"condition_id": condition_id},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list) and data:
            market = data[0]
            tokens = market.get("tokens", [])
            if len(tokens) >= 2:
                return {
                    "up_price": float(tokens[0].get("price", 0.5)),
                    "down_price": float(tokens[1].get("price", 0.5)),
                }
        return None
    except requests.RequestException as e:
        logger.error("Failed to fetch prices for %s: %s", condition_id, e)
        return None
