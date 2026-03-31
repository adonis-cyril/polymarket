"""
Backtest engine for the Polymarket 5-min trading strategy.

Replays historical 1-min candles to simulate the bot's decision loop:
1. Group candles into 5-min windows
2. For each window, run volatility regime check
3. Simulate entry timing and signal generation (delta-based)
4. Size bets via fractional Kelly criterion
5. Resolve outcomes and track P&L, win rate, Brier score

Uses token_pricing.py for realistic token price simulation so that
backtest results approximate live trading conditions.

Usage:
    from data.historical import fetch_all_assets
    from backtest.runner import run_backtest, BacktestConfig

    candles = fetch_all_assets(days=30)
    config = BacktestConfig()
    result = run_backtest(candles, config)
    result.print_summary()
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from backtest.token_pricing import (
    estimate_token_prices,
    estimate_win_probability,
    simulate_window_outcome,
    calculate_pnl,
    get_payout_ratio,
)
from data.historical import HistoricalCandle
from strategy.regime import (
    Regime,
    calculate_atr,
    is_trending,
    ATR_PERIOD,
    LOW_VOL_THRESHOLD,
    HIGH_VOL_THRESHOLD,
    ENTRY_TIMING,
)

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 300
WINDOW_MS = WINDOW_SECONDS * 1000


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    starting_balance: float = 20.00
    min_bet: float = 4.75
    max_position_pct: float = 0.40        # Max 40% of bankroll per trade
    min_signal_score: float = 3.0         # Minimum signal score to trade
    min_delta_pct: float = 0.03           # Minimum delta to consider
    entry_seconds_before_close: int = 15  # When to "enter" within each window

    # Kelly parameters
    kelly_alpha: float = 0.25             # Fractional Kelly multiplier
    brier_tiers: dict = field(default_factory=lambda: {
        (0.35, 1.0): 0.10,
        (0.25, 0.35): 0.15,
        (0.15, 0.25): 0.25,
        (0.00, 0.15): 0.40,
    })

    # Risk limits
    daily_loss_limit: float = 0.20        # 20% of day-start balance
    drawdown_cap: float = 0.40            # 40% from peak
    consecutive_loss_pause: int = 5

    # Regime settings
    skip_high_vol: bool = True
    use_regime_timing: bool = True

    # Reversal settings
    enable_reversals: bool = True
    reversal_min_market_lean: float = 0.60
    reversal_max_market_lean: float = 0.85
    reversal_min_counter_move: float = 0.05
    reversal_max_position_pct: float = 0.15


@dataclass
class BacktestTrade:
    """A single simulated trade."""
    window_ts: int
    asset: str
    direction: str
    trade_type: str           # 'SNIPE' or 'REVERSAL'
    token_price: float
    bet_size: float
    kelly_fraction: float
    signal_score: float
    regime: str
    result: str               # 'WIN' or 'LOSS'
    pnl: float
    balance_before: float
    balance_after: float
    payout_ratio: float
    win_prob_estimate: float
    delta_pct: float


@dataclass
class BacktestResult:
    """Complete backtest results."""
    config: BacktestConfig
    trades: list[BacktestTrade] = field(default_factory=list)
    starting_balance: float = 20.00
    final_balance: float = 20.00
    peak_balance: float = 20.00
    max_drawdown_pct: float = 0.0
    windows_seen: int = 0
    windows_skipped_regime: int = 0
    windows_skipped_no_edge: int = 0
    windows_skipped_risk: int = 0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.result == "WIN")

    @property
    def losses(self) -> int:
        return self.total_trades - self.wins

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def total_pnl(self) -> float:
        return self.final_balance - self.starting_balance

    @property
    def roi_pct(self) -> float:
        return (self.total_pnl / self.starting_balance) * 100 if self.starting_balance else 0.0

    @property
    def snipe_trades(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.trade_type == "SNIPE"]

    @property
    def reversal_trades(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.trade_type == "REVERSAL"]

    @property
    def snipe_win_rate(self) -> float:
        snipes = self.snipe_trades
        if not snipes:
            return 0.0
        return sum(1 for t in snipes if t.result == "WIN") / len(snipes)

    @property
    def reversal_win_rate(self) -> float:
        reversals = self.reversal_trades
        if not reversals:
            return 0.0
        return sum(1 for t in reversals if t.result == "WIN") / len(reversals)

    def calculate_brier_score(self) -> float:
        """Rolling Brier score: mean squared error of probability estimates."""
        if not self.trades:
            return 0.5
        total = 0.0
        for t in self.trades:
            actual = 1.0 if t.result == "WIN" else 0.0
            total += (t.win_prob_estimate - actual) ** 2
        return total / len(self.trades)

    def print_summary(self):
        brier = self.calculate_brier_score()
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        print(f"  Balance:      ${self.starting_balance:.2f} → ${self.final_balance:.2f} ({self.roi_pct:+.1f}%)")
        print(f"  Peak:         ${self.peak_balance:.2f} | Max Drawdown: {self.max_drawdown_pct:.1f}%")
        print(f"  Total Trades: {self.total_trades} | Win Rate: {self.win_rate:.1%}")
        print(f"  Snipes:       {len(self.snipe_trades)} ({self.snipe_win_rate:.1%} win rate)")
        print(f"  Reversals:    {len(self.reversal_trades)} ({self.reversal_win_rate:.1%} win rate)")
        print(f"  Brier Score:  {brier:.4f}")
        print(f"  Windows:      {self.windows_seen} seen | {self.windows_skipped_regime} skipped (regime)"
              f" | {self.windows_skipped_no_edge} skipped (no edge)"
              f" | {self.windows_skipped_risk} skipped (risk)")
        print("=" * 60)


def _group_candles_into_windows(
    candles: list[HistoricalCandle],
) -> dict[int, list[HistoricalCandle]]:
    """Group 1-min candles into 5-min windows by window_ts."""
    windows: dict[int, list[HistoricalCandle]] = {}
    for c in candles:
        # Window start = open_time floored to nearest 5-min boundary
        window_ts = (c.open_time // WINDOW_MS) * (WINDOW_SECONDS)
        if window_ts not in windows:
            windows[window_ts] = []
        windows[window_ts].append(c)
    return windows


def _get_kelly_alpha(brier_score: float, tiers: dict) -> float:
    """Get fractional Kelly alpha from Brier score tiers."""
    for (low, high), alpha in tiers.items():
        if low <= brier_score < high:
            return alpha
    return 0.10  # Fallback: very conservative


def _calculate_kelly_bet(
    win_prob: float,
    token_price: float,
    balance: float,
    alpha: float,
    max_pct: float,
    min_bet: float,
) -> tuple[float, float]:
    """
    Calculate Kelly bet size.
    Returns (bet_size, kelly_fraction). bet_size=0 means no edge.
    """
    if token_price <= 0 or token_price >= 1.0:
        return 0.0, 0.0

    b = (1.0 - token_price) / token_price  # payout odds
    q = 1.0 - win_prob

    full_kelly = (win_prob * b - q) / b
    if full_kelly <= 0:
        return 0.0, 0.0

    frac_kelly = alpha * full_kelly
    bet_size = frac_kelly * balance

    bet_size = max(bet_size, min_bet)
    bet_size = min(bet_size, balance * max_pct)
    bet_size = min(bet_size, balance)  # Never bet more than we have

    if bet_size > balance:
        return 0.0, 0.0

    return bet_size, frac_kelly


def _classify_regime_from_candles(
    current_candles: list[HistoricalCandle],
    baseline_candles: list[HistoricalCandle],
) -> Regime:
    """Classify regime from historical candle lists."""
    atr_current = calculate_atr(current_candles[-ATR_PERIOD:])
    atr_baseline = calculate_atr(baseline_candles)

    if atr_baseline == 0:
        return Regime.MEDIUM_VOL

    ratio = atr_current / atr_baseline
    trending, _ = is_trending(current_candles[-ATR_PERIOD:])

    if ratio < LOW_VOL_THRESHOLD:
        return Regime.LOW_VOL
    elif ratio < HIGH_VOL_THRESHOLD:
        return Regime.MEDIUM_VOL
    elif trending:
        return Regime.TRENDING_VOL
    else:
        return Regime.HIGH_VOL


def _check_reversal(
    asset: str,
    window_candles: list[HistoricalCandle],
    config: BacktestConfig,
) -> Optional[dict]:
    """
    Check if a reversal setup exists in this window.

    Looks at the last 1-2 candles to detect a counter-move against
    the prevailing direction.
    """
    if len(window_candles) < 3:
        return None

    open_price = window_candles[0].open
    # Price ~60s before close (second-to-last candle)
    recent_price = window_candles[-2].close
    # Price at entry time (last candle)
    current_price = window_candles[-1].close

    # Delta up to the recent point
    delta_to_recent = ((recent_price - open_price) / open_price) * 100
    # Delta from recent to current (counter-move detection)
    counter_move = ((current_price - recent_price) / recent_price) * 100

    # Simulate token prices at the recent point
    seconds_at_recent = 60  # approximate
    prices = estimate_token_prices(asset, delta_to_recent, seconds_at_recent)
    market_lean = max(prices.up_price, prices.down_price)
    market_direction = "UP" if prices.up_price > prices.down_price else "DOWN"

    # Check reversal conditions
    if not (config.reversal_min_market_lean <= market_lean <= config.reversal_max_market_lean):
        return None

    # Counter-move must be against market direction
    is_counter = (
        (market_direction == "UP" and counter_move < -config.reversal_min_counter_move) or
        (market_direction == "DOWN" and counter_move > config.reversal_min_counter_move)
    )
    if not is_counter:
        return None

    contrarian_side = "DOWN" if market_direction == "UP" else "UP"
    contrarian_price = prices.down_price if market_direction == "UP" else prices.up_price

    if contrarian_price < 0.10 or contrarian_price > 0.40:
        return None

    win_prob = 0.25 + min(abs(counter_move) * 0.5, 0.15)

    return {
        "direction": contrarian_side,
        "contrarian_price": contrarian_price,
        "win_prob": win_prob,
        "counter_move_pct": abs(counter_move),
    }


def run_backtest(
    candles_by_asset: dict[str, list[HistoricalCandle]],
    config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """
    Run a full backtest across all assets.

    Args:
        candles_by_asset: Dict mapping asset key to list of 1-min candles.
        config: Backtest configuration. Uses defaults if None.

    Returns:
        BacktestResult with all trades and statistics.
    """
    if config is None:
        config = BacktestConfig()

    result = BacktestResult(config=config, starting_balance=config.starting_balance)
    balance = config.starting_balance
    peak = balance
    consecutive_losses = 0
    day_start_balance = balance
    current_day = None

    # Build rolling Brier score
    brier_sum = 0.0
    brier_count = 0

    # Group candles into windows per asset
    windows_by_asset: dict[str, dict[int, list[HistoricalCandle]]] = {}
    all_window_timestamps: set[int] = set()

    for asset, candles in candles_by_asset.items():
        windows_by_asset[asset] = _group_candles_into_windows(candles)
        all_window_timestamps.update(windows_by_asset[asset].keys())

    # Build baseline candle lists per asset (for regime ATR baseline)
    baseline_candles: dict[str, list[HistoricalCandle]] = {}
    for asset, candles in candles_by_asset.items():
        # Use first 24h as baseline, then the full history
        baseline_candles[asset] = candles[:1440] if len(candles) > 1440 else candles

    # Process windows in chronological order
    sorted_windows = sorted(all_window_timestamps)

    for window_ts in sorted_windows:
        result.windows_seen += 1

        # Day boundary tracking
        day = window_ts // 86400
        if day != current_day:
            current_day = day
            day_start_balance = balance

        # Risk checks
        if balance < config.min_bet:
            result.windows_skipped_risk += 1
            continue

        if consecutive_losses >= config.consecutive_loss_pause:
            result.windows_skipped_risk += 1
            consecutive_losses = 0  # Reset after pause
            continue

        if day_start_balance > 0 and (day_start_balance - balance) / day_start_balance > config.daily_loss_limit:
            result.windows_skipped_risk += 1
            continue

        if peak > 0 and (peak - balance) / peak > config.drawdown_cap:
            result.windows_skipped_risk += 1
            continue

        # Evaluate each asset for this window
        best_trade: Optional[dict] = None
        best_score = 0.0

        for asset in candles_by_asset:
            window_candles = windows_by_asset[asset].get(window_ts, [])
            if len(window_candles) < 2:
                continue

            # Get candles leading up to this window for regime check
            asset_candles = candles_by_asset[asset]
            # Find index of first candle in this window
            window_open_ms = window_ts * 1000
            candle_idx = None
            for idx, c in enumerate(asset_candles):
                if c.open_time >= window_open_ms:
                    candle_idx = idx
                    break
            if candle_idx is None or candle_idx < ATR_PERIOD:
                continue

            recent_candles = asset_candles[max(0, candle_idx - ATR_PERIOD):candle_idx]

            # Regime check
            regime = _classify_regime_from_candles(recent_candles, baseline_candles[asset])

            if config.skip_high_vol and regime == Regime.HIGH_VOL:
                result.windows_skipped_regime += 1
                continue

            # Check for reversal first
            if config.enable_reversals:
                reversal = _check_reversal(asset, window_candles, config)
                if reversal:
                    # Reversal takes priority
                    best_trade = {
                        "asset": asset,
                        "trade_type": "REVERSAL",
                        "direction": reversal["direction"],
                        "token_price": reversal["contrarian_price"],
                        "win_prob": reversal["win_prob"],
                        "delta_pct": reversal["counter_move_pct"],
                        "regime": regime.value,
                        "window_candles": window_candles,
                        "signal_score": 5.0,  # Reversal gets fixed high score
                    }
                    best_score = 999  # Always prefer reversal
                    break

            # Normal snipe: calculate delta at entry time
            open_price = window_candles[0].open
            close_price = window_candles[-1].close

            # Simulate entry point (use second-to-last candle as "entry" price)
            entry_candle_idx = max(0, len(window_candles) - 2)
            entry_price = window_candles[entry_candle_idx].close
            delta_pct = ((entry_price - open_price) / open_price) * 100

            if abs(delta_pct) < config.min_delta_pct:
                continue

            # Direction: follow the delta
            direction = "UP" if delta_pct > 0 else "DOWN"

            # Estimate token price and win probability
            seconds_left = config.entry_seconds_before_close
            if config.use_regime_timing:
                seconds_left = ENTRY_TIMING.get(regime, 15)

            prices = estimate_token_prices(asset, delta_pct, seconds_left)
            token_price = prices.up_ask if direction == "UP" else prices.down_ask
            win_prob = estimate_win_probability(delta_pct, seconds_left, asset)

            # Signal score (simplified for backtest: delta-weighted)
            signal_score = abs(delta_pct) * 7.0  # Delta weight = 7 per spec

            if signal_score > best_score and signal_score >= config.min_signal_score:
                best_score = signal_score
                best_trade = {
                    "asset": asset,
                    "trade_type": "SNIPE",
                    "direction": direction,
                    "token_price": token_price,
                    "win_prob": win_prob,
                    "delta_pct": delta_pct,
                    "regime": regime.value,
                    "window_candles": window_candles,
                    "signal_score": signal_score,
                }

        if not best_trade:
            result.windows_skipped_no_edge += 1
            continue

        # Size the bet
        brier_score = brier_sum / brier_count if brier_count > 0 else 0.30
        alpha = _get_kelly_alpha(brier_score, config.brier_tiers)

        if best_trade["trade_type"] == "REVERSAL":
            alpha *= 0.5  # Half alpha for reversals
            max_pct = config.reversal_max_position_pct
        else:
            max_pct = config.max_position_pct

        bet_size, kelly_frac = _calculate_kelly_bet(
            win_prob=best_trade["win_prob"],
            token_price=best_trade["token_price"],
            balance=balance,
            alpha=alpha,
            max_pct=max_pct,
            min_bet=config.min_bet,
        )

        if bet_size <= 0 or bet_size > balance:
            result.windows_skipped_no_edge += 1
            continue

        # Resolve outcome
        wc = best_trade["window_candles"]
        outcome = simulate_window_outcome(wc[0].open, wc[-1].close)
        trade_result = "WIN" if best_trade["direction"] == outcome else "LOSS"

        pnl = calculate_pnl(best_trade["direction"], best_trade["token_price"], bet_size, outcome)
        balance_before = balance
        balance += pnl
        balance = max(balance, 0)

        # Update peak and drawdown
        if balance > peak:
            peak = balance
        drawdown = (peak - balance) / peak * 100 if peak > 0 else 0
        if drawdown > result.max_drawdown_pct:
            result.max_drawdown_pct = drawdown

        # Track consecutive losses
        if trade_result == "LOSS":
            consecutive_losses += 1
        else:
            consecutive_losses = 0

        # Update Brier score
        actual = 1.0 if trade_result == "WIN" else 0.0
        brier_sum += (best_trade["win_prob"] - actual) ** 2
        brier_count += 1

        # Record trade
        trade = BacktestTrade(
            window_ts=window_ts,
            asset=best_trade["asset"],
            direction=best_trade["direction"],
            trade_type=best_trade["trade_type"],
            token_price=best_trade["token_price"],
            bet_size=round(bet_size, 4),
            kelly_fraction=round(kelly_frac, 6),
            signal_score=round(best_trade["signal_score"], 4),
            regime=best_trade["regime"],
            result=trade_result,
            pnl=round(pnl, 4),
            balance_before=round(balance_before, 4),
            balance_after=round(balance, 4),
            payout_ratio=round(get_payout_ratio(best_trade["token_price"]), 4),
            win_prob_estimate=round(best_trade["win_prob"], 4),
            delta_pct=round(best_trade["delta_pct"], 6),
        )
        result.trades.append(trade)

    result.final_balance = round(balance, 4)
    result.peak_balance = round(peak, 4)

    return result
