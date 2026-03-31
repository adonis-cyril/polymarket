"""
Late-window reversal detection for contrarian high-payout trades.

Monitors for situations where:
1. A 5-min market is leaning 60-85% in one direction
2. The underlying asset suddenly moves AGAINST that direction on Binance
3. Polymarket hasn't repriced yet (oracle lag)
4. The contrarian token is cheap ($0.10-$0.40)

These are rare (5-15 per day across all assets) but have 2-4x payout ratios.
The bot buys the contrarian side, betting on the reversal completing before
the window closes.

IMPORTANT: This detects reversals ALREADY HAPPENING on exchange feeds,
not predicting future reversals.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from data.binance_ws import BinanceWebsocket

logger = logging.getLogger(__name__)

# Trigger thresholds
MIN_SECONDS_LEFT = 15           # Don't enter with < 15s (fills may fail)
MAX_SECONDS_LEFT = 90           # Only look in last 90 seconds
MIN_MARKET_LEAN = 0.60          # Market must be 60%+ in one direction
MAX_MARKET_LEAN = 0.85          # Above 85%, reversal too unlikely
MIN_COUNTER_MOVE_PCT = 0.05     # Binance must show >= 0.05% counter-move
MAX_CONTRARIAN_PRICE = 0.40     # Only buy contrarian if <= $0.40
MIN_CONTRARIAN_PRICE = 0.10     # Below $0.10 means market is too certain


@dataclass
class ReversalSignal:
    """A detected reversal setup."""
    asset: str
    direction: str               # 'UP' or 'DOWN' — the contrarian side to bet on
    contrarian_price: float      # Current price of the contrarian token
    win_prob: float              # Estimated win probability (25-40%)
    payout_ratio: float          # (1 - price) / price
    counter_move_pct: float      # Size of the counter-move on Binance
    seconds_left: float          # Time remaining in window
    oracle_lag_detected: bool    # Whether we detected pricing lag


class ReversalDetector:
    """
    Monitors for late-window reversal setups across all assets.
    """

    def __init__(self, binance_ws: BinanceWebsocket):
        self.binance_ws = binance_ws

    def detect(
        self,
        asset: str,
        seconds_left: float,
        up_price: float,
        down_price: float,
        up_price_20s_ago: Optional[float] = None,
        down_price_20s_ago: Optional[float] = None,
    ) -> Optional[ReversalSignal]:
        """
        Check if a reversal setup exists for this asset.

        Args:
            asset: Asset key ('btc', etc.)
            seconds_left: Seconds remaining in window.
            up_price: Current UP token price on Polymarket.
            down_price: Current DOWN token price on Polymarket.
            up_price_20s_ago: UP token price 20 seconds ago (for lag detection).
            down_price_20s_ago: DOWN token price 20 seconds ago (for lag detection).

        Returns:
            ReversalSignal if setup detected, None otherwise.
        """
        # Time window check
        if not (MIN_SECONDS_LEFT <= seconds_left <= MAX_SECONDS_LEFT):
            return None

        # Determine market direction and lean
        market_direction = "UP" if up_price > down_price else "DOWN"
        market_lean = max(up_price, down_price)

        if not (MIN_MARKET_LEAN <= market_lean <= MAX_MARKET_LEAN):
            return None

        # Check Binance for counter-move in last 20 seconds
        move_pct = self.binance_ws.get_price_change_pct(asset, seconds_ago=20)
        if move_pct is None:
            return None

        # Counter-move: exchange price moves AGAINST the market direction
        is_counter_move = (
            (market_direction == "UP" and move_pct < -MIN_COUNTER_MOVE_PCT) or
            (market_direction == "DOWN" and move_pct > MIN_COUNTER_MOVE_PCT)
        )

        if not is_counter_move:
            return None

        # Check contrarian token price
        contrarian_side = "DOWN" if market_direction == "UP" else "UP"
        contrarian_price = down_price if market_direction == "UP" else up_price

        if not (MIN_CONTRARIAN_PRICE <= contrarian_price <= MAX_CONTRARIAN_PRICE):
            return None

        # Check for oracle lag: has Polymarket repriced?
        oracle_lag = False
        if up_price_20s_ago is not None and down_price_20s_ago is not None:
            contrarian_price_20s_ago = (
                down_price_20s_ago if market_direction == "UP" else up_price_20s_ago
            )
            expected_reprice = abs(move_pct) * 2.0
            actual_reprice = abs(contrarian_price - contrarian_price_20s_ago)
            oracle_lag = actual_reprice < expected_reprice * 0.5
        else:
            # Can't confirm lag without historical price, but counter-move is strong enough
            oracle_lag = abs(move_pct) > MIN_COUNTER_MOVE_PCT * 2

        if not oracle_lag:
            return None

        # Estimate win probability (calibrated conservatively)
        win_prob = 0.25 + min(abs(move_pct) * 0.5, 0.15)  # 25-40% range
        payout_ratio = (1.0 - contrarian_price) / contrarian_price

        signal = ReversalSignal(
            asset=asset,
            direction=contrarian_side,
            contrarian_price=contrarian_price,
            win_prob=win_prob,
            payout_ratio=payout_ratio,
            counter_move_pct=abs(move_pct),
            seconds_left=seconds_left,
            oracle_lag_detected=oracle_lag,
        )

        logger.info(
            "REVERSAL DETECTED: %s %s | contrarian=$%.2f | move=%.3f%% | "
            "win_prob=%.1f%% | payout=%.1fx | %ds left",
            asset.upper(), contrarian_side, contrarian_price,
            abs(move_pct), win_prob * 100, payout_ratio, int(seconds_left),
        )

        return signal
