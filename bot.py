"""
Polymarket 5-min trading bot — active position management strategy.

Core philosophy:
- Target 10% net profit per trade (after fees)
- Size bets using fractional Kelly (quarter-Kelly default)
- Actively manage positions: buy/sell contracts mid-window
- Re-enter within the same window up to 3 times

Exit triggers (first one fires):
  1. TAKE_PROFIT_10PCT: token >= entry * 1.10 (after fees)
  2. RESOLUTION_WIN: window resolves in our favor
  3. ACCEPTABLE_PROFIT: token >= entry * 1.07 + conviction fading + <45s left
  4. EDGE_VANISHED_PROFIT: signal dropped below 1.5 + in profit
  5. BREAKEVEN_EXIT: signal dropped below 1.0 + near breakeven
  6. STOP_LOSS: token <= entry * 0.92 OR <20s left and losing
  7. RESOLUTION_LOSS: held through resolution, lost

Special: DONE_DEAL trades (token >= $0.90, <15s, signal >6, whale)
  → Override Kelly, bet full phase-allowed amount

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

# Level targets
LEVEL_TARGETS = [40, 80, 160, 320, 640, 1280, 2560, 5120, 10240]

# Entry price bounds
ENTRY_PRICE_MIN = 0.65
ENTRY_PRICE_MAX = 0.93

# Exit thresholds
TAKE_PROFIT_MULT = 1.10       # 10% gross profit target
ACCEPTABLE_PROFIT_MULT = 1.07 # 7% acceptable profit
STOP_LOSS_MULT = 0.92         # 8% max drawdown
EDGE_VANISH_SCORE = 1.5       # Signal score below this = edge vanishing
BREAKEVEN_SCORE = 1.0         # Signal score below this = get out flat
BREAKEVEN_TOLERANCE = 0.02    # 2% around entry = "breakeven"

# Timing thresholds
ACCEPTABLE_PROFIT_SECS = 45   # Take 7% if < 45s remain
STOP_LOSS_TIME_SECS = 20      # Cut loss if < 20s remain and losing
MIN_REENTRY_SECS = 90         # Minimum time for re-entry

# Re-entry limits
MAX_ENTRIES_PER_WINDOW = 3

# Reversal sizing
REVERSAL_BANKROLL_PCT = 0.15

# Fee safety
MAX_ROUND_TRIP_FEE_PCT = 0.03  # 3% round-trip = abnormal, pause

# Phase labels
PHASE_LABELS = {
    1: "Protecting Principal",
    2: "Playing with House Money",
    3: "Scaling Up",
    4: "Full Compound",
}


def calculate_phase_and_bet(balance: float, initial_bankroll: float) -> tuple[int, float]:
    """
    Capital preservation: returns (phase, max_phase_allowed_bet).
    Kelly then sizes within this ceiling.
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


def estimate_fee_rate() -> float:
    """
    Query Polymarket fee rate. For now returns default.
    TODO: In live mode, query GET /fee-rate from CLOB API.
    """
    return 0.005  # 0.5% per side (1% round-trip) — conservative estimate


class TradingBot:
    """Main trading bot with active position management."""

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

        # Whale data
        self.tracked_wallets: set[str] = set()
        self.whale_profiles: list[WalletProfile] = []

        # Baseline candles for regime
        self.baseline_candles: dict[str, list] = {}

        # Window open prices
        self.window_open_prices: dict[str, float] = {}

    async def start(self):
        """Initialize and run."""
        logger.info("=" * 60)
        logger.info("POLYMARKET BOT — ACTIVE MANAGEMENT + KELLY")
        logger.info("Mode: %s", "PAPER" if self.paper_mode else "LIVE")
        logger.info("Starting balance: $%.2f", self.balance)
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

        logger.info("Connecting to Binance WS...")
        await self.binance_ws.start()
        logger.info("Connecting to Polymarket CLOB WS...")
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
                await self._run_cycle()
            except Exception:
                logger.exception("Error in trading cycle")

            remaining = seconds_until_close()
            if remaining > 5:
                wait_time = max(1, remaining - 120)
                logger.info("Sleeping %.0fs...", wait_time)
                await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(remaining + 5)

    async def _run_cycle(self):
        """One 5-min window cycle. Supports re-entry up to MAX_ENTRIES_PER_WINDOW."""
        window_ts = get_current_window_ts()
        entries_this_window = 0

        logger.info("--- Window %d | Balance: $%.2f ---", window_ts, self.balance)

        # Admin commands
        for cmd in supabase_push.check_commands():
            self._handle_command(cmd)

        # Fee check
        fee_rate = estimate_fee_rate()
        round_trip_fee = fee_rate * 2
        if round_trip_fee > MAX_ROUND_TRIP_FEE_PCT:
            logger.error("ABNORMAL FEES: %.2f%% round-trip > %.2f%%. Pausing.", round_trip_fee * 100, MAX_ROUND_TRIP_FEE_PCT * 100)
            db.update_bot_state(status="PAUSED")
            return

        # Discover markets + subscribe
        markets = discover_all_markets(window_ts)
        if not markets:
            return

        for market in markets.values():
            await self.polymarket_ws.subscribe(market.up_token_id, market.down_token_id)

        # Capture window open prices
        for asset in markets:
            price = self.binance_ws.get_price(asset)
            if price > 0:
                self.window_open_prices[asset] = price
                db.save_window_open_price(asset, window_ts, price)

        # Trade loop: can re-enter up to MAX_ENTRIES_PER_WINDOW times
        while entries_this_window < MAX_ENTRIES_PER_WINDOW:
            skip = self._check_risk_limits()
            if skip:
                logger.info("SKIP: %s", skip)
                break

            remaining = seconds_until_close()
            if remaining < MIN_REENTRY_SECS and entries_this_window > 0:
                logger.info("Not enough time for re-entry (%.0fs left)", remaining)
                break
            if remaining < 30:
                logger.info("Window nearly closed, skipping entry")
                break

            # Find best opportunity
            opportunity = await self._find_best_opportunity(markets, window_ts, fee_rate)
            if not opportunity:
                if entries_this_window == 0:
                    logger.info("No actionable signal this window")
                break

            entries_this_window += 1

            # Execute trade with active management
            await self._execute_and_manage(
                opportunity, window_ts, fee_rate, entries_this_window,
            )

        await self.polymarket_ws.unsubscribe_all()

    async def _find_best_opportunity(
        self, markets: dict[str, Market], window_ts: int, fee_rate: float,
    ) -> Optional[dict]:
        """Scan all assets and return the best trade opportunity."""
        best_signal: Optional[SignalResult] = None
        best_regime: Optional[Regime] = None
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
                up_price = self.polymarket_ws.get_best_ask(market.up_token_id)
                down_price = self.polymarket_ws.get_best_ask(market.down_token_id)
                rev = self.reversal_detector.detect(asset, secs_left, up_price, down_price)
                if rev and (reversal_signal is None or rev.payout_ratio > reversal_signal.payout_ratio):
                    reversal_signal = rev
                    best_market = market
                    best_regime = regime_state.regime

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

            if signal:
                logger.info(
                    "  %s: signal=%.2f dir=%s delta=%.4f%% wp=%.1f%%",
                    asset.upper(), signal.score, signal.direction,
                    signal.delta_pct, signal.win_prob_estimate * 100,
                )
                if signal.score > (best_signal.score if best_signal else 0):
                    best_signal = signal
                    best_regime = regime_state.regime
                    best_market = market
            else:
                current_price = self.binance_ws.get_price(asset)
                if open_price > 0 and current_price > 0:
                    delta = ((current_price - open_price) / open_price) * 100
                    logger.debug("  %s: no signal (delta=%.4f%%)", asset.upper(), delta)

        # Build opportunity dict
        if best_signal and best_signal.score >= MIN_SIGNAL_SCORE and best_market:
            token_id = (
                best_market.up_token_id if best_signal.direction == "UP"
                else best_market.down_token_id
            )
            token_price = self.polymarket_ws.get_best_ask(token_id)

            # If WS order book has no data (returns default 1.0), estimate from Binance delta
            if token_price >= 0.99:
                open_price = self.window_open_prices.get(best_signal.asset, 0)
                current_price = self.binance_ws.get_price(best_signal.asset)
                if open_price > 0 and current_price > 0:
                    delta_pct = ((current_price - open_price) / open_price) * 100
                    secs_left = seconds_until_close()
                    from backtest.token_pricing import estimate_token_prices
                    est = estimate_token_prices(best_signal.asset, delta_pct, max(secs_left, 1))
                    token_price = est.up_ask if best_signal.direction == "UP" else est.down_ask
                    logger.info("  WS book empty, estimated token_price=$%.3f from delta=%.4f%%", token_price, delta_pct)
                else:
                    # Last resort: try Gamma API
                    from execution.market_discovery import get_market_prices
                    gamma_prices = get_market_prices(best_market.condition_id)
                    if gamma_prices:
                        token_price = gamma_prices["up_price"] if best_signal.direction == "UP" else gamma_prices["down_price"]
                        logger.info("  WS book empty, Gamma price=$%.3f", token_price)

            logger.info(
                "  Best: %s %s score=%.2f | token_price=$%.3f (range $%.2f-$%.2f)",
                best_signal.asset.upper(), best_signal.direction,
                best_signal.score, token_price, ENTRY_PRICE_MIN, ENTRY_PRICE_MAX,
            )

            if ENTRY_PRICE_MIN <= token_price <= ENTRY_PRICE_MAX:
                # Check net profit after fees is at least 7%
                net_return_on_resolution = ((1.0 / token_price) - 1) - (fee_rate * 2)
                if net_return_on_resolution < 0.07 and token_price > 0.91:
                    logger.info("  %s: net return %.1f%% < 7%% at $%.2f, skipping",
                                best_signal.asset.upper(), net_return_on_resolution * 100, token_price)
                else:
                    secs_left = seconds_until_close()
                    regime_str = best_regime.value if best_regime else "UNKNOWN"

                    # Check done-deal conditions
                    whale_count = best_signal.whale_count
                    done_deal = is_done_deal(token_price, secs_left, best_signal.score, regime_str, whale_count)

                    # Kelly sizing
                    phase, phase_allowed = calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)

                    if done_deal:
                        bet_size = phase_allowed
                        trade_type = "DONE_DEAL"
                    else:
                        bet_size = calculate_kelly_bet(
                            win_prob=best_signal.win_prob_estimate,
                            token_price=token_price,
                            phase_allowed_amount=phase_allowed,
                        )
                        trade_type = "SNIPE"

                    if bet_size >= float(MIN_BET):
                        return {
                            "trade_type": trade_type,
                            "direction": best_signal.direction,
                            "asset": best_signal.asset,
                            "token_price": token_price,
                            "bet_size": bet_size,
                            "signal": best_signal,
                            "regime": regime_str,
                            "market": best_market,
                            "phase": phase,
                            "token_id": token_id,
                        }

        # Reversal opportunity
        if reversal_signal and best_market:
            bet_size = self.balance * REVERSAL_BANKROLL_PCT
            if bet_size >= float(MIN_BET):
                return {
                    "trade_type": "REVERSAL",
                    "direction": reversal_signal.direction,
                    "asset": reversal_signal.asset,
                    "token_price": reversal_signal.contrarian_price,
                    "bet_size": bet_size,
                    "signal": best_signal,
                    "regime": best_regime.value if best_regime else "UNKNOWN",
                    "market": best_market,
                    "phase": calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)[0],
                    "reversal": reversal_signal,
                    "token_id": "",
                }

        return None

    async def _execute_and_manage(
        self, opp: dict, window_ts: int, fee_rate: float, entry_num: int,
    ):
        """Enter position and actively manage it until exit."""
        trade_type = opp["trade_type"]
        direction = opp["direction"]
        asset = opp["asset"]
        entry_price = opp["token_price"]
        bet_size = min(opp["bet_size"], self.balance)
        signal = opp.get("signal")
        regime = opp["regime"]
        phase = opp["phase"]
        entry_signal_score = signal.score if signal else 5.0

        entry_time = time.time()
        token_id = opp.get("token_id", "")
        execution_type = "PAPER"

        # --- LIVE ENTRY ---
        if not self.paper_mode and token_id:
            from execution.order import place_buy_order, place_sell_order, get_fee_rate
            from execution.balance import get_usdc_balance, wait_for_balance_update
            from execution.claim import claim_position

            best_ask = entry_price
            buy_result = place_buy_order(token_id, bet_size, best_ask)
            if not buy_result.success:
                logger.error("ENTRY FAILED: %s", buy_result.error)
                return
            entry_price = buy_result.fill_price
            shares = buy_result.fill_size
            execution_type = buy_result.execution_type
            fee_rate = get_fee_rate()
        else:
            shares = bet_size / entry_price

        logger.info(
            "ENTER: %s %s %s | $%.3f | $%.2f (Phase %d) | signal=%.1f | entry #%d | %s",
            trade_type, asset.upper(), direction, entry_price,
            bet_size, phase, entry_signal_score, entry_num, execution_type,
        )

        # Active management loop — poll every 1.5 seconds
        exit_reason = None
        exit_price = 0.0

        while exit_reason is None:
            secs_left = seconds_until_close()

            # Get current token price
            if not self.paper_mode and token_id:
                # Live: use CLOB order book for real-time price
                book = self.polymarket_ws.get_order_book(token_id)
                current_token_price = book.mid_price if book else entry_price
            else:
                # Paper: simulate from Binance delta
                open_price = self.window_open_prices.get(asset, 0)
                current_asset_price = self.binance_ws.get_price(asset)
                if open_price > 0 and current_asset_price > 0:
                    delta_pct = ((current_asset_price - open_price) / open_price) * 100
                    from backtest.token_pricing import estimate_token_prices
                    prices = estimate_token_prices(asset, delta_pct, max(secs_left, 1))
                    current_token_price = prices.up_price if direction == "UP" else prices.down_price
                else:
                    current_token_price = entry_price

            # Re-run signal stack to check if conviction holds
            market = opp.get("market")
            current_signal_score = entry_signal_score  # Default
            if market and open_price > 0:
                try:
                    sig = analyze_signals(
                        self.binance_ws, self.polymarket_ws, market, open_price,
                    )
                    if sig:
                        current_signal_score = sig.score
                except Exception:
                    pass

            # Calculate gross/net P&L
            gross_pnl = shares * current_token_price - bet_size
            sell_fee = current_token_price * shares * fee_rate
            buy_fee = bet_size * fee_rate
            net_pnl = gross_pnl - buy_fee - sell_fee
            net_return_pct = (net_pnl / bet_size) * 100 if bet_size > 0 else 0

            # --- EXIT CHECKS (priority order) ---

            # 1. TAKE PROFIT: 10% net profit
            net_tp_price = entry_price * TAKE_PROFIT_MULT
            if current_token_price >= net_tp_price and net_return_pct >= 7:
                exit_reason = "TAKE_PROFIT_10PCT"
                exit_price = current_token_price
                break

            # 2. Window closed → resolution
            if secs_left <= 0:
                await asyncio.sleep(2)
                close_price = self.binance_ws.get_price(asset)
                if open_price > 0 and close_price > 0:
                    actual = "UP" if close_price > open_price else "DOWN"
                else:
                    actual = "DOWN" if direction == "UP" else "UP"

                if direction == actual:
                    exit_reason = "RESOLUTION_WIN"
                    exit_price = 1.0
                else:
                    exit_reason = "RESOLUTION_LOSS"
                    exit_price = 0.0
                break

            # 3. ACCEPTABLE PROFIT: 7%+ and conviction fading, <45s
            if (current_token_price >= entry_price * ACCEPTABLE_PROFIT_MULT
                    and secs_left < ACCEPTABLE_PROFIT_SECS
                    and current_signal_score < entry_signal_score * 0.7):
                exit_reason = "ACCEPTABLE_PROFIT"
                exit_price = current_token_price
                break

            # 4. EDGE VANISHED but in profit
            if (current_signal_score < EDGE_VANISH_SCORE
                    and current_signal_score < entry_signal_score
                    and current_token_price > entry_price):
                exit_reason = "EDGE_VANISHED_PROFIT"
                exit_price = current_token_price
                break

            # 5. BREAKEVEN EXIT: signal collapsed, near entry price
            if (current_signal_score < BREAKEVEN_SCORE
                    and abs(current_token_price - entry_price) / entry_price < BREAKEVEN_TOLERANCE):
                exit_reason = "BREAKEVEN_EXIT"
                exit_price = current_token_price
                break

            # 6. STOP LOSS: 8% drawdown OR <20s and losing
            if current_token_price <= entry_price * STOP_LOSS_MULT:
                exit_reason = "STOP_LOSS"
                exit_price = current_token_price
                break

            if secs_left < STOP_LOSS_TIME_SECS and current_token_price < entry_price:
                exit_reason = "STOP_LOSS"
                exit_price = current_token_price
                break

            await asyncio.sleep(1.5)

        # --- LIVE EXIT EXECUTION ---
        if not self.paper_mode and token_id and exit_reason not in ("RESOLUTION_WIN", "RESOLUTION_LOSS"):
            urgent = exit_reason in ("STOP_LOSS", "BREAKEVEN_EXIT")
            sell_result = place_sell_order(token_id, shares, exit_price, urgent=urgent)
            if sell_result.success:
                exit_price = sell_result.fill_price
                execution_type = sell_result.execution_type
                logger.info("SELL executed: %s at $%.3f", exit_reason, exit_price)
            else:
                logger.error("SELL failed: %s — holding through resolution", sell_result.error)
                # Fall through to resolution

        if not self.paper_mode and exit_reason == "RESOLUTION_WIN":
            # Wait for balance to update, then claim if needed
            expected = self.balance + shares * 1.0 - bet_size
            final_balance = wait_for_balance_update(expected, timeout=30)
            if final_balance < expected * 0.95:
                market = opp.get("market")
                if market:
                    claim_position(market.condition_id)

        # Calculate final P&L
        if exit_price == 1.0:
            # Resolution win
            gross_pnl = shares * 1.0 - bet_size
            fees = bet_size * fee_rate  # Only entry fee, no sell fee on resolution
        elif exit_price == 0.0:
            # Resolution loss
            gross_pnl = -bet_size
            fees = bet_size * fee_rate
        else:
            # Sold mid-window
            gross_pnl = shares * exit_price - bet_size
            fees = bet_size * fee_rate + shares * exit_price * fee_rate

        net_pnl = gross_pnl - fees
        hold_duration = int(time.time() - entry_time)
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

        win_rate = self.total_wins / self.total_trades if self.total_trades > 0 else 0

        # Log trade
        reversal_sig = opp.get("reversal")
        db.log_trade(
            window_ts=window_ts,
            asset=asset,
            direction=direction,
            trade_type=trade_type,
            token_price=entry_price,
            bet_size=bet_size,
            kelly_fraction=DEFAULT_KELLY_FRACTION,
            signal_score=entry_signal_score,
            regime=regime,
            result="WIN" if is_win else "LOSS",
            balance_before=balance_before,
            balance_after=self.balance,
            pnl=round(gross_pnl, 4),
            payout_ratio=round((1 - entry_price) / entry_price, 4) if entry_price > 0 else 0,
            brier_rolling=0,
            win_rate_rolling=win_rate,
            execution_type=execution_type,
            whale_aligned=signal.whale_aligned if signal else False,
            whale_count=signal.whale_count if signal else 0,
            reversal_counter_move_pct=reversal_sig.counter_move_pct if reversal_sig else 0,
            exit_reason=exit_reason,
            entry_price=entry_price,
            exit_price=exit_price,
            hold_duration_seconds=hold_duration,
            return_pct=round(return_pct, 4),
            fee_rate=fee_rate,
            fees_paid=round(fees, 4),
            net_profit_after_fees=round(net_pnl, 4),
            num_entries_this_window=entry_num,
        )

        # Update bot state
        current_phase, _ = calculate_phase_and_bet(self.balance, INITIAL_BANKROLL)
        db.update_bot_state(
            current_balance=self.balance,
            peak_balance=self.peak_balance,
            total_trades=self.total_trades,
            total_wins=self.total_wins,
            win_rate=win_rate,
            current_regime=regime,
            consecutive_losses=self.consecutive_losses,
            current_phase=current_phase,
        )

        self._check_level_up()
        self._sync_state()
        supabase_push.sync_unsynced_trades(db)

        logger.info(
            "EXIT: %s | Gross: $%+.2f | Fees: $%.2f | Net: $%+.2f (%.1f%%) | Balance: $%.2f | Hold: %ds",
            exit_reason, gross_pnl, fees, net_pnl, return_pct, self.balance, hold_duration,
        )

    def _check_risk_limits(self) -> Optional[str]:
        if self.balance < float(MIN_BET):
            db.update_bot_state(status="BLOWN_UP")
            return f"Balance ${self.balance:.2f} below minimum bet"

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
            logger.info("LEVEL UP! Level %d ($%.2f) in %.1fh", self.current_level, self.balance, hours)
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
            logger.info("Force skip next window")


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
