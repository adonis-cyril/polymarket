"""
Extract actionable entry patterns from whale trade history.

Takes the raw trade history from profiler.py and cross-references with
Binance historical candles to reconstruct the market conditions at the
time of each whale trade. Outputs structured entry conditions that the
live signal stack can match against.

Patterns extracted:
1. Delta thresholds: what price delta range do top wallets enter at?
2. Timing patterns: how many seconds before close do they enter?
3. Token price preferences: what token prices do they pay?
4. Asset rotation: do they prefer certain assets at certain times?
5. Skip conditions: when do ALL top wallets sit out?
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from data.historical import HistoricalCandle
from whale_tracking.profiler import WalletTrade

logger = logging.getLogger(__name__)


@dataclass
class EntryCondition:
    """A single entry condition bucket with associated win rate."""
    delta_min: float          # Minimum absolute delta % for this bucket
    delta_max: float          # Maximum absolute delta %
    seconds_left_max: int     # Maximum seconds remaining at entry
    seconds_left_min: int     # Minimum seconds remaining at entry
    trade_count: int = 0      # Number of trades in this bucket
    wins: int = 0
    losses: int = 0

    @property
    def win_rate(self) -> float:
        if self.trade_count == 0:
            return 0.0
        return self.wins / self.trade_count


@dataclass
class WalletProfile:
    """Complete extracted profile for a whale wallet."""
    address: str
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_entry_delta_pct: float
    avg_entry_seconds_left: int
    avg_token_price_paid: float
    preferred_assets: list[str]
    entry_conditions: list[EntryCondition]
    hourly_activity: dict[int, int] = field(default_factory=dict)  # hour → trade count


# Delta buckets for pattern extraction
DELTA_BUCKETS = [
    (0.00, 0.04),   # Very small delta
    (0.04, 0.08),   # Small delta
    (0.08, 0.15),   # Medium delta
    (0.15, 999.0),  # Large delta
]

# Timing buckets
TIMING_BUCKETS = [
    (0, 10),      # Last 10 seconds
    (10, 30),     # 10-30 seconds left
    (30, 60),     # 30-60 seconds left
    (60, 300),    # More than 1 minute left
]


def _find_candle_at(candles: list[HistoricalCandle], timestamp_ms: int) -> Optional[HistoricalCandle]:
    """Find the candle that contains the given timestamp."""
    for candle in candles:
        if candle.open_time <= timestamp_ms <= candle.close_time:
            return candle
    return None


def _find_window_open_price(candles: list[HistoricalCandle], window_ts: int) -> Optional[float]:
    """Find the price at the start of a 5-min window."""
    window_open_ms = window_ts * 1000
    candle = _find_candle_at(candles, window_open_ms)
    if candle:
        return candle.open
    return None


def enrich_trades_with_delta(
    trades: list[WalletTrade],
    candles_by_asset: dict[str, list[HistoricalCandle]],
) -> list[WalletTrade]:
    """
    Cross-reference whale trades with Binance candles to calculate
    the asset delta at the time of each trade.

    Modifies trades in-place, setting btc_delta_pct.
    """
    enriched = 0
    for trade in trades:
        asset_candles = candles_by_asset.get(trade.asset, [])
        if not asset_candles:
            continue

        # Find the price at window open
        open_price = _find_window_open_price(asset_candles, trade.window_ts)
        if not open_price:
            continue

        # Find the price at time of trade
        trade_candle = _find_candle_at(asset_candles, trade.timestamp * 1000)
        if not trade_candle:
            continue

        trade_price = trade_candle.close
        trade.btc_delta_pct = ((trade_price - open_price) / open_price) * 100.0
        enriched += 1

    logger.info("Enriched %d/%d trades with delta data", enriched, len(trades))
    return trades


def extract_entry_conditions(trades: list[WalletTrade]) -> list[EntryCondition]:
    """
    Extract entry condition buckets from a wallet's trade history.

    Groups trades by (delta bucket, timing bucket) and calculates
    win rate for each combination.
    """
    conditions: dict[tuple, EntryCondition] = {}

    for db in DELTA_BUCKETS:
        for tb in TIMING_BUCKETS:
            key = (db, tb)
            conditions[key] = EntryCondition(
                delta_min=db[0],
                delta_max=db[1],
                seconds_left_min=tb[0],
                seconds_left_max=tb[1],
            )

    for trade in trades:
        abs_delta = abs(trade.btc_delta_pct)

        for db in DELTA_BUCKETS:
            if db[0] <= abs_delta < db[1]:
                for tb in TIMING_BUCKETS:
                    if tb[0] <= trade.seconds_left < tb[1]:
                        key = (db, tb)
                        ec = conditions[key]
                        ec.trade_count += 1
                        if trade.outcome == "WIN":
                            ec.wins += 1
                        else:
                            ec.losses += 1
                        break
                break

    # Filter out empty buckets
    return [ec for ec in conditions.values() if ec.trade_count > 0]


def build_wallet_profile(
    address: str,
    trades: list[WalletTrade],
    total_pnl: float,
) -> WalletProfile:
    """
    Build a complete wallet profile from enriched trade history.
    """
    if not trades:
        return WalletProfile(
            address=address,
            total_trades=0,
            win_rate=0.0,
            total_pnl=total_pnl,
            avg_entry_delta_pct=0.0,
            avg_entry_seconds_left=0,
            avg_token_price_paid=0.0,
            preferred_assets=[],
            entry_conditions=[],
        )

    wins = sum(1 for t in trades if t.outcome == "WIN")
    total = len(trades)

    # Averages
    deltas = [abs(t.btc_delta_pct) for t in trades if t.btc_delta_pct != 0]
    avg_delta = sum(deltas) / len(deltas) if deltas else 0.0
    avg_seconds = sum(t.seconds_left for t in trades) // total
    avg_price = sum(t.token_price for t in trades) / total

    # Asset preferences
    asset_counts: dict[str, int] = defaultdict(int)
    for t in trades:
        asset_counts[t.asset] += 1
    sorted_assets = sorted(asset_counts.items(), key=lambda x: x[1], reverse=True)
    preferred = [a for a, _ in sorted_assets[:3]]

    # Hourly activity pattern
    hourly: dict[int, int] = defaultdict(int)
    for t in trades:
        hour = (t.timestamp % 86400) // 3600
        hourly[hour] += 1

    # Entry conditions
    entry_conditions = extract_entry_conditions(trades)

    return WalletProfile(
        address=address,
        total_trades=total,
        win_rate=wins / total,
        total_pnl=total_pnl,
        avg_entry_delta_pct=round(avg_delta, 6),
        avg_entry_seconds_left=avg_seconds,
        avg_token_price_paid=round(avg_price, 4),
        preferred_assets=preferred,
        entry_conditions=entry_conditions,
        hourly_activity=dict(hourly),
    )


def get_whale_pattern_signal(
    profiles: list[WalletProfile],
    asset: str,
    delta_pct: float,
    seconds_left: int,
) -> float:
    """
    Score how well current conditions match historical whale entry patterns.

    Returns a score from -1.0 to +1.0:
    +1.0 = strong match (conditions align with where top wallets win 90%+)
     0.0 = neutral (no clear pattern match)
    -1.0 = anti-match (top wallets historically avoid these conditions)
    """
    if not profiles:
        return 0.0

    abs_delta = abs(delta_pct)
    scores = []

    for profile in profiles:
        if not profile.entry_conditions:
            continue

        # Weight by wallet's overall win rate
        wallet_weight = profile.win_rate

        # Find matching entry condition
        best_match: Optional[EntryCondition] = None
        for ec in profile.entry_conditions:
            if (ec.delta_min <= abs_delta < ec.delta_max and
                    ec.seconds_left_min <= seconds_left < ec.seconds_left_max):
                best_match = ec
                break

        if best_match and best_match.trade_count >= 5:
            # Score based on win rate in this bucket vs overall
            bucket_wr = best_match.win_rate
            if bucket_wr > 0.80:
                score = 1.0 * wallet_weight
            elif bucket_wr > 0.65:
                score = 0.5 * wallet_weight
            elif bucket_wr < 0.40:
                score = -0.5 * wallet_weight
            else:
                score = 0.0
            scores.append(score)
        elif best_match is None:
            # This wallet never trades in these conditions → slight negative
            scores.append(-0.2 * wallet_weight)

    if not scores:
        return 0.0

    # Average across all profiled wallets, clamped to [-1, 1]
    avg = sum(scores) / len(scores)
    return max(-1.0, min(1.0, round(avg, 4)))


def get_consensus_thresholds(profiles: list[WalletProfile]) -> dict:
    """
    Extract collective thresholds from all profiled wallets.

    Returns consensus on minimum delta, preferred timing, etc.
    """
    if not profiles:
        return {}

    all_deltas = [p.avg_entry_delta_pct for p in profiles if p.avg_entry_delta_pct > 0]
    all_timing = [p.avg_entry_seconds_left for p in profiles if p.avg_entry_seconds_left > 0]
    all_prices = [p.avg_token_price_paid for p in profiles if p.avg_token_price_paid > 0]

    return {
        "min_delta_consensus": min(all_deltas) if all_deltas else 0.04,
        "avg_delta": sum(all_deltas) / len(all_deltas) if all_deltas else 0.07,
        "avg_entry_seconds_left": int(sum(all_timing) / len(all_timing)) if all_timing else 22,
        "avg_token_price": sum(all_prices) / len(all_prices) if all_prices else 0.78,
        "wallet_count": len(profiles),
    }
