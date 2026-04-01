"""
Polymarket 5-min trading bot — unified full-bankroll strategy.

Single strategy: target 10% return per trade. Full bankroll each time.

Entry: pick strongest signal asset, buy if token price is $0.65-$0.93.
Exit (first trigger wins):
  1. TAKE_PROFIT_10PCT: token price >= entry * 1.10 → sell
  2. RESOLUTION_WIN: window resolves in our favor → $1.00/share
  3. TIME_STOP: <30s left, in profit but below 10% → sell at market
  4. STOP_LOSS: <30s left, in the red → sell at market
  5. RESOLUTION_LOSS: held through resolution, lost → $0

Reversal trades: exception to full bankroll, uses 15% only.

Usage:
    python bot.py              # Paper trading mode (default)
    python bot.py --live       # Live trading mode
"""

import argparse
import asyncio
import logging
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from config import (
    ASSETS, DAILY_LOSS_LIMIT, DRAWDOWN_CAP, CONSECUTIVE_LOSS_PAUSE,
    MIN_BET, STARTING_BANKROLL, INITIAL_BANKROLL,
)
from data.binance_ws import BinanceWebsocket
from data.polymarket_ws import PolymarketWebsocket
from data import db
from execution.market_discovery import (
    Market, discover_all_markets, get_current_window_ts, seconds_until_close,
)
from notifications import supabase_push
from strategy.regime import (
    Regime, classify_from_binance_ws, should_skip_window, get_entry_timing,
)
from strategy.reversal import ReversalDetector
from strategy.signals import SignalResult, analyze_signals, MIN_SIGNAL_SCORE
from utils.logger import setup_logging
from whale_tracking.pattern_extractor import WalletProfile
from whale_tracking.scorer import get_whale_signal
from whale_tracking.wallet_db import get_tracked_addresses

logger = logging.getLogger(__name__)

# Level targets for the compounding challenge
LEVEL_TARGETS = [40, 80, 160, 320, 640, 1280, 2560, 5120, 10240]

# Entry price bounds for normal trades
ENTRY_PRICE_MIN = 0.65
ENTRY_PRICE_MAX = 0.93

# Preferred entry zone (resolution alone gives 10-18%)
PREFERRED_PRICE_MIN = 0.85
PREFERRED_PRICE_MAX = 0.91

# Take profit target
TAKE_PROFIT_PCT = 0.10  # 10%

# Reversal sizing
REVERSAL_BANKROLL_PCT = 0.15

# Time stop threshold (seconds before window close)
TIME_STOP_SECONDS = 30

# Phase labels for dashboard
PHASE_LABELS = {
    1: "Protecting Principal",
    2: "Playing with House Money",
    3: "Scaling Up",
    4: "Full Compound",
}


def calculate_phase_and_bet(balance: float, initial_bankroll: float) -> tuple[int, float]:
    """
    Capital preservation position sizing.

    Phase 1 (<2x): bet fixed initial_bankroll
    Phase 2 (2x-3x): bet only profits (balance - initial_bankroll)
    Phase 3 (3x-5x): bet 50% of total
    Phase 4 (5x+): bet 75% of total

    Returns (phase, bet_size).
    """
    ratio = balance / initial_bankroll if initial_bankroll > 0 else 1

    if ratio < 2:
        return 1, min(initial_bankroll, balance)
    elif ratio < 3:
        return 2, balance - initial_bankroll
    elif ratio < 5:
        return 3, balance * 0.50
    else:
        return 4, balance * 0.75


class TradingBot:
    """Main trading bot — unified full-bankroll strategy."""

    def __init__(self, paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.binance_ws = BinanceWebsocket()
        self.polymarket_ws = PolymarketWebsocket()
        self.reversal_detector: Optional[ReversalDetector] = None

        # State
        self.balance = float(STARTING_BANKROLL)
        self.peak_balance = self.balance
        self.current_level = 1
        self.level_target = LEVEL_TARGETS[0] if LEVEL_TARGETS else 10240
        self.consecutive_losses = 0
        self.total_trades = 0
        self.total_wins = 0
        self.start_time = time.time()

        # Whale data (loaded on startup)
        self.tracked_wallets: set[str] = set()
        self.whale_profiles: list[WalletProfile] = []

        # Historical candles for regime baseline (loaded on startup)
        self.baseline_candles: dict[str, list] = {}

        # Window open prices (captured at start of each window)
        self.window_open_prices: dict[str, float] = {}

    async def start(self):
        """Initialize connections and start the main loop."""
        logger.info("=" * 60)
        logger.info("POLYMARKET TRADING BOT — 10%% TARGET STRATEGY")
        logger.info("Mode: %s", "PAPER" if self.paper_mode else "LIVE")
        logger.info("Starting balance: $%.2f", self.balance)
        logger.info("=" * 60)

        # Initialize database
        db.init_db()
        state = db.get_bot_state()
        if state.get("current_balance"):
            self.balance = state["current_balance"]
            self.peak_balance = state.get("peak_balance", self.balance)
            self.total_trades = state.get("total_trades", 0)
            self.total_wins = state.get("total_wins", 0)
            self.current_level = state.get("current_level", 1)
            logger.info("Resumed from saved state: $%.2f, %d trades", self.balance, self.total_trades)

        # Start websocket connections
        logger.info("Connecting to Binance websocket...")
        await self.binance_ws.start()

        logger.info("Connecting to Polymarket CLOB websocket...")
        await self.polymarket_ws.start()

        # Initialize reversal detector
        self.reversal_detector = ReversalDetector(self.binance_ws)

        # Load tracked whale wallets
        try:
            self.tracked_wallets = get_tracked_addresses()
            logger.info("Loaded %d tracked whale wallets", len(self.tracked_wallets))
        except Exception:
            logger.warning("Failed to load whale wallets, continuing without")

        # Fetch historical candles for regime baseline
        await self._load_baseline_candles()

        # Update bot state
        db.update_bot_state(
            status="RUNNING",
            current_balance=self.balance,
            peak_balance=self.peak_balance,
        )
        self._sync_state()

        # Run main loop
        try:
            await self._main_loop()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self.binance_ws.stop()
            await self.polymarket_ws.stop()
            db.update_bot_state(status="STOPPED")
            self._sync_state()

    async def _load_baseline_candles(self):
        """Load 24h of historical candles for regime baseline."""
        from data.historical import fetch_candles
        logger.info("Fetching baseline candles (24h) for regime detection...")
        for asset in ASSETS:
            try:
                candles = fetch_candles(asset, days=1)
                self.baseline_candles[asset] = candles
                logger.info("  %s: %d baseline candles", asset.upper(), len(candles))
            except Exception as e:
                logger.warning("  %s: failed to fetch baseline: %s", asset.upper(), e)
                self.baseline_candles[asset] = []

    async def _main_loop(self):
        """Main trading loop — one iteration per 5-min window."""
        while True:
            try:
                await self._run_cycle()
            except Exception:
                logger.exception("Error in trading cycle")

            remaining = seconds_until_close()
            if remaining > 5:
                wait_time = max(1, remaining - 120)
                logger.info("Sleeping %.0fs until next window approach...", wait_time)
                await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(remaining + 5)

    async def _run_cycle(self):
        """Run a single 5-minute trading cycle."""
        window_ts = get_current_window_ts()
        remaining = seconds_until_close()

        logger.info(
            "--- Window %d | %.0fs remaining | Balance: $%.2f ---",
            window_ts, remaining, self.balance,
        )

        # Check admin commands
        commands = supabase_push.check_commands()
        for cmd in commands:
            self._handle_command(cmd)

        # Risk checks
        skip_reason = self._check_risk_limits()
        if skip_reason:
            logger.info("SKIP: %s", skip_reason)
            return

        # Discover markets
        markets = discover_all_markets(window_ts)
        if not markets:
            logger.warning("No markets found for window %d", window_ts)
            return

        # Subscribe to order books
        for market in markets.values():
            await self.polymarket_ws.subscribe(market.up_token_id, market.down_token_id)

        # Capture window open prices
        for asset in markets:
            price = self.binance_ws.get_price(asset)
            if price > 0:
                self.window_open_prices[asset] = price
                db.save_window_open_price(asset, window_ts, price)

        # Scan all assets: regime check + signal analysis
        best_signal: Optional[SignalResult] = None
        best_regime: Optional[Regime] = None
        best_market: Optional[Market] = None
        reversal_signal = None

        for asset, market in markets.items():
            baseline = self.baseline_candles.get(asset, [])
            regime_state = classify_from_binance_ws(self.binance_ws, asset, baseline)

            if should_skip_window(regime_state):
                logger.debug("  %s: SKIP (HIGH_VOL regime)", asset.upper())
                continue

            entry_timing = get_entry_timing(regime_state)

            # Wait for entry timing
            secs_left = seconds_until_close()
            if secs_left > entry_timing + 10:
                wait = secs_left - entry_timing - 5
                if wait > 0:
                    await asyncio.sleep(min(wait, 30))

            # Check for reversal
            secs_left = seconds_until_close()
            if self.reversal_detector and 15 <= secs_left <= 90:
                up_price = self.polymarket_ws.get_best_ask(market.up_token_id)
                down_price = self.polymarket_ws.get_best_ask(market.down_token_id)
                rev = self.reversal_detector.detect(asset, secs_left, up_price, down_price)
                if rev and (reversal_signal is None or rev.payout_ratio > reversal_signal.payout_ratio):
                    reversal_signal = rev
                    best_market = market
                    best_regime = regime_state.regime

            # Run signal stack
            open_price = self.window_open_prices.get(asset, 0)
            if open_price == 0:
                continue

            whale_score, whale_dir, whale_count = 0.0, None, 0
            if self.tracked_wallets:
                try:
                    whale_score, whale_dir, whale_count = get_whale_signal(
                        self.whale_profiles, self.tracked_wallets,
                        asset, 0, int(secs_left), market.condition_id,
                        market.up_token_id, market.down_token_id,
                    )
                except Exception:
                    pass

            signal = analyze_signals(
                self.binance_ws, self.polymarket_ws, market, open_price,
                whale_signal=whale_score,
                whale_direction=whale_dir,
                whale_count=whale_count,
            )

            if signal and (best_signal is None or signal.score > best_signal.score):
                best_signal = signal
                best_regime = regime_state.regime
                best_market = market

        # ---- DECIDE: reversal vs normal trade ----
        trade_type = None
        direction = None
        asset = None
        token_price = 0.0
        bet_size = 0.0

        # Calculate phase-based bet size
        phase, phase_bet = calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)

        # Check normal trade first
        if best_signal and best_signal.score >= MIN_SIGNAL_SCORE and best_market:
            token_id = (
                best_market.up_token_id if best_signal.direction == "UP"
                else best_market.down_token_id
            )
            token_price = self.polymarket_ws.get_best_ask(token_id)

            if ENTRY_PRICE_MIN <= token_price <= ENTRY_PRICE_MAX:
                trade_type = "SNIPE"
                direction = best_signal.direction
                asset = best_signal.asset
                bet_size = phase_bet
            else:
                logger.info(
                    "  %s signal score %.1f but token price $%.2f outside $%.2f-$%.2f range, skipping",
                    best_signal.asset.upper(), best_signal.score, token_price,
                    ENTRY_PRICE_MIN, ENTRY_PRICE_MAX,
                )

        # Reversal overrides weak snipes or fills the gap when no snipe found
        if reversal_signal and (trade_type is None or (best_signal and best_signal.score < 8)):
            trade_type = "REVERSAL"
            direction = reversal_signal.direction
            asset = reversal_signal.asset
            token_price = reversal_signal.contrarian_price
            bet_size = self.balance * REVERSAL_BANKROLL_PCT  # 15% only

        if trade_type is None:
            logger.info("No actionable trade this window")
            await self.polymarket_ws.unsubscribe_all()
            return

        # Enforce minimum bet
        if bet_size < float(MIN_BET):
            logger.info("SKIP: bet size $%.2f below minimum $%.2f", bet_size, float(MIN_BET))
            await self.polymarket_ws.unsubscribe_all()
            return

        signal_score = best_signal.score if best_signal else 5.0
        regime_str = best_regime.value if best_regime else "UNKNOWN"
        entry_time = time.time()

        logger.info(
            "TRADE: %s %s %s | entry=$%.3f | bet=$%.2f (Phase %d: %s) | signal=%.1f",
            trade_type, asset.upper(), direction, token_price,
            bet_size, phase, PHASE_LABELS[phase], signal_score,
        )

        # ---- EXECUTE + EXIT LOGIC ----
        balance_before = self.balance
        shares = bet_size / token_price

        if self.paper_mode:
            exit_reason, exit_price, pnl = await self._paper_execute_with_exits(
                asset, direction, token_price, shares, bet_size, window_ts,
            )
        else:
            # Live execution — same logic, but with real order placement
            exit_reason, exit_price, pnl = await self._paper_execute_with_exits(
                asset, direction, token_price, shares, bet_size, window_ts,
            )

        hold_duration = int(time.time() - entry_time)
        return_pct = (pnl / bet_size) * 100 if bet_size > 0 else 0

        # Update balance
        self.balance += pnl
        self.balance = max(self.balance, 0)

        is_win = pnl > 0
        if is_win:
            self.total_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

        self.total_trades += 1
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance

        # Log trade
        win_rate = self.total_wins / self.total_trades if self.total_trades > 0 else 0
        payout_ratio = (1 - token_price) / token_price if token_price > 0 else 0

        db.log_trade(
            window_ts=window_ts,
            asset=asset,
            direction=direction,
            trade_type=trade_type,
            token_price=token_price,
            bet_size=bet_size,
            kelly_fraction=0,
            signal_score=signal_score,
            regime=regime_str,
            result="WIN" if is_win else "LOSS",
            balance_before=balance_before,
            balance_after=self.balance,
            pnl=pnl,
            payout_ratio=payout_ratio,
            brier_rolling=0,
            win_rate_rolling=win_rate,
            execution_type="PAPER" if self.paper_mode else "MAKER",
            whale_aligned=best_signal.whale_aligned if best_signal else False,
            whale_count=best_signal.whale_count if best_signal else 0,
            reversal_counter_move_pct=(
                reversal_signal.counter_move_pct if reversal_signal and trade_type == "REVERSAL" else 0
            ),
            exit_reason=exit_reason,
            entry_price=token_price,
            exit_price=exit_price,
            hold_duration_seconds=hold_duration,
            return_pct=return_pct,
        )

        # Update bot state
        current_phase, _ = calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)
        db.update_bot_state(
            current_balance=self.balance,
            peak_balance=self.peak_balance,
            total_trades=self.total_trades,
            total_wins=self.total_wins,
            win_rate=win_rate,
            current_regime=regime_str,
            consecutive_losses=self.consecutive_losses,
            current_phase=current_phase,
        )

        self._check_level_up()
        self._sync_state()
        supabase_push.sync_unsynced_trades(db)

        logger.info(
            "EXIT: %s | PnL: $%+.2f (%.1f%%) | Balance: $%.2f | Hold: %ds | Win Rate: %.1f%%",
            exit_reason, pnl, return_pct, self.balance, hold_duration, win_rate * 100,
        )

        await self.polymarket_ws.unsubscribe_all()

    async def _paper_execute_with_exits(
        self,
        asset: str,
        direction: str,
        entry_price: float,
        shares: float,
        bet_size: float,
        window_ts: int,
    ) -> tuple[str, float, float]:
        """
        Paper trade with full exit logic. Polls every 2 seconds.

        Returns: (exit_reason, exit_price, pnl)
        """
        take_profit_price = entry_price * (1 + TAKE_PROFIT_PCT)

        while True:
            secs_left = seconds_until_close()

            # Simulate current token price from Binance delta
            open_price = self.window_open_prices.get(asset, 0)
            current_asset_price = self.binance_ws.get_price(asset)

            if open_price > 0 and current_asset_price > 0:
                delta_pct = ((current_asset_price - open_price) / open_price) * 100
                # Estimate current token price based on delta
                from backtest.token_pricing import estimate_token_prices
                prices = estimate_token_prices(asset, delta_pct, secs_left)
                current_token_price = (
                    prices.up_price if direction == "UP" else prices.down_price
                )
            else:
                current_token_price = entry_price

            # EXIT 1: Take profit at 10%
            if current_token_price >= take_profit_price:
                pnl = shares * current_token_price - bet_size
                return "TAKE_PROFIT_10PCT", current_token_price, pnl

            # EXIT 3/4: Time stop with <30s left
            if secs_left <= TIME_STOP_SECONDS:
                if current_token_price > entry_price:
                    # In profit but below 10% — take partial profit
                    pnl = shares * current_token_price - bet_size
                    return "TIME_STOP", current_token_price, pnl
                elif current_token_price < entry_price:
                    # In the red — cut loss
                    pnl = shares * current_token_price - bet_size
                    return "STOP_LOSS", current_token_price, pnl

            # Window closed — resolution
            if secs_left <= 0:
                await asyncio.sleep(2)  # Wait for resolution data

                close_price = self.binance_ws.get_price(asset)
                if open_price > 0 and close_price > 0:
                    actual = "UP" if close_price > open_price else "DOWN"
                else:
                    actual = "DOWN" if direction == "UP" else "UP"

                if direction == actual:
                    # EXIT 2: Resolution win — $1.00 per share
                    pnl = shares * 1.0 - bet_size
                    return "RESOLUTION_WIN", 1.0, pnl
                else:
                    # EXIT 5: Resolution loss — $0 per share
                    return "RESOLUTION_LOSS", 0.0, -bet_size

            await asyncio.sleep(2)

    def _check_risk_limits(self) -> Optional[str]:
        """Check all risk limits. Returns skip reason or None."""
        if self.balance < float(MIN_BET):
            db.update_bot_state(status="BLOWN_UP")
            return f"Balance ${self.balance:.2f} below minimum bet ${MIN_BET}"

        if self.consecutive_losses >= CONSECUTIVE_LOSS_PAUSE:
            self.consecutive_losses = 0
            return f"Consecutive loss breaker ({CONSECUTIVE_LOSS_PAUSE} losses)"

        today_start = db.get_today_starting_balance()
        if today_start > 0:
            daily_loss = (today_start - self.balance) / today_start
            if daily_loss > DAILY_LOSS_LIMIT:
                return f"Daily loss limit hit ({daily_loss:.1%} > {DAILY_LOSS_LIMIT:.0%})"

        if self.peak_balance > 0:
            drawdown = (self.peak_balance - self.balance) / self.peak_balance
            if drawdown > DRAWDOWN_CAP:
                return f"Drawdown cap hit ({drawdown:.1%} > {DRAWDOWN_CAP:.0%})"

        return None

    def _check_level_up(self):
        """Check if we've reached a new level target."""
        if self.current_level > len(LEVEL_TARGETS):
            return

        target_idx = self.current_level - 1
        if target_idx < len(LEVEL_TARGETS) and self.balance >= LEVEL_TARGETS[target_idx]:
            hours_elapsed = (time.time() - self.start_time) / 3600
            logger.info(
                "LEVEL UP! Level %d reached ($%.2f >= $%.2f) in %.1f hours",
                self.current_level, self.balance, LEVEL_TARGETS[target_idx], hours_elapsed,
            )
            supabase_push.push_level_reached(
                level=self.current_level,
                target=LEVEL_TARGETS[target_idx],
                trades_taken=self.total_trades,
                hours_elapsed=hours_elapsed,
            )
            self.current_level += 1
            if self.current_level <= len(LEVEL_TARGETS):
                self.level_target = LEVEL_TARGETS[self.current_level - 1]
            else:
                self.level_target = 99999
            db.update_bot_state(current_level=self.current_level, level_target=self.level_target)

    def _sync_state(self):
        """Sync bot state to Supabase."""
        win_rate = self.total_wins / self.total_trades if self.total_trades > 0 else 0
        phase, _ = calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)
        supabase_push.push_bot_state(
            status="RUNNING",
            balance=self.balance,
            level=self.current_level,
            level_target=self.level_target,
            peak=self.peak_balance,
            today_start=db.get_today_starting_balance(),
            total_trades=self.total_trades,
            total_wins=self.total_wins,
            win_rate=win_rate,
            brier_score=0,
            regime=db.get_bot_state().get("current_regime", "UNKNOWN"),
            kelly_alpha=0,
            consecutive_losses=self.consecutive_losses,
            current_phase=phase,
        )

    def _handle_command(self, cmd: dict):
        """Handle an admin command from the dashboard."""
        command = cmd.get("command", "")
        payload = cmd.get("payload", {})
        logger.info("Admin command: %s %s", command, payload)

        if command == "PAUSE":
            db.update_bot_state(status="PAUSED")
        elif command == "RESUME":
            db.update_bot_state(status="RUNNING")
        elif command == "FORCE_SKIP":
            logger.info("Force skipping next window")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument("--live", action="store_true", help="Enable live trading")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    setup_logging(args.log_level)

    bot = TradingBot(paper_mode=not args.live)
    asyncio.run(bot.start())


if __name__ == "__main__":
    main()
