"""
Combined whale signal scorer.

Merges historical pattern matching with live whale activity detection
into a single weighted signal for the main strategy.

Total whale weight in signal stack: 3.5
- Historical pattern match: weight 2.0
- Live whale confirmation: weight 1.5
- Alignment bonus: if both fire in same direction, 1.5x multiplier
"""

import logging
from typing import Optional

from whale_tracking.live_monitor import WhaleLiveSignal, check_whale_activity
from whale_tracking.pattern_extractor import WalletProfile, get_whale_pattern_signal

logger = logging.getLogger(__name__)

PATTERN_WEIGHT = 2.0
LIVE_WEIGHT = 1.5
ALIGNMENT_MULTIPLIER = 1.5


def get_whale_signal(
    profiles: list[WalletProfile],
    tracked_wallets: set[str],
    asset: str,
    delta_pct: float,
    seconds_left: int,
    condition_id: str,
    up_token_id: str = "",
    down_token_id: str = "",
    inferred_direction: Optional[str] = None,
) -> tuple[float, Optional[str], int]:
    """
    Get combined whale signal for the current market.

    Args:
        profiles: List of WalletProfile objects from pattern_extractor.
        tracked_wallets: Set of tracked wallet addresses.
        asset: Asset key.
        delta_pct: Current price delta percentage.
        seconds_left: Seconds remaining in window.
        condition_id: Market condition ID for live trade lookup.
        up_token_id: UP token ID.
        down_token_id: DOWN token ID.
        inferred_direction: The direction our signals suggest ('UP' or 'DOWN').

    Returns:
        Tuple of (combined_score, whale_direction, num_whales).
        combined_score can be negative (anti-pattern) or positive (confirmation).
    """
    # Historical pattern match
    pattern_score = get_whale_pattern_signal(profiles, asset, delta_pct, seconds_left)

    # Live whale activity
    live_signal = check_whale_activity(
        condition_id, tracked_wallets, up_token_id, down_token_id,
    )

    # Weighted combination
    combined = (pattern_score * PATTERN_WEIGHT) + (live_signal.signal_score * LIVE_WEIGHT)

    # Alignment bonus: if historical patterns AND live whales agree with our direction
    if inferred_direction and live_signal.direction:
        pattern_agrees = (
            (pattern_score > 0 and inferred_direction == live_signal.direction) or
            (pattern_score < 0 and inferred_direction != live_signal.direction)
        )
        live_agrees = live_signal.direction == inferred_direction

        if pattern_agrees and live_agrees:
            combined *= ALIGNMENT_MULTIPLIER
            logger.info(
                "Whale alignment bonus: pattern + live agree on %s (%.2f → %.2f)",
                inferred_direction, combined / ALIGNMENT_MULTIPLIER, combined,
            )

    return combined, live_signal.direction, live_signal.num_whales
