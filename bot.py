"""
Polymarket 5-min trading bot — active position management.

Targets 10% net profit per trade after fees. Uses quarter-Kelly sizing
within capital preservation phases. Actively manages positions: can exit
early (take profit, stop loss, edge vanishing) and re-enter up to 3 times
per window.

Exit triggers (first fires):
  1. TAKE_PROFIT_10PCT:     token >= entry * 1.10 (after fees)
  2. RESOLUTION_WIN:        window resolves in our favor
  3. ACCEPTABLE_PROFIT:     token >= entry * 1.07, conviction fading, <45s
  4. EDGE_VANISHED_PROFIT:  signal dropped <1.5 but still in profit
  5. BREAKEVEN_EXIT:        signal dropped <1.0, price near entry
  6. STOP_LOSS:             token <= entry * 0.92 or <20s and losing
  7. RESOLUTION_LOSS:       held through resolution, lost

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

import requests
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
from strategy.kelly import calculate_kelly_bet, is_done_deal, DEFAULT_KELLY_FRACTION
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

LEVEL_TARGETS = [40, 80, 160, 320, 640, 1280, 2560, 5120, 10240]

# Entry price bounds
ENTRY_PRICE_MIN = 0.65
ENTRY_PRICE_MAX = 0.93

# Exit thresholds
TAKE_PROFIT_MULT = 1.10       # 10% take profit
ACCEPTABLE_PROFIT_MULT = 1.07 # 7% acceptable
STOP_LOSS_MULT = 0.92         # 8% stop loss
EDGE_VANISH_SCORE = 1.5       # Signal score below which edge is gone
BREAKEVEN_SCORE = 1.0         # Signal score for breakeven exit
BREAKEVEN_PRICE_PCT = 0.02    # Within 2% of entry = roughly breakeven

# Re-entry limits
MAX_ENTRIES_PER_WINDOW = 3
MIN_SECONDS_FOR_REENTRY = 90

# Reversal sizing
REVERSAL_BANKROLL_PCT = 0.15

# Fee threshold
MAX_ACCEPTABLE_FEE_PCT = 3.0  # Pause if round-trip fees > 3%
MIN_NET_PROFIT_PCT = 7.0      # Only enter if estimated net >= 7%

# CLOB fee endpoint
CLOB_FEE_URL = "https://clob.polymarket.com/fee-rate"

PHASE_LABELS = {
    1: "Protecting Principal",
    2: "Playing with House Money",
    3: "Scaling Up",
    4: "Full Compound",
}


def calculate_phase_and_bet(balance: float, initial_bankroll: float) -> tuple[int, float]:
    """Capital preservation phase sizing."""
    ratio = balance / initial_bankroll if initial_bankroll > 0 else 1
    if ratio < 2:
        return 1, min(initial_bankroll, balance)
    elif ratio < 3:
        return 2, balance - initial_bankroll
    elif ratio < 5:
        return 3, balance * 0.50
    else:
        return 4, balance * 0.75


def fetch_fee_rate() -> float:
    """Fetch current Polymarket fee rate. Returns fee as decimal (e.g., 0.02 = 2%)."""
    try:
        resp = requests.get(CLOB_FEE_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        # API returns maker/taker rates
        maker = float(data.get("maker", 0))
        taker = float(data.get("taker", 0.02))
        return maker  # We use maker orders primarily
    except Exception:
        return 0.0  # Assume 0 if can't fetch (maker orders are often 0 fee)


class TradingBot:
    """Main trading bot with active position management."""

    def __init__(self, paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.binance_ws = BinanceWebsocket()
        self.polymarket_ws = PolymarketWebsocket()
        self.reversal_detector: Optional[ReversalDetector] = None

        self.balance = float(STARTING_BANKROLL)
        self.peak_balance = self.balance
        self.current_level = 1
        self.level_target = LEVEL_TARGETS[0] if LEVEL_TARGETS else 10240
        self.consecutive_losses = 0
        self.total_trades = 0
        self.total_wins = 0
        self.start_time = time.time()
        self.current_fee_rate = 0.0

        self.tracked_wallets: set[str] = set()
        self.whale_profiles: list[WalletProfile] = []
        self.baseline_candles: dict[str, list] = {}
        self.window_open_prices: dict[str, float] = {}

    async def start(self):
        """Initialize and run."""
        logger.info("=" * 60)
        logger.info("POLYMARKET BOT — Active Management + 10%% Target")
        logger.info("Mode: %s | Balance: $%.2f", "PAPER" if self.paper_mode else "LIVE", self.balance)
        logger.info("=" * 60)

        db.init_db()
        state = db.get_bot_state()
        if state.get("current_balance"):
            self.balance = state["current_balance"]
            self.peak_balance = state.get("peak_balance", self.balance)
            self.total_trades = state.get("total_trades", 0)
            self.total_wins = state.get("total_wins", 0)
            self.current_level = state.get("current_level", 1)
            logger.info("Resumed: $%.2f, %d trades", self.balance, self.total_trades)

        await self.binance_ws.start()
        await self.polymarket_ws.start()
        self.reversal_detector = ReversalDetector(self.binance_ws)

        try:
            self.tracked_wallets = get_tracked_addresses()
            logger.info("Loaded %d tracked whale wallets", len(self.tracked_wallets))
        except Exception:
            logger.warning("Failed to load whale wallets")

        await self._load_baseline_candles()

        db.update_bot_state(status="RUNNING", current_balance=self.balance, peak_balance=self.peak_balance)
        self._sync_state()

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
        from data.historical import fetch_candles
        logger.info("Fetching baseline candles (24h)...")
        for asset in ASSETS:
            try:
                self.baseline_candles[asset] = fetch_candles(asset, days=1)
                logger.info("  %s: %d candles", asset.upper(), len(self.baseline_candles[asset]))
            except Exception as e:
                logger.warning("  %s: failed: %s", asset.upper(), e)
                self.baseline_candles[asset] = []

    async def _main_loop(self):
        while True:
            try:
                await self._run_window()
            except Exception:
                logger.exception("Error in trading cycle")

            remaining = seconds_until_close()
            if remaining > 5:
                await asyncio.sleep(max(1, remaining - 120))
            else:
                await asyncio.sleep(remaining + 5)

    async def _run_window(self):
        """Run a single 5-min window: scan, enter, manage, exit, repeat."""
        window_ts = get_current_window_ts()
        remaining = seconds_until_close()

        logger.info("--- Window %d | %.0fs left | $%.2f ---", window_ts, remaining, self.balance)

        # Admin commands
        for cmd in supabase_push.check_commands():
            self._handle_command(cmd)

        # Risk checks
        skip = self._check_risk_limits()
        if skip:
            logger.info("SKIP: %s", skip)
            return

        # Fee check
        self.current_fee_rate = fetch_fee_rate()
        round_trip_fee_pct = self.current_fee_rate * 2 * 100
        if round_trip_fee_pct > MAX_ACCEPTABLE_FEE_PCT:
            logger.warning("PAUSE: fees abnormally high (%.2f%% round trip)", round_trip_fee_pct)
            return

        # Discover markets
        markets = discover_all_markets(window_ts)
        if not markets:
            return

        for m in markets.values():
            await self.polymarket_ws.subscribe(m.up_token_id, m.down_token_id)

        # Capture open prices
        for asset in markets:
            price = self.binance_ws.get_price(asset)
            if price > 0:
                self.window_open_prices[asset] = price
                db.save_window_open_price(asset, window_ts, price)

        # --- ENTRY + MANAGEMENT LOOP (can re-enter up to 3 times) ---
        entries_this_window = 0

        while entries_this_window < MAX_ENTRIES_PER_WINDOW:
            secs_left = seconds_until_close()
            if secs_left < 20:
                break

            # Find best opportunity
            opportunity = await self._find_best_opportunity(markets, window_ts)
            if not opportunity:
                break

            trade_type = opportunity["trade_type"]
            asset = opportunity["asset"]
            direction = opportunity["direction"]
            token_price = opportunity["token_price"]
            signal_score = opportunity["signal_score"]
            regime = opportunity["regime"]
            whale_count = opportunity["whale_count"]
            whale_aligned = opportunity["whale_aligned"]
            market = opportunity["market"]

            # Position sizing
            phase, phase_amount = calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)

            if trade_type == "REVERSAL":
                bet_size = self.balance * REVERSAL_BANKROLL_PCT
            elif trade_type == "DONE_DEAL":
                bet_size = phase_amount  # Full port of phase amount
            else:
                # Quarter-Kelly within phase amount
                win_prob = opportunity.get("win_prob", 0.70)
                bet_size = calculate_kelly_bet(win_prob, token_price, phase_amount)

            if bet_size < float(MIN_BET):
                if self.balance >= float(MIN_BET):
                    bet_size = float(MIN_BET)
                else:
                    break

            bet_size = min(bet_size, self.balance)

            # Check estimated net profit after fees
            payout_ratio = (1.0 - token_price) / token_price
            estimated_gross_pct = payout_ratio * 100
            estimated_net_pct = estimated_gross_pct - (round_trip_fee_pct)
            if estimated_net_pct < MIN_NET_PROFIT_PCT and trade_type not in ("REVERSAL", "DONE_DEAL"):
                logger.info("SKIP: estimated net profit %.1f%% < %.1f%% minimum", estimated_net_pct, MIN_NET_PROFIT_PCT)
                break

            entries_this_window += 1
            entry_time = time.time()
            shares = bet_size / token_price
            fees_on_entry = bet_size * self.current_fee_rate

            logger.info(
                "ENTER #%d: %s %s %s | $%.3f | $%.2f bet | Phase %d | signal=%.1f",
                entries_this_window, trade_type, asset.upper(), direction,
                token_price, bet_size, phase, signal_score,
            )

            # --- ACTIVE POSITION MANAGEMENT ---
            exit_reason, exit_price, gross_pnl = await self._manage_position(
                asset, direction, token_price, shares, bet_size,
                signal_score, regime, market, window_ts,
            )

            hold_duration = int(time.time() - entry_time)
            fees_on_exit = (shares * exit_price) * self.current_fee_rate if exit_price > 0 else 0
            total_fees = fees_on_entry + fees_on_exit
            net_pnl = gross_pnl - total_fees
            return_pct = (net_pnl / bet_size) * 100 if bet_size > 0 else 0

            # Update balance
            balance_before = self.balance
            self.balance += net_pnl
            self.balance = max(self.balance, 0)

            is_win = net_pnl > 0
            if is_win:
                self.total_wins += 1
                self.consecutive_losses = 0
            else:
                self.consecutive_losses += 1
            self.total_trades += 1

            if self.balance > self.peak_balance:
                self.peak_balance = self.balance

            win_rate = self.total_wins / self.total_trades

            # Log trade
            db.log_trade(
                window_ts=window_ts, asset=asset, direction=direction,
                trade_type=trade_type, token_price=token_price,
                bet_size=bet_size, kelly_fraction=DEFAULT_KELLY_FRACTION,
                signal_score=signal_score, regime=regime,
                result="WIN" if is_win else "LOSS",
                balance_before=balance_before, balance_after=self.balance,
                pnl=round(gross_pnl, 4),
                payout_ratio=round(payout_ratio, 4),
                brier_rolling=0, win_rate_rolling=win_rate,
                execution_type="PAPER" if self.paper_mode else "MAKER",
                whale_aligned=whale_aligned, whale_count=whale_count,
                reversal_counter_move_pct=opportunity.get("counter_move_pct", 0),
                exit_reason=exit_reason,
                entry_price=token_price, exit_price=exit_price,
                hold_duration_seconds=hold_duration,
                return_pct=round(return_pct, 4),
                fee_rate=self.current_fee_rate,
                fees_paid=round(total_fees, 4),
                net_profit_after_fees=round(net_pnl, 4),
                num_entries_this_window=entries_this_window,
            )

            current_phase, _ = calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)
            db.update_bot_state(
                current_balance=self.balance, peak_balance=self.peak_balance,
                total_trades=self.total_trades, total_wins=self.total_wins,
                win_rate=win_rate, current_regime=regime,
                consecutive_losses=self.consecutive_losses,
                current_phase=current_phase,
            )

            logger.info(
                "EXIT: %s | Gross: $%+.2f | Fees: $%.2f | Net: $%+.2f (%.1f%%) | Bal: $%.2f | %ds hold",
                exit_reason, gross_pnl, total_fees, net_pnl, return_pct, self.balance, hold_duration,
            )

            # Can we re-enter?
            secs_left = seconds_until_close()
            profitable_exit = exit_reason in ("TAKE_PROFIT_10PCT", "ACCEPTABLE_PROFIT", "EDGE_VANISHED_PROFIT")
            if not (profitable_exit and secs_left > MIN_SECONDS_FOR_REENTRY):
                break

            logger.info("Re-entry eligible: %.0fs remaining, scanning...", secs_left)

        # End of window
        self._check_level_up()
        self._sync_state()
        supabase_push.sync_unsynced_trades(db)
        await self.polymarket_ws.unsubscribe_all()

    async def _find_best_opportunity(
        self, markets: dict[str, Market], window_ts: int,
    ) -> Optional[dict]:
        """Scan all assets and return the best trade opportunity."""
        best_signal: Optional[SignalResult] = None
        best_regime_str = "UNKNOWN"
        best_market: Optional[Market] = None
        reversal_signal = None

        for asset, market in markets.items():
            baseline = self.baseline_candles.get(asset, [])
            regime_state = classify_from_binance_ws(self.binance_ws, asset, baseline)

            if should_skip_window(regime_state):
                continue

            entry_timing = get_entry_timing(regime_state)
            secs_left = seconds_until_close()

            if secs_left > entry_timing + 10:
                wait = min(secs_left - entry_timing - 5, 30)
                if wait > 0:
                    await asyncio.sleep(wait)

            secs_left = seconds_until_close()

            # Reversal check
            if self.reversal_detector and 15 <= secs_left <= 90:
                up_p = self.polymarket_ws.get_best_ask(market.up_token_id)
                down_p = self.polymarket_ws.get_best_ask(market.down_token_id)
                rev = self.reversal_detector.detect(asset, secs_left, up_p, down_p)
                if rev and (reversal_signal is None or rev.payout_ratio > reversal_signal.payout_ratio):
                    reversal_signal = rev
                    best_market = market
                    best_regime_str = regime_state.regime.value

            # Signal stack
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
                whale_signal=whale_score, whale_direction=whale_dir, whale_count=whale_count,
            )

            if signal and (best_signal is None or signal.score > best_signal.score):
                best_signal = signal
                best_regime_str = regime_state.regime.value
                best_market = market

        # Build opportunity dict
        if best_signal and best_signal.score >= MIN_SIGNAL_SCORE and best_market:
            token_id = (
                best_market.up_token_id if best_signal.direction == "UP"
                else best_market.down_token_id
            )
            token_price = self.polymarket_ws.get_best_ask(token_id)
            secs_left = seconds_until_close()

            # Check done-deal conditions
            if is_done_deal(token_price, secs_left, best_signal.score,
                            best_regime_str, best_signal.whale_count):
                return {
                    "trade_type": "DONE_DEAL",
                    "asset": best_signal.asset, "direction": best_signal.direction,
                    "token_price": token_price, "signal_score": best_signal.score,
                    "regime": best_regime_str, "whale_count": best_signal.whale_count,
                    "whale_aligned": best_signal.whale_aligned, "market": best_market,
                    "win_prob": 0.95,
                }

            # Normal entry within price bounds
            if ENTRY_PRICE_MIN <= token_price <= ENTRY_PRICE_MAX:
                return {
                    "trade_type": "SNIPE",
                    "asset": best_signal.asset, "direction": best_signal.direction,
                    "token_price": token_price, "signal_score": best_signal.score,
                    "regime": best_regime_str, "whale_count": best_signal.whale_count,
                    "whale_aligned": best_signal.whale_aligned, "market": best_market,
                    "win_prob": best_signal.win_prob_estimate,
                }

        # Reversal fallback
        if reversal_signal and best_market:
            return {
                "trade_type": "REVERSAL",
                "asset": reversal_signal.asset, "direction": reversal_signal.direction,
                "token_price": reversal_signal.contrarian_price,
                "signal_score": 5.0, "regime": best_regime_str,
                "whale_count": 0, "whale_aligned": False, "market": best_market,
                "win_prob": reversal_signal.win_prob,
                "counter_move_pct": reversal_signal.counter_move_pct,
            }

        return None

    async def _manage_position(
        self, asset: str, direction: str, entry_price: float,
        shares: float, bet_size: float, entry_signal_score: float,
        regime: str, market: Market, window_ts: int,
    ) -> tuple[str, float, float]:
        """
        Actively manage a position. Polls every 1.5 seconds.
        Returns (exit_reason, exit_price, gross_pnl).
        """
        take_profit_target = entry_price * TAKE_PROFIT_MULT
        acceptable_target = entry_price * ACCEPTABLE_PROFIT_MULT
        stop_loss_level = entry_price * STOP_LOSS_MULT

        while True:
            secs_left = seconds_until_close()

            # Estimate current token price from Binance delta
            open_price = self.window_open_prices.get(asset, 0)
            current_asset_price = self.binance_ws.get_price(asset)

            if open_price > 0 and current_asset_price > 0:
                delta_pct = ((current_asset_price - open_price) / open_price) * 100
                from backtest.token_pricing import estimate_token_prices
                prices = estimate_token_prices(asset, delta_pct, max(secs_left, 1))
                current_token_price = prices.up_price if direction == "UP" else prices.down_price
            else:
                current_token_price = entry_price

            # Re-run signal for conviction tracking
            current_signal_score = entry_signal_score  # Default
            try:
                signal = analyze_signals(
                    self.binance_ws, self.polymarket_ws, market, open_price,
                )
                if signal:
                    current_signal_score = signal.score
                    # Flip: if signal now favors opposite direction, score is negative for us
                    if signal.direction != direction:
                        current_signal_score = -signal.score
            except Exception:
                pass

            in_profit = current_token_price > entry_price
            profit_pct = ((current_token_price - entry_price) / entry_price) * 100

            # EXIT 1: Take profit at 10%
            if current_token_price >= take_profit_target:
                pnl = shares * current_token_price - bet_size
                return "TAKE_PROFIT_10PCT", current_token_price, pnl

            # EXIT 3: Acceptable profit (7%+, conviction fading, <45s)
            if (current_token_price >= acceptable_target
                    and secs_left < 45
                    and current_signal_score < entry_signal_score * 0.7):
                pnl = shares * current_token_price - bet_size
                return "ACCEPTABLE_PROFIT", current_token_price, pnl

            # EXIT 4: Edge vanishing but in profit
            if current_signal_score < EDGE_VANISH_SCORE and in_profit:
                pnl = shares * current_token_price - bet_size
                return "EDGE_VANISHED_PROFIT", current_token_price, pnl

            # EXIT 5: Breakeven exit (signal collapsed, price near entry)
            if (current_signal_score < BREAKEVEN_SCORE
                    and abs(profit_pct) < BREAKEVEN_PRICE_PCT * 100):
                pnl = shares * current_token_price - bet_size
                return "BREAKEVEN_EXIT", current_token_price, pnl

            # EXIT 6: Stop loss
            if current_token_price <= stop_loss_level:
                pnl = shares * current_token_price - bet_size
                return "STOP_LOSS", current_token_price, pnl

            if secs_left < 20 and not in_profit:
                pnl = shares * current_token_price - bet_size
                return "STOP_LOSS", current_token_price, pnl

            # Window closed — resolution
            if secs_left <= 0:
                await asyncio.sleep(2)
                close_price = self.binance_ws.get_price(asset)
                if open_price > 0 and close_price > 0:
                    actual = "UP" if close_price > open_price else "DOWN"
                else:
                    actual = "DOWN" if direction == "UP" else "UP"

                if direction == actual:
                    pnl = shares * 1.0 - bet_size
                    return "RESOLUTION_WIN", 1.0, pnl
                else:
                    return "RESOLUTION_LOSS", 0.0, -bet_size

            await asyncio.sleep(1.5)

    def _check_risk_limits(self) -> Optional[str]:
        if self.balance < float(MIN_BET):
            db.update_bot_state(status="BLOWN_UP")
            return f"Balance ${self.balance:.2f} below minimum"

        if self.consecutive_losses >= CONSECUTIVE_LOSS_PAUSE:
            self.consecutive_losses = 0
            return f"Consecutive loss breaker ({CONSECUTIVE_LOSS_PAUSE})"

        today_start = db.get_today_starting_balance()
        if today_start > 0:
            daily_loss = (today_start - self.balance) / today_start
            if daily_loss > DAILY_LOSS_LIMIT:
                return f"Daily loss limit ({daily_loss:.1%})"

        if self.peak_balance > 0:
            drawdown = (self.peak_balance - self.balance) / self.peak_balance
            if drawdown > DRAWDOWN_CAP:
                return f"Drawdown cap ({drawdown:.1%})"

        return None

    def _check_level_up(self):
        if self.current_level > len(LEVEL_TARGETS):
            return
        idx = self.current_level - 1
        if idx < len(LEVEL_TARGETS) and self.balance >= LEVEL_TARGETS[idx]:
            hours = (time.time() - self.start_time) / 3600
            logger.info("LEVEL UP! %d ($%.2f >= $%.2f) in %.1fh",
                        self.current_level, self.balance, LEVEL_TARGETS[idx], hours)
            supabase_push.push_level_reached(self.current_level, LEVEL_TARGETS[idx], self.total_trades, hours)
            self.current_level += 1
            self.level_target = LEVEL_TARGETS[self.current_level - 1] if self.current_level <= len(LEVEL_TARGETS) else 99999
            db.update_bot_state(current_level=self.current_level, level_target=self.level_target)

    def _sync_state(self):
        win_rate = self.total_wins / self.total_trades if self.total_trades > 0 else 0
        phase, _ = calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)
        supabase_push.push_bot_state(
            status="RUNNING", balance=self.balance, level=self.current_level,
            level_target=self.level_target, peak=self.peak_balance,
            today_start=db.get_today_starting_balance(),
            total_trades=self.total_trades, total_wins=self.total_wins,
            win_rate=win_rate, brier_score=0,
            regime=db.get_bot_state().get("current_regime", "UNKNOWN"),
            kelly_alpha=DEFAULT_KELLY_FRACTION,
            consecutive_losses=self.consecutive_losses, current_phase=phase,
        )

    def _handle_command(self, cmd: dict):
        command = cmd.get("command", "")
        logger.info("Admin command: %s", command)
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
