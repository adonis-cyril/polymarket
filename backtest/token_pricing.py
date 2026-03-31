"""
Delta-based realistic token pricing model for backtesting.

Simulates how Polymarket 5-min UP/DOWN token prices behave based on the
underlying asset's price movement (delta) within a window. This is critical
for realistic backtesting — without it, backtests assume you can always buy
at some fixed price, which massively overstates edge.

In reality, token prices are a function of:
1. The current delta (price change since window open)
2. Time remaining in the window
3. Market maker behavior / order book dynamics

This model uses a sigmoid-based pricing curve calibrated to observed
Polymarket behavior:
- At window open (delta=0): both tokens ≈ $0.50
- As delta grows positive: UP token rises toward $1.00, DOWN falls toward $0.00
- As time runs out: prices become more extreme (less time for reversal)
- Spread/slippage is modeled to avoid assuming perfect fills
"""

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class TokenPrices:
    """Simulated token prices for a given market state."""
    up_price: float      # Price of the UP token ($0.00 - $1.00)
    down_price: float    # Price of the DOWN token ($0.00 - $1.00)
    spread: float        # Simulated bid-ask spread
    up_ask: float        # Price you'd actually pay for UP (up_price + spread/2)
    down_ask: float      # Price you'd actually pay for DOWN (down_price + spread/2)


# Sigmoid steepness calibration by asset
# Higher = more sensitive to delta (smaller absolute moves matter more)
# Calibrated so that a "typical" decisive move maps to ~75-85% token price
ASSET_SENSITIVITY = {
    "btc": 12.0,    # BTC: 0.08% move → ~75% token price
    "eth": 10.0,    # ETH: slightly more volatile, needs bigger move
    "sol": 6.0,     # SOL: much more volatile, lower sensitivity
    "xrp": 5.0,     # XRP: most volatile of the four
}

# Time decay factor: how much time remaining amplifies price extremes
# At T-300s (window open): factor = 1.0 (no amplification)
# At T-0s (window close): factor = TIME_DECAY_MAX (prices very extreme)
TIME_DECAY_MAX = 2.5

# Spread model: wider spread when prices are near 0.50 (uncertain),
# tighter when prices are extreme (market is confident)
BASE_SPREAD = 0.03       # 3 cents base spread
MIN_SPREAD = 0.01        # 1 cent minimum spread at extremes


def sigmoid(x: float) -> float:
    """Standard sigmoid function, clamped to avoid overflow."""
    x = max(-20.0, min(20.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def estimate_token_prices(
    asset: str,
    delta_pct: float,
    seconds_left: float,
    window_duration: float = 300.0,
) -> TokenPrices:
    """
    Estimate UP/DOWN token prices based on current market state.

    Args:
        asset: Asset key ('btc', 'eth', 'sol', 'xrp')
        delta_pct: Price change since window open, in percent.
                   Positive = price went up, negative = price went down.
        seconds_left: Seconds remaining in the 5-min window (0-300).
        window_duration: Total window length in seconds (default 300).

    Returns:
        TokenPrices with simulated UP/DOWN prices and asks.
    """
    sensitivity = ASSET_SENSITIVITY.get(asset, 10.0)

    # Time decay: as window progresses, prices become more decisive
    elapsed_ratio = 1.0 - (seconds_left / window_duration)
    time_factor = 1.0 + (TIME_DECAY_MAX - 1.0) * elapsed_ratio

    # Sigmoid input: delta * sensitivity * time_factor
    sig_input = delta_pct * sensitivity * time_factor

    # UP token price = sigmoid of the input
    up_price = sigmoid(sig_input)
    down_price = 1.0 - up_price

    # Spread: wider near 0.50, tighter at extremes
    uncertainty = 1.0 - abs(up_price - 0.5) * 2.0  # 1.0 at 0.50, 0.0 at 0/1
    spread = MIN_SPREAD + (BASE_SPREAD - MIN_SPREAD) * uncertainty

    # Ask prices (what you'd actually pay)
    up_ask = min(up_price + spread / 2, 0.99)
    down_ask = min(down_price + spread / 2, 0.99)

    return TokenPrices(
        up_price=round(up_price, 4),
        down_price=round(down_price, 4),
        spread=round(spread, 4),
        up_ask=round(up_ask, 4),
        down_ask=round(down_ask, 4),
    )


def estimate_win_probability(
    delta_pct: float,
    seconds_left: float,
    asset: str,
) -> float:
    """
    Estimate the probability that the current direction holds until window close.

    This is used by the backtest to simulate what a signal-based win probability
    estimate would look like. In live trading, the signal stack produces this;
    in backtesting, we derive it from delta + time.

    Args:
        delta_pct: Current price delta in percent (positive = UP favored).
        seconds_left: Seconds remaining in window.
        asset: Asset key.

    Returns:
        Probability (0.0 - 1.0) that the favored direction wins.
    """
    if abs(delta_pct) < 0.001:
        return 0.50

    # Base probability from delta magnitude
    sensitivity = ASSET_SENSITIVITY.get(asset, 10.0)
    base_prob = sigmoid(abs(delta_pct) * sensitivity * 0.8)

    # Time bonus: more time elapsed = more likely current direction holds
    # But diminishing — last 30 seconds are where reversals happen
    elapsed_ratio = 1.0 - (seconds_left / 300.0)

    if elapsed_ratio > 0.9:
        # Last 30 seconds: slight reduction (reversal risk)
        time_bonus = 0.08
    elif elapsed_ratio > 0.5:
        time_bonus = 0.05 + 0.05 * elapsed_ratio
    else:
        time_bonus = 0.02

    prob = min(base_prob + time_bonus, 0.98)
    return round(prob, 4)


def simulate_window_outcome(
    open_price: float,
    close_price: float,
) -> str:
    """
    Determine the outcome of a 5-min window.

    Args:
        open_price: Asset price at window open.
        close_price: Asset price at window close.

    Returns:
        'UP' if close > open, 'DOWN' if close <= open.
    """
    return "UP" if close_price > open_price else "DOWN"


def calculate_pnl(
    direction: str,
    token_ask: float,
    bet_size: float,
    outcome: str,
) -> float:
    """
    Calculate P&L for a single trade.

    Args:
        direction: 'UP' or 'DOWN' (what we bet on).
        token_ask: Price we paid for the token.
        bet_size: USDC amount wagered.
        outcome: 'UP' or 'DOWN' (actual result).

    Returns:
        P&L in USDC. Positive = profit, negative = loss.
    """
    shares = bet_size / token_ask

    if direction == outcome:
        # Win: each share pays $1.00
        payout = shares * 1.0
        return payout - bet_size
    else:
        # Loss: shares worth $0.00
        return -bet_size


def get_payout_ratio(token_price: float) -> float:
    """
    Calculate the payout ratio for a token at a given price.
    Payout ratio = profit / risk = (1.0 - price) / price

    E.g., buy at $0.75 → payout ratio = 0.333 (win $0.25 per $0.75 risked)
    E.g., buy at $0.25 → payout ratio = 3.0 (win $0.75 per $0.25 risked)
    """
    if token_price <= 0 or token_price >= 1.0:
        return 0.0
    return (1.0 - token_price) / token_price
