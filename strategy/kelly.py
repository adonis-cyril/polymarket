"""
Brier-tiered fractional Kelly criterion for position sizing.

Kelly fraction scales with model accuracy (rolling Brier score).
Better accuracy → more aggressive sizing. Poor accuracy → conservative.

The Brier score measures calibration of probability estimates:
- 0.0 = perfect (always predicts correctly with correct confidence)
- 0.25 = random guessing
- 0.5+ = worse than random
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Brier score tiers: (lower_bound, upper_bound) → alpha (fraction of full Kelly)
BRIER_TIERS = {
    (0.35, 1.0): 0.10,   # Bad accuracy: very conservative
    (0.25, 0.35): 0.15,  # Below average
    (0.15, 0.25): 0.25,  # Good
    (0.00, 0.15): 0.40,  # Excellent: most aggressive
}

# Hard limits
MIN_BET_USDC = 4.75       # Polymarket minimum (5 shares)
MAX_POSITION_PCT = 0.40   # Never exceed 40% of bankroll
MAX_REVERSAL_PCT = 0.15   # Reversal trades capped at 15%


@dataclass
class KellyResult:
    """Result of Kelly sizing calculation."""
    bet_size: float
    kelly_fraction: float
    alpha: float
    win_prob: float
    payout_odds: float
    full_kelly: float
    skip_reason: str = ""


def get_alpha_for_brier(brier_score: float) -> float:
    """Get the fractional Kelly alpha from the current Brier score."""
    for (low, high), alpha in BRIER_TIERS.items():
        if low <= brier_score < high:
            return alpha
    return 0.10  # Fallback: very conservative


def calculate_kelly(
    win_prob: float,
    token_price: float,
    balance: float,
    brier_score: float,
    is_reversal: bool = False,
) -> KellyResult:
    """
    Calculate fractional Kelly bet size.

    Args:
        win_prob: Estimated probability of winning (0-1).
        token_price: Price of the token we're buying (0-1).
        balance: Current USDC balance.
        brier_score: Rolling Brier score of our predictions.
        is_reversal: True for reversal trades (uses half alpha, lower cap).

    Returns:
        KellyResult with bet size and supporting data.
    """
    # Payout odds: buy at token_price, win pays $1.00
    if token_price <= 0 or token_price >= 1.0:
        return KellyResult(
            bet_size=0, kelly_fraction=0, alpha=0,
            win_prob=win_prob, payout_odds=0, full_kelly=0,
            skip_reason="Invalid token price",
        )

    b = (1.0 - token_price) / token_price  # payout odds ratio
    q = 1.0 - win_prob

    # Full Kelly: f* = (p*b - q) / b
    full_kelly = (win_prob * b - q) / b

    if full_kelly <= 0:
        return KellyResult(
            bet_size=0, kelly_fraction=0, alpha=0,
            win_prob=win_prob, payout_odds=b, full_kelly=full_kelly,
            skip_reason="No edge (Kelly <= 0)",
        )

    # Get alpha from Brier score
    alpha = get_alpha_for_brier(brier_score)

    # Reversal trades: use half alpha
    if is_reversal:
        alpha *= 0.5

    fractional_kelly = alpha * full_kelly
    bet_size = fractional_kelly * balance

    # Enforce minimum
    if bet_size < MIN_BET_USDC:
        if balance >= MIN_BET_USDC:
            bet_size = MIN_BET_USDC
        else:
            return KellyResult(
                bet_size=0, kelly_fraction=fractional_kelly, alpha=alpha,
                win_prob=win_prob, payout_odds=b, full_kelly=full_kelly,
                skip_reason="Balance below minimum bet",
            )

    # Enforce maximum
    max_pct = MAX_REVERSAL_PCT if is_reversal else MAX_POSITION_PCT
    max_bet = balance * max_pct
    bet_size = min(bet_size, max_bet)

    # Never bet more than we have
    bet_size = min(bet_size, balance)

    return KellyResult(
        bet_size=round(bet_size, 4),
        kelly_fraction=round(fractional_kelly, 6),
        alpha=alpha,
        win_prob=win_prob,
        payout_odds=round(b, 4),
        full_kelly=round(full_kelly, 6),
    )


def update_brier_score(
    predictions: list[tuple[float, bool]],
) -> float:
    """
    Calculate Brier score from a list of (predicted_prob, actual_outcome) pairs.

    Args:
        predictions: List of (probability_estimate, did_win) tuples.

    Returns:
        Brier score (0 = perfect, 0.25 = random, higher = bad).
    """
    if not predictions:
        return 0.30  # Default: slightly below average

    total = sum((prob - (1.0 if won else 0.0)) ** 2 for prob, won in predictions)
    return total / len(predictions)
