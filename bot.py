"""
Main trading bot entry point.

Runs the 5-minute cycle loop:
1. Discover markets for all assets
2. Check volatility regime
3. Wait for entry timing
4. Run signal analysis
5. Size bet via Kelly criterion
6. Execute trade (paper or live)
7. Wait for resolution
8. Update state and sync

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
    MIN_BET, STARTING_BANKROLL,
)
from data.binance_ws import BinanceWebsocket
from data.polymarket_ws import PolymarketWebsocket
from data import db
from execution.market_discovery import (
    Market, discover_all_markets, get_current_window_ts, seconds_until_close,
)
from notifications import supabase_push
from strategy.kelly import calculate_kelly, get_alpha_for_brier
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


class TradingBot:
    """Main trading bot that runs the 5-minute cycle."""

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
        logger.info("POLYMARKET TRADING BOT")
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

        # Push initial state to Supabase
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

            # Wait for next window
            remaining = seconds_until_close()
            if remaining > 5:
                # Wait until near the end of the current window
                wait_time = max(1, remaining - 120)  # Wake up 2 min before close
                logger.info("Sleeping %.0fs until next window approach...", wait_time)
                await asyncio.sleep(wait_time)
            else:
                # Very close to close, wait for next window
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

        # Regime check per asset + find best signal
        best_signal: Optional[SignalResult] = None
        best_regime: Optional[Regime] = None
        best_market: Optional[Market] = None
        reversal_signal = None

        for asset, market in markets.items():
            # Regime check
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
                    logger.debug("  %s: waiting %.0fs for entry window", asset.upper(), wait)
                    await asyncio.sleep(min(wait, 30))

            # Check for reversal
            secs_left = seconds_until_close()
            if self.reversal_detector and 15 <= secs_left <= 90:
                up_price = self.polymarket_ws.get_best_ask(market.up_token_id)
                down_price = self.polymarket_ws.get_best_ask(market.down_token_id)

                rev = self.reversal_detector.detect(
                    asset, secs_left, up_price, down_price,
                )
                if rev and (reversal_signal is None or rev.payout_ratio > reversal_signal.payout_ratio):
                    reversal_signal = rev
                    best_market = market
                    best_regime = regime_state.regime

            # Run signal stack
            open_price = self.window_open_prices.get(asset, 0)
            if open_price == 0:
                continue

            # Get whale signal
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

        # Decide: reversal vs snipe
        trade_signal = None
        trade_type = "SNIPE"
        token_price = 0.0

        if best_signal and best_signal.score >= MIN_SIGNAL_SCORE:
            trade_signal = best_signal
            trade_type = "SNIPE"
            token_price = self.polymarket_ws.get_best_ask(
                best_market.up_token_id if best_signal.direction == "UP"
                else best_market.down_token_id
            )
            # Use signal's win prob if token price is available
            if token_price <= 0 or token_price >= 1.0:
                token_price = 0.70  # Fallback

        if reversal_signal and (trade_signal is None or trade_signal.score < 8):
            # Reversal takes priority over weak snipes
            trade_type = "REVERSAL"
            token_price = reversal_signal.contrarian_price
            if token_price <= 0 or token_price >= 1.0:
                token_price = 0.30

        if trade_signal is None and reversal_signal is None:
            logger.info("No actionable signal this window")
            return

        # Kelly sizing
        brier = db.get_rolling_brier()
        win_prob = (
            reversal_signal.win_prob if trade_type == "REVERSAL"
            else trade_signal.win_prob_estimate
        )

        kelly_result = calculate_kelly(
            win_prob=win_prob,
            token_price=token_price,
            balance=self.balance,
            brier_score=brier,
            is_reversal=(trade_type == "REVERSAL"),
        )

        if kelly_result.bet_size <= 0:
            logger.info("SKIP: %s", kelly_result.skip_reason)
            return

        # Determine direction
        if trade_type == "REVERSAL":
            direction = reversal_signal.direction
            asset = reversal_signal.asset
        else:
            direction = trade_signal.direction
            asset = trade_signal.asset

        logger.info(
            "TRADE: %s %s %s | price=$%.3f | bet=$%.2f | kelly=%.4f | wp=%.1f%%",
            trade_type, asset.upper(), direction, token_price,
            kelly_result.bet_size, kelly_result.kelly_fraction, win_prob * 100,
        )

        # Execute (paper mode: simulate outcome)
        if self.paper_mode:
            result = await self._paper_execute(asset, direction, window_ts)
        else:
            # Live execution would go here
            result = await self._paper_execute(asset, direction, window_ts)

        # Calculate P&L
        balance_before = self.balance
        if result == "WIN":
            shares = kelly_result.bet_size / token_price
            pnl = shares * 1.0 - kelly_result.bet_size
            self.balance += pnl
            self.total_wins += 1
            self.consecutive_losses = 0
        else:
            pnl = -kelly_result.bet_size
            self.balance += pnl
            self.consecutive_losses += 1

        self.total_trades += 1
        self.balance = max(self.balance, 0)

        if self.balance > self.peak_balance:
            self.peak_balance = self.balance

        # Log trade
        win_rate = self.total_wins / self.total_trades if self.total_trades > 0 else 0
        payout_ratio = (1 - token_price) / token_price if token_price > 0 else 0

        db.log_prediction(win_prob, result == "WIN")
        brier = db.get_rolling_brier()

        signal_score = trade_signal.score if trade_signal else 5.0
        regime_str = best_regime.value if best_regime else "UNKNOWN"

        trade_id = db.log_trade(
            window_ts=window_ts,
            asset=asset,
            direction=direction,
            trade_type=trade_type,
            token_price=token_price,
            bet_size=kelly_result.bet_size,
            kelly_fraction=kelly_result.kelly_fraction,
            signal_score=signal_score,
            regime=regime_str,
            result=result,
            balance_before=balance_before,
            balance_after=self.balance,
            pnl=pnl,
            payout_ratio=payout_ratio,
            brier_rolling=brier,
            win_rate_rolling=win_rate,
            execution_type="PAPER" if self.paper_mode else "MAKER",
            whale_aligned=trade_signal.whale_aligned if trade_signal else False,
            whale_count=trade_signal.whale_count if trade_signal else 0,
            reversal_counter_move_pct=(
                reversal_signal.counter_move_pct if reversal_signal and trade_type == "REVERSAL" else 0
            ),
        )

        # Update bot state
        db.update_bot_state(
            current_balance=self.balance,
            peak_balance=self.peak_balance,
            total_trades=self.total_trades,
            total_wins=self.total_wins,
            win_rate=win_rate,
            brier_score=brier,
            current_regime=regime_str,
            kelly_alpha=kelly_result.alpha,
            consecutive_losses=self.consecutive_losses,
        )

        # Check level progression
        self._check_level_up()

        # Sync to Supabase
        self._sync_state()
        supabase_push.sync_unsynced_trades(db)

        logger.info(
            "RESULT: %s | PnL: $%+.2f | Balance: $%.2f | Win Rate: %.1f%% | Brier: %.3f",
            result, pnl, self.balance, win_rate * 100, brier,
        )

        # Unsubscribe from this window's tokens
        await self.polymarket_ws.unsubscribe_all()

    async def _paper_execute(self, asset: str, direction: str, window_ts: int) -> str:
        """
        Paper trade: wait for window to close, check actual outcome.
        """
        remaining = seconds_until_close()
        if remaining > 0:
            logger.info("  Waiting %.0fs for window resolution...", remaining)
            await asyncio.sleep(remaining + 2)

        # Check outcome from Binance
        open_price = self.window_open_prices.get(asset, 0)
        close_price = self.binance_ws.get_price(asset)

        if open_price == 0 or close_price == 0:
            logger.warning("  Missing prices for outcome check, defaulting to LOSS")
            return "LOSS"

        actual = "UP" if close_price > open_price else "DOWN"
        result = "WIN" if direction == actual else "LOSS"

        logger.info(
            "  Outcome: %s (open=$%.2f, close=$%.2f, delta=%.4f%%)",
            actual, open_price, close_price,
            ((close_price - open_price) / open_price) * 100,
        )

        return result

    def _check_risk_limits(self) -> Optional[str]:
        """Check all risk limits. Returns skip reason or None."""
        if self.balance < float(MIN_BET):
            db.update_bot_state(status="BLOWN_UP")
            return f"Balance ${self.balance:.2f} below minimum bet ${MIN_BET}"

        if self.consecutive_losses >= CONSECUTIVE_LOSS_PAUSE:
            self.consecutive_losses = 0  # Reset after pause
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

            db.update_bot_state(
                current_level=self.current_level,
                level_target=self.level_target,
            )

    def _sync_state(self):
        """Sync bot state to Supabase."""
        brier = db.get_rolling_brier()
        win_rate = self.total_wins / self.total_trades if self.total_trades > 0 else 0
        alpha = get_alpha_for_brier(brier)

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
            brier_score=brier,
            regime=db.get_bot_state().get("current_regime", "UNKNOWN"),
            kelly_alpha=alpha,
            consecutive_losses=self.consecutive_losses,
        )

    def _handle_command(self, cmd: dict):
        """Handle an admin command from the dashboard."""
        command = cmd.get("command", "")
        payload = cmd.get("payload", {})

        logger.info("Admin command: %s %s", command, payload)

        if command == "PAUSE":
            db.update_bot_state(status="PAUSED")
            logger.info("Bot PAUSED by admin")
        elif command == "RESUME":
            db.update_bot_state(status="RUNNING")
            logger.info("Bot RESUMED by admin")
        elif command == "SET_KELLY_ALPHA":
            # Handled through Brier score adjustment
            pass
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
