"""
Fractional Kelly criterion for position sizing.

Quarter-Kelly (25%) by default. Kelly determines what fraction of
the phase-allowed bet amount to actually risk.

Full Kelly formula: f = (p * b - q) / b
  p = estimated win probability
  b = payout ratio = (1 - token_price) / token_price
  q = 1 - p

Exception: "done deal" trades (token >= $0.90, <15s left, signal > 6,
whale confirmation) override Kelly and use 100% of phase-allowed amount.
"""

import logging

logger = logging.getLogger(__name__)

DEFAULT_KELLY_FRACTION = 0.25  # Quarter-Kelly


def calculate_kelly_bet(
    win_prob: float,
    token_price: float,
    phase_allowed_amount: float,
    kelly_fraction: float = DEFAULT_KELLY_FRACTION,
) -> float:
    """
    Calculate bet size using fractional Kelly.

    Args:
        win_prob: Estimated probability of winning (0-1).
        token_price: Token price we'd buy at (0-1).
        phase_allowed_amount: Max bet allowed by current capital preservation phase.
        kelly_fraction: Fraction of full Kelly to use (default 0.25).

    Returns:
        Bet size in USDC. Returns 0 if no edge.
    """
    if token_price <= 0 or token_price >= 1.0 or win_prob <= 0:
        return 0.0

    b = (1.0 - token_price) / token_price  # payout odds
    q = 1.0 - win_prob

    full_kelly = (win_prob * b - q) / b

    if full_kelly <= 0:
        return 0.0

    bet_fraction = kelly_fraction * full_kelly
    bet_size = bet_fraction * phase_allowed_amount

    # Clamp to phase-allowed amount
    bet_size = min(bet_size, phase_allowed_amount)

    return round(bet_size, 4)


def is_done_deal(
    token_price: float,
    seconds_left: float,
    signal_score: float,
    regime: str,
    whale_count: int,
) -> bool:
    """
    Check if this is a "done deal" — near-certain resolution win.

    All conditions must be true:
    - Token price >= $0.90
    - < 15 seconds remain
    - Signal score > 6
    - Regime is not HIGH_VOL
    - At least 1 whale entered same direction
    """
    return (
        token_price >= 0.90
        and seconds_left < 15
        and signal_score > 6
        and regime != "HIGH_VOL"
        and whale_count >= 1
    )
