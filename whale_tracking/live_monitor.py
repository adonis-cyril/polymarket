"""
Live whale activity monitor for the current 5-min market window.

During the bot's snipe window (last 60 seconds), checks if any tracked
profitable wallet has placed a trade on the current market. Runs in the
hot path but is a lightweight API call (< 200ms).

Does NOT copy trade. Only uses whale presence as a signal booster.
Absence of whale activity is neutral (score = 0), not negative.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"
REQUEST_TIMEOUT = 5


@dataclass
class WhaleLiveSignal:
    """Live whale activity signal for the current market."""
    direction: Optional[str]  # 'UP' or 'DOWN', or None if no whales
    num_whales: int
    consensus: float          # 0-1, how many agree on direction
    signal_score: float       # 0-2.0, capped score for signal stack
    whale_addresses: list[str]  # Which whales entered


def check_whale_activity(
    condition_id: str,
    tracked_wallets: set[str],
    up_token_id: str = "",
    down_token_id: str = "",
) -> WhaleLiveSignal:
    """
    Check if any tracked wallets have entered the current market.

    Args:
        condition_id: The market's condition ID.
        tracked_wallets: Set of tracked wallet addresses (lowercase).
        up_token_id: Token ID for the UP outcome.
        down_token_id: Token ID for the DOWN outcome.

    Returns:
        WhaleLiveSignal with whale activity data.
    """
    if not tracked_wallets:
        return WhaleLiveSignal(
            direction=None, num_whales=0, consensus=0,
            signal_score=0, whale_addresses=[],
        )

    try:
        resp = requests.get(
            f"{DATA_API_BASE}/trades",
            params={"market": condition_id, "limit": 50},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        recent_trades = resp.json()
    except requests.RequestException as e:
        logger.debug("Failed to fetch trades for whale check: %s", e)
        return WhaleLiveSignal(
            direction=None, num_whales=0, consensus=0,
            signal_score=0, whale_addresses=[],
        )

    if not isinstance(recent_trades, list):
        return WhaleLiveSignal(
            direction=None, num_whales=0, consensus=0,
            signal_score=0, whale_addresses=[],
        )

    # Filter for trades from tracked wallets
    whale_trades = []
    seen_wallets = set()

    for trade in recent_trades:
        maker = (trade.get("maker", "") or "").lower()
        taker = (trade.get("taker", "") or "").lower()
        trader = maker if maker in tracked_wallets else (taker if taker in tracked_wallets else None)

        if trader and trader not in seen_wallets:
            seen_wallets.add(trader)

            # Determine direction from token ID
            asset_id = trade.get("asset_id", "")
            side = trade.get("side", "BUY")

            if asset_id == up_token_id:
                direction = "UP" if side == "BUY" else "DOWN"
            elif asset_id == down_token_id:
                direction = "DOWN" if side == "BUY" else "UP"
            else:
                direction = "UP" if side == "BUY" else "DOWN"

            whale_trades.append({
                "address": trader,
                "direction": direction,
                "price": float(trade.get("price", 0)),
                "size": float(trade.get("size", 0)),
            })

    if not whale_trades:
        return WhaleLiveSignal(
            direction=None, num_whales=0, consensus=0,
            signal_score=0, whale_addresses=[],
        )

    # Determine consensus direction
    up_count = sum(1 for t in whale_trades if t["direction"] == "UP")
    down_count = len(whale_trades) - up_count

    direction = "UP" if up_count > down_count else "DOWN"
    consensus = max(up_count, down_count) / len(whale_trades)

    # Score: more whales + higher consensus = stronger signal
    signal_score = len(whale_trades) * consensus * 0.5
    signal_score = min(signal_score, 2.0)  # Cap at 2.0

    addresses = [t["address"] for t in whale_trades]

    logger.info(
        "Whale activity: %d whales, direction=%s, consensus=%.0f%%, score=%.2f",
        len(whale_trades), direction, consensus * 100, signal_score,
    )

    return WhaleLiveSignal(
        direction=direction,
        num_whales=len(whale_trades),
        consensus=consensus,
        signal_score=signal_score,
        whale_addresses=addresses,
    )
