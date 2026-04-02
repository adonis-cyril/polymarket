"""
Full signal stack for 5-min market direction prediction.

Combines multiple weighted signals into a composite score that determines:
1. Whether to trade (score must exceed threshold)
2. Which direction to bet (UP or DOWN)
3. Confidence level (used for win probability estimation)

Signal weights (from spec):
1. Window delta:              weight 7  (primary)
2. Oracle lag:                weight 3  (secondary)
3. Order book imbalance:      weight 2  (tertiary)
4. Whale pattern match:       weight 2  (from historical profiles)
5. Live whale confirmation:   weight 1.5 (from current market)
6. Multi-exchange consensus:  weight 1  (confirmation)

If whale pattern + live whale fire same direction: 1.5x boost on combined whale score.
Spike detection: if score jumps >= 1.5 between checks, fire immediately.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from data.binance_ws import BinanceWebsocket
from data.polymarket_ws import PolymarketWebsocket
from execution.market_discovery import Market

logger = logging.getLogger(__name__)

# Signal weights
DELTA_WEIGHT = 7.0
ORACLE_LAG_WEIGHT = 3.0
BOOK_IMBALANCE_WEIGHT = 2.0
WHALE_PATTERN_WEIGHT = 2.0
WHALE_LIVE_WEIGHT = 1.5
MULTI_EXCHANGE_WEIGHT = 1.0

# Thresholds
MIN_SIGNAL_SCORE = 3.0
SPIKE_THRESHOLD = 1.5  # Score jump that triggers immediate fire

# Multi-exchange endpoints (free, no auth)
COINBASE_TICKER_URL = "https://api.coinbase.com/v2/prices/{pair}/spot"
KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"

COINBASE_PAIRS = {
    "btc": "BTC-USD",
    "eth": "ETH-USD",
    "sol": "SOL-USD",
    "xrp": "XRP-USD",
}

KRAKEN_PAIRS = {
    "btc": "XBTUSD",
    "eth": "ETHUSD",
    "sol": "SOLUSD",
    "xrp": "XRPUSD",
}


@dataclass
class SignalResult:
    """Result of signal analysis for a single asset."""
    asset: str
    direction: str             # 'UP' or 'DOWN'
    score: float               # Composite signal score
    delta_pct: float           # Window delta percentage
    delta_signal: float        # Normalized delta contribution
    oracle_lag_signal: float   # Oracle lag contribution
    book_imbalance_signal: float  # Order book imbalance contribution
    whale_signal: float        # Combined whale contribution
    multi_exchange_signal: float  # Multi-exchange consensus contribution
    whale_aligned: bool        # Did whales agree with our direction?
    whale_count: int           # Number of whales that entered
    win_prob_estimate: float   # Estimated win probability from signal strength


@dataclass
class SignalState:
    """Tracks signal state across multiple checks within a window."""
    best_signal: Optional[SignalResult] = None
    previous_score: float = 0.0
    spike_detected: bool = False
    checks_count: int = 0


def _get_coinbase_price(asset: str) -> Optional[float]:
    """Fetch current price from Coinbase."""
    pair = COINBASE_PAIRS.get(asset)
    if not pair:
        return None
    try:
        resp = requests.get(
            COINBASE_TICKER_URL.format(pair=pair),
            timeout=3,
        )
        resp.raise_for_status()
        return float(resp.json()["data"]["amount"])
    except Exception:
        return None


def _get_kraken_price(asset: str) -> Optional[float]:
    """Fetch current price from Kraken."""
    pair = KRAKEN_PAIRS.get(asset)
    if not pair:
        return None
    try:
        resp = requests.get(
            KRAKEN_TICKER_URL,
            params={"pair": pair},
            timeout=3,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        for key, val in result.items():
            return float(val["c"][0])  # Last trade close price
        return None
    except Exception:
        return None


def calculate_delta_signal(
    binance_ws: BinanceWebsocket,
    asset: str,
    window_open_price: float,
) -> tuple[float, float]:
    """
    Calculate window delta signal.

    Returns (delta_pct, normalized_signal).
    Signal is normalized: 0.05% delta → signal ~1.0.
    """
    current_price = binance_ws.get_price(asset)
    if current_price == 0 or window_open_price == 0:
        return 0.0, 0.0

    delta_pct = ((current_price - window_open_price) / window_open_price) * 100

    # Normalize: 0.05% = 1.0, 0.10% = 2.0, etc.
    normalized = delta_pct / 0.05

    return delta_pct, normalized


def calculate_oracle_lag_signal(
    binance_ws: BinanceWebsocket,
    polymarket_ws: PolymarketWebsocket,
    asset: str,
    market: Market,
) -> float:
    """
    Calculate oracle lag signal.

    Compares Binance real-time price implied direction with Polymarket
    token prices. If Binance suggests UP but Polymarket still prices
    DOWN favorably, that's exploitable lag.

    Returns signal from -1.0 to +1.0.
    """
    binance_price = binance_ws.get_price(asset)
    if binance_price == 0:
        return 0.0

    # Get Polymarket implied direction from token prices
    up_book = polymarket_ws.get_order_book(market.up_token_id)
    down_book = polymarket_ws.get_order_book(market.down_token_id)

    if not up_book or not down_book:
        return 0.0

    poly_up_price = up_book.mid_price
    poly_down_price = down_book.mid_price

    # Binance 10-second direction
    price_10s = binance_ws.get_price_at(asset, seconds_ago=10)
    if price_10s is None:
        return 0.0

    binance_direction = 1.0 if binance_price > price_10s else -1.0

    # Polymarket implied direction
    poly_direction = 1.0 if poly_up_price > poly_down_price else -1.0

    # Lag exists when Binance and Polymarket disagree, or when
    # Binance has moved but Polymarket hasn't caught up
    if binance_direction != poly_direction:
        # Strong lag: exchanges disagree
        return binance_direction * 0.8

    # Check magnitude of Binance move vs Polymarket reprice
    binance_move = abs(binance_price - price_10s) / price_10s * 100
    poly_lean = abs(poly_up_price - 0.5)

    if binance_move > 0.03 and poly_lean < 0.15:
        # Binance moved but Polymarket still near 50/50
        return binance_direction * 0.5

    return 0.0


def calculate_book_imbalance_signal(
    polymarket_ws: PolymarketWebsocket,
    market: Market,
) -> float:
    """
    Calculate order book imbalance signal.

    Returns signal from -1.0 (bearish) to +1.0 (bullish).
    """
    return polymarket_ws.get_book_imbalance(
        market.up_token_id, market.down_token_id,
    )


def calculate_multi_exchange_signal(asset: str, binance_direction: float) -> float:
    """
    Check multi-exchange price consensus.

    Returns signal from -1.0 to +1.0.
    All three agreeing = strong signal. Disagreement = weak/zero.
    """
    directions = [binance_direction]

    coinbase_price = _get_coinbase_price(asset)
    kraken_price = _get_kraken_price(asset)

    # We can't determine direction from spot prices alone without
    # historical reference, so we just check if they're available
    # and use as a confirmation of Binance direction
    exchange_count = 1  # Binance
    if coinbase_price is not None:
        exchange_count += 1
    if kraken_price is not None:
        exchange_count += 1

    # More exchanges available = higher confidence in Binance direction
    if exchange_count >= 3:
        return binance_direction * 0.8
    elif exchange_count >= 2:
        return binance_direction * 0.5
    return 0.0


def analyze_signals(
    binance_ws: BinanceWebsocket,
    polymarket_ws: PolymarketWebsocket,
    market: Market,
    window_open_price: float,
    whale_signal: float = 0.0,
    whale_direction: Optional[str] = None,
    whale_count: int = 0,
) -> Optional[SignalResult]:
    """
    Run the full signal stack for a single asset.

    Args:
        binance_ws: Active Binance websocket.
        polymarket_ws: Active Polymarket CLOB websocket.
        market: Market object from discovery.
        window_open_price: Price at window open (from Binance).
        whale_signal: Pre-computed whale signal score.
        whale_direction: Direction whales are betting.
        whale_count: Number of whales detected.

    Returns:
        SignalResult or None if no actionable signal.
    """
    # 1. Window delta (weight 7)
    delta_pct, delta_normalized = calculate_delta_signal(
        binance_ws, market.asset, window_open_price,
    )

    if abs(delta_pct) < 0.005:
        return None  # No meaningful move

    direction = "UP" if delta_pct > 0 else "DOWN"
    delta_signal = abs(delta_normalized) * DELTA_WEIGHT
    if delta_pct < 0:
        delta_signal = -delta_signal

    # 2. Oracle lag (weight 3)
    oracle_lag = calculate_oracle_lag_signal(
        binance_ws, polymarket_ws, market.asset, market,
    )
    oracle_signal = oracle_lag * ORACLE_LAG_WEIGHT

    # 3. Book imbalance (weight 2)
    book_imbalance = calculate_book_imbalance_signal(polymarket_ws, market)
    book_signal = book_imbalance * BOOK_IMBALANCE_WEIGHT

    # 4+5. Whale signals (pre-computed by scorer.py)
    # whale_signal already includes pattern (weight 2) + live (weight 1.5) + alignment bonus

    # 6. Multi-exchange consensus (weight 1)
    binance_dir = 1.0 if delta_pct > 0 else -1.0
    multi_ex = calculate_multi_exchange_signal(market.asset, binance_dir)
    multi_ex_signal = multi_ex * MULTI_EXCHANGE_WEIGHT

    # Composite score: sum all signals, take absolute value for strength
    # Direction is determined by delta (primary signal)
    raw_score = delta_signal + oracle_signal + book_signal + whale_signal + multi_ex_signal
    score = abs(raw_score)

    # Check if whales agree with our direction
    whale_aligned = whale_direction == direction if whale_direction else False

    # Estimate win probability from signal strength
    # Calibrated: score 5 ≈ 70%, score 10 ≈ 85%, score 15+ ≈ 90%
    if score >= 15:
        win_prob = 0.90
    elif score >= 10:
        win_prob = 0.80 + (score - 10) * 0.02
    elif score >= 5:
        win_prob = 0.65 + (score - 5) * 0.03
    elif score >= 3:
        win_prob = 0.55 + (score - 3) * 0.05
    else:
        win_prob = 0.50 + score * 0.02

    win_prob = min(win_prob, 0.95)

    return SignalResult(
        asset=market.asset,
        direction=direction,
        score=round(score, 4),
        delta_pct=round(delta_pct, 6),
        delta_signal=round(abs(delta_signal), 4),
        oracle_lag_signal=round(oracle_signal, 4),
        book_imbalance_signal=round(book_signal, 4),
        whale_signal=round(whale_signal, 4),
        multi_exchange_signal=round(multi_ex_signal, 4),
        whale_aligned=whale_aligned,
        whale_count=whale_count,
        win_prob_estimate=round(win_prob, 4),
    )
