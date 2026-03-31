"""
Volatility regime detection using ATR (Average True Range).

Classifies the current market into one of four regimes:
- LOW_VOL: Quiet/grinding (e.g., Asian session). Safe to enter early (T-60s).
- MEDIUM_VOL: Normal conditions. Standard snipe timing (T-15s).
- TRENDING_VOL: High volatility but directional. Tradeable at T-10s.
- HIGH_VOL: Choppy, non-directional. Skip the window entirely.

The regime determines:
1. Whether to trade at all (HIGH_VOL = skip)
2. Entry timing within the 5-min window
3. Signal confidence weighting
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from data.binance_ws import BinanceWebsocket

logger = logging.getLogger(__name__)


class Regime(str, Enum):
    LOW_VOL = "LOW_VOL"
    MEDIUM_VOL = "MEDIUM_VOL"
    HIGH_VOL = "HIGH_VOL"
    TRENDING_VOL = "TRENDING_VOL"


# Entry timing per regime (seconds before window close)
ENTRY_TIMING = {
    Regime.LOW_VOL: 60,
    Regime.MEDIUM_VOL: 15,
    Regime.TRENDING_VOL: 10,
    Regime.HIGH_VOL: 0,  # Don't enter
}

# Regime classification thresholds (ATR ratio = current / baseline)
LOW_VOL_THRESHOLD = 0.5
HIGH_VOL_THRESHOLD = 1.5

# Trending detection: requires directional consistency
TRENDING_MIN_DIRECTIONAL_RATIO = 0.7  # 70%+ of candles move in same direction

# ATR calculation periods
ATR_PERIOD = 30           # 30 one-minute candles for current ATR
ATR_BASELINE_PERIOD = 1440  # 24 hours of 1-min candles for baseline


@dataclass
class RegimeState:
    """Current regime classification with supporting data."""
    regime: Regime
    atr_current: float
    atr_baseline: float
    atr_ratio: float
    is_trending: bool
    trend_direction: Optional[str]  # 'UP' or 'DOWN' if trending
    entry_seconds_before_close: int


def calculate_atr(candles: list) -> float:
    """
    Calculate Average True Range from a list of candles.
    Candles can be either Candle (from websocket) or HistoricalCandle objects.

    ATR = average of True Range over the period, where:
    True Range = max(high - low, |high - prev_close|, |low - prev_close|)
    """
    if len(candles) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev = candles[i - 1]

        high = curr.high
        low = curr.low
        prev_close = prev.close

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    if not true_ranges:
        return 0.0

    return sum(true_ranges) / len(true_ranges)


def is_trending(candles: list, min_ratio: float = TRENDING_MIN_DIRECTIONAL_RATIO) -> tuple[bool, Optional[str]]:
    """
    Determine if recent candles show a directional trend.

    A trend is detected when >= min_ratio of candles close in the same
    direction (bullish or bearish). Returns (is_trending, direction).
    """
    if len(candles) < 5:
        return False, None

    up_count = sum(1 for c in candles if c.close > c.open)
    down_count = len(candles) - up_count
    total = len(candles)

    if up_count / total >= min_ratio:
        return True, "UP"
    elif down_count / total >= min_ratio:
        return True, "DOWN"

    return False, None


def classify_regime(
    current_candles: list,
    baseline_candles: list,
) -> RegimeState:
    """
    Classify the current volatility regime.

    Args:
        current_candles: Last 30 one-minute candles (from websocket or historical).
        baseline_candles: Last 24h of one-minute candles for baseline ATR.

    Returns:
        RegimeState with classification and supporting data.
    """
    atr_current = calculate_atr(current_candles[-ATR_PERIOD:])
    atr_baseline = calculate_atr(baseline_candles[-ATR_BASELINE_PERIOD:])

    # Avoid division by zero
    if atr_baseline == 0:
        logger.warning("ATR baseline is 0, defaulting to MEDIUM_VOL")
        return RegimeState(
            regime=Regime.MEDIUM_VOL,
            atr_current=atr_current,
            atr_baseline=0,
            atr_ratio=1.0,
            is_trending=False,
            trend_direction=None,
            entry_seconds_before_close=ENTRY_TIMING[Regime.MEDIUM_VOL],
        )

    ratio = atr_current / atr_baseline

    # Check for trending behavior in the current window
    trending, trend_dir = is_trending(current_candles[-ATR_PERIOD:])

    if ratio < LOW_VOL_THRESHOLD:
        regime = Regime.LOW_VOL
    elif ratio < HIGH_VOL_THRESHOLD:
        regime = Regime.MEDIUM_VOL
    elif trending:
        regime = Regime.TRENDING_VOL
    else:
        regime = Regime.HIGH_VOL

    state = RegimeState(
        regime=regime,
        atr_current=atr_current,
        atr_baseline=atr_baseline,
        atr_ratio=ratio,
        is_trending=trending,
        trend_direction=trend_dir,
        entry_seconds_before_close=ENTRY_TIMING[regime],
    )

    logger.info(
        "Regime: %s | ATR: %.6f / %.6f (ratio: %.2f) | Trending: %s %s",
        state.regime.value,
        atr_current,
        atr_baseline,
        ratio,
        trending,
        trend_dir or "",
    )

    return state


def classify_from_binance_ws(
    binance_ws: BinanceWebsocket,
    asset: str,
    baseline_candles: list,
) -> RegimeState:
    """
    Convenience function to classify regime using live websocket data
    for current candles and pre-fetched historical data for baseline.

    Args:
        binance_ws: Active BinanceWebsocket instance.
        asset: Asset key (e.g., 'btc').
        baseline_candles: 24h of historical candles for baseline ATR.

    Returns:
        RegimeState with current classification.
    """
    current_candles = binance_ws.get_candles(asset, count=ATR_PERIOD)

    if len(current_candles) < 10:
        logger.warning(
            "Only %d live candles for %s, need at least 10. Defaulting to MEDIUM_VOL",
            len(current_candles), asset,
        )
        return RegimeState(
            regime=Regime.MEDIUM_VOL,
            atr_current=0,
            atr_baseline=0,
            atr_ratio=1.0,
            is_trending=False,
            trend_direction=None,
            entry_seconds_before_close=ENTRY_TIMING[Regime.MEDIUM_VOL],
        )

    return classify_regime(current_candles, baseline_candles)


def should_skip_window(regime_state: RegimeState) -> bool:
    """Returns True if the current regime means we should skip this window."""
    return regime_state.regime == Regime.HIGH_VOL


def get_entry_timing(regime_state: RegimeState) -> int:
    """Returns how many seconds before window close to enter."""
    return regime_state.entry_seconds_before_close
