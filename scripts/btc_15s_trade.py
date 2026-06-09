#!/usr/bin/env python3
"""One-shot: $1 UP on latest BTC-5min market, close after exactly 15s.

Uses the same execution paths as bot.py (place_buy_order / place_sell_order)
and market discovery as the live staircase harness.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from execution.market_discovery import get_current_window_ts, seconds_until_close
from execution.order import compute_buy_shares, place_buy_order, place_sell_order
from tests.live_staircase.helpers import (
    discover_btc_market,
    fetch_book,
    format_market_summary,
    get_token_balance,
    log_order_result,
    save_state,
    StaircaseState,
)
from tests.live_staircase.log import LOG, setup_logging

BET_SIZE = 1.0
HOLD_SECONDS = 15.0
SIDE = "up"


def main() -> int:
    setup_logging("INFO")

    window_ts = get_current_window_ts()
    market = discover_btc_market()
    if not market:
        LOG.error("Could not discover BTC 5m market")
        return 1

    if market.window_ts != window_ts:
        LOG.error(
            "Market window_ts=%d != current window %d — refusing stale market",
            market.window_ts,
            window_ts,
        )
        return 1

    close_dt = datetime.fromtimestamp(market.close_time, tz=timezone.utc)
    LOG.info("=== Latest BTC-5min market ===")
    LOG.info("\n%s", format_market_summary(market))
    LOG.info(
        "Verified latest: slug=%s condition_id=%s close_utc=%s secs_left=%.0f",
        market.slug,
        market.condition_id,
        close_dt.isoformat(),
        seconds_until_close(),
    )

    token_id = market.up_token_id
    book = fetch_book(token_id)
    best_ask = book.best_ask if book.best_ask < 1 else book.mid
    if best_ask <= 0:
        LOG.error("No valid ask price for UP token")
        return 1

    try:
        est_shares = compute_buy_shares(BET_SIZE, best_ask)
    except ValueError as exc:
        LOG.error("Refusing buy: %s", exc)
        return 1

    LOG.info(
        "Placing LIVE BUY UP $%.2f @ ask=%.3f (~%.2f shares)",
        BET_SIZE,
        best_ask,
        est_shares,
    )

    buy_result = place_buy_order(token_id, BET_SIZE, best_ask)
    log_order_result("BUY", buy_result)
    if not buy_result.success:
        return 1

    shares = buy_result.fill_size
    entry_price = buy_result.fill_price
    save_state(
        StaircaseState(
            asset="btc",
            side=SIDE,
            token_id=token_id,
            shares=shares,
            entry_price=entry_price,
            amount_usdc=BET_SIZE,
        )
    )

    shares = buy_result.fill_size
    for _ in range(10):
        pos_after_buy = get_token_balance(token_id)
        if pos_after_buy >= shares * 0.9:
            shares = pos_after_buy
            break
        time.sleep(0.5)
    LOG.info(
        "Position after buy: %.4f UP shares (token %s...) order_id=%s",
        pos_after_buy,
        token_id[:16],
        (buy_result.order_id or "")[:16],
    )

    LOG.info("Holding for exactly %.0f seconds...", HOLD_SECONDS)
    hold_start = time.monotonic()
    time.sleep(HOLD_SECONDS)
    hold_elapsed = time.monotonic() - hold_start
    LOG.info("Hold complete: %.2fs elapsed", hold_elapsed)

    # Re-verify we're still on the same window/market
    current = discover_btc_market()
    if not current or current.condition_id != market.condition_id:
        LOG.warning(
            "Window may have rolled — selling on original token %s...",
            token_id[:16],
        )

    sell_shares = get_token_balance(token_id)
    if sell_shares <= 0:
        sell_shares = shares
        LOG.warning("Token balance 0, using fill_size %.4f", shares)
    else:
        shares = sell_shares

    book = fetch_book(token_id)
    target = book.best_bid if book.best_bid > 0 else book.mid
    LOG.info(
        "Placing LIVE URGENT SELL %.2f shares @ target=%.3f (bid=%.3f)",
        shares,
        target,
        book.best_bid,
    )

    sell_result = place_sell_order(token_id, shares, target, urgent=True)
    log_order_result("SELL", sell_result)
    if not sell_result.success:
        return 1

    time.sleep(2)
    pos_after_sell = get_token_balance(token_id)
    LOG.info(
        "Position after sell: %.2f UP shares order_id=%s",
        pos_after_sell,
        (sell_result.order_id or "")[:16],
    )

    if pos_after_sell > 0.01:
        LOG.error("Close incomplete — %.2f shares remain", pos_after_sell)
        return 1

    LOG.info(
        "SUCCESS: $%.2f UP opened @ $%.3f, held %.1fs, closed @ $%.3f",
        BET_SIZE,
        entry_price,
        hold_elapsed,
        sell_result.fill_price,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
