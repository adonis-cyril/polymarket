"""
Fetch historical 1-min candles from Binance REST API.

Used to bootstrap the volatility model (ATR baseline) and backtest
the signal stack. Fetches up to 30 days of 1-minute candles per asset
using paginated requests (Binance limit: 1000 candles per request).

All data sources are free — no API key required for public klines.
"""

import logging
import time
from dataclasses import dataclass

import requests

from config import ASSETS, BINANCE_SYMBOLS

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
MAX_CANDLES_PER_REQUEST = 1000
ONE_MINUTE_MS = 60 * 1000
REQUEST_DELAY = 0.2  # seconds between paginated requests to avoid rate limits


@dataclass
class HistoricalCandle:
    """A single historical 1-minute candle."""
    open_time: int       # Unix ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int      # Unix ms


def fetch_candles(
    asset: str,
    days: int = 30,
    interval: str = "1m",
) -> list[HistoricalCandle]:
    """
    Fetch historical candles for a single asset from Binance.

    Args:
        asset: Asset key (e.g., 'btc', 'eth', 'sol', 'xrp')
        days: Number of days of history to fetch (default 30)
        interval: Candle interval (default '1m')

    Returns:
        List of HistoricalCandle, oldest first.
    """
    symbol = BINANCE_SYMBOLS.get(asset)
    if not symbol:
        raise ValueError(f"Unknown asset: {asset}")

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)

    all_candles: list[HistoricalCandle] = []
    current_start = start_ms

    total_expected = days * 24 * 60  # 1-min candles per day
    logger.info(
        "Fetching %d days of %s candles for %s (~%d candles)",
        days, interval, symbol, total_expected,
    )

    while current_start < now_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "limit": MAX_CANDLES_PER_REQUEST,
        }

        try:
            resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
            resp.raise_for_status()
            raw_candles = resp.json()
        except requests.RequestException as e:
            logger.error("Failed to fetch candles for %s at %d: %s", symbol, current_start, e)
            # Retry once after a brief pause
            time.sleep(1.0)
            try:
                resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
                resp.raise_for_status()
                raw_candles = resp.json()
            except requests.RequestException:
                logger.error("Retry also failed for %s, skipping batch", symbol)
                current_start += MAX_CANDLES_PER_REQUEST * ONE_MINUTE_MS
                continue

        if not raw_candles:
            break

        for k in raw_candles:
            all_candles.append(HistoricalCandle(
                open_time=k[0],
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                close_time=k[6],
            ))

        # Move start to after the last candle's close time
        current_start = raw_candles[-1][6] + 1

        if len(raw_candles) < MAX_CANDLES_PER_REQUEST:
            break  # No more data available

        time.sleep(REQUEST_DELAY)

    logger.info("Fetched %d candles for %s", len(all_candles), symbol)
    return all_candles


def fetch_all_assets(days: int = 30) -> dict[str, list[HistoricalCandle]]:
    """
    Fetch historical candles for all tracked assets.

    Returns:
        Dict mapping asset key to list of HistoricalCandle.
    """
    result = {}
    for asset in ASSETS:
        result[asset] = fetch_candles(asset, days=days)
    return result


def candles_to_closes(candles: list[HistoricalCandle]) -> list[float]:
    """Extract close prices from a list of candles."""
    return [c.close for c in candles]


def candles_to_ohlc(candles: list[HistoricalCandle]) -> list[dict]:
    """Convert candles to list of OHLC dicts (useful for ATR calculation)."""
    return [
        {
            "open_time": c.open_time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]
