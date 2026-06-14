"""Staircase command implementations."""

from __future__ import annotations

import time

from execution.balance import get_usdc_balance
from execution.market_discovery import seconds_until_close
from execution.order import (
    cancel_all_orders,
    get_clob_client,
    place_buy_order,
    place_sell_order,
)
from tests.live_staircase.config import (
    STAIRCASE_DEFAULT_SIZE,
    STAIRCASE_LAST_MINUTE_MAX_SECS,
    STAIRCASE_LAST_MINUTE_MIN_SECS,
    STAIRCASE_SL_PCT,
    STAIRCASE_TP_PCT,
)
from tests.live_staircase.helpers import (
    RunContext,
    StaircaseState,
    confirm,
    discover_btc_market,
    fetch_account_snapshot,
    fetch_book,
    format_market_summary,
    get_open_orders,
    get_token_balance,
    load_state,
    log_account_snapshot,
    log_order_result,
    normalize_side,
    require_live,
    resolve_entry_price,
    resolve_shares,
    save_state,
    token_for_side,
)
from tests.live_staircase.log import LOG


def cmd_discover(ctx: RunContext) -> int:
    LOG.info("=== STAIR: discover ===")
    market = discover_btc_market()
    if not market:
        return 1
    LOG.info("\n%s", format_market_summary(market))
    return 0


def cmd_buy(ctx: RunContext) -> int:
    LOG.info("=== STAIR: buy ===")
    market = discover_btc_market()
    if not market:
        return 1

    side = normalize_side(ctx.side)
    token_id = token_for_side(market, side)
    book = fetch_book(token_id)
    best_ask = book.best_ask if book.best_ask < 1 else book.mid
    size = ctx.size or STAIRCASE_DEFAULT_SIZE
    est_shares = size / best_ask if best_ask > 0 else 0

    LOG.info(
        "Buy %s $%.2f (~%.2f shares) @ ask=%.3f | %ds left",
        side.upper(), size, est_shares, best_ask, int(seconds_until_close()),
    )

    if not require_live(ctx, f"buy {side.upper()} ${size:.2f}"):
        return 0

    if not confirm(ctx, f"Place LIVE buy {side.upper()} ${size:.2f}?"):
        LOG.info("Cancelled")
        return 0

    result = place_buy_order(token_id, size, best_ask)
    log_order_result("BUY", result)
    if not result.success:
        return 1

    save_state(StaircaseState(
        asset="btc",
        side=side,
        token_id=token_id,
        shares=result.fill_size,
        entry_price=result.fill_price,
        amount_usdc=size,
    ))
    return 0


def cmd_sell(ctx: RunContext, urgent: bool = False) -> int:
    LOG.info("=== STAIR: %s ===", "exit" if urgent else "sell")
    market = discover_btc_market()
    if not market:
        return 1

    side = normalize_side(ctx.side)
    token_id = token_for_side(market, side)
    book = fetch_book(token_id)
    target = book.best_bid if book.best_bid > 0 else book.mid

    try:
        shares = resolve_shares(ctx, token_id)
    except ValueError as exc:
        LOG.error("%s", exc)
        return 1

    label = "urgent exit" if urgent else "sell"
    LOG.info(
        "Sell %s %.2f shares @ target=%.3f (bid=%.3f)",
        side.upper(), shares, target, book.best_bid,
    )

    if not require_live(ctx, f"{label} {shares:.2f} shares"):
        return 0

    if not confirm(ctx, f"Place LIVE {label} for {shares:.2f} shares?"):
        LOG.info("Cancelled")
        return 0

    result = place_sell_order(token_id, shares, target, urgent=urgent)
    log_order_result("SELL", result)
    return 0 if result.success else 1


def cmd_take_profit(ctx: RunContext) -> int:
    LOG.info("=== STAIR: take-profit ===")
    market = discover_btc_market()
    if not market:
        return 1

    side = normalize_side(ctx.side)
    token_id = token_for_side(market, side)
    book = fetch_book(token_id)
    entry = resolve_entry_price(ctx, token_id, book.mid)
    tp_pct = ctx.tp_pct if ctx.tp_pct is not None else STAIRCASE_TP_PCT
    target = round(entry * (1 + tp_pct), 2)

    try:
        shares = resolve_shares(ctx, token_id)
    except ValueError as exc:
        LOG.error("%s", exc)
        return 1

    LOG.info(
        "TP %s entry=%.3f target=%.3f (+%.1f%%) shares=%.2f current=%.3f",
        side.upper(), entry, target, tp_pct * 100, shares, book.mid,
    )

    if not require_live(ctx, f"place TP limit @ ${target:.2f}"):
        return 0

    if not confirm(ctx, f"Place LIVE take-profit limit @ ${target:.2f}?"):
        LOG.info("Cancelled")
        return 0

    result = place_sell_order(token_id, shares, target, urgent=False)
    log_order_result("TAKE-PROFIT", result)
    return 0 if result.success else 1


def cmd_stop_loss(ctx: RunContext) -> int:
    LOG.info("=== STAIR: stop-loss ===")
    market = discover_btc_market()
    if not market:
        return 1

    side = normalize_side(ctx.side)
    token_id = token_for_side(market, side)
    book = fetch_book(token_id)
    entry = resolve_entry_price(ctx, token_id, book.mid)
    sl_pct = ctx.sl_pct if ctx.sl_pct is not None else STAIRCASE_SL_PCT
    sl_price = round(entry * (1 - sl_pct), 2)
    current = book.mid
    breached = current <= sl_price

    try:
        shares = resolve_shares(ctx, token_id)
    except ValueError as exc:
        LOG.error("%s", exc)
        return 1

    LOG.info(
        "SL %s entry=%.3f sl=%.3f (-%.1f%%) shares=%.2f current=%.3f breached=%s",
        side.upper(), entry, sl_price, sl_pct * 100, shares, current, breached,
    )

    if not require_live(ctx, "stop-loss sell"):
        return 0

    if breached:
        prompt = f"SL BREACHED — market sell {shares:.2f} shares @ ~${current:.3f}?"
        if not confirm(ctx, prompt):
            LOG.info("Cancelled")
            return 0
        result = place_sell_order(token_id, shares, book.best_bid or current, urgent=True)
    else:
        prompt = f"Place SL limit @ ${sl_price:.2f} (not breached yet)?"
        if not confirm(ctx, prompt):
            LOG.info("Cancelled")
            return 0
        result = place_sell_order(token_id, shares, sl_price, urgent=False)

    log_order_result("STOP-LOSS", result)
    return 0 if result.success else 1


def cmd_cancel(ctx: RunContext) -> int:
    LOG.info("=== STAIR: cancel ===")
    orders = get_open_orders()

    if ctx.order_id:
        LOG.info("Cancel single order: %s", ctx.order_id)
        if not require_live(ctx, f"cancel order {ctx.order_id[:12]}"):
            return 0
        if not confirm(ctx, f"Cancel order {ctx.order_id[:12]}...?"):
            return 0
        try:
            get_clob_client().cancel(ctx.order_id)
            LOG.info("Cancelled order %s", ctx.order_id[:12])
            return 0
        except Exception as exc:
            LOG.error("Cancel failed: %s", exc)
            return 1

    LOG.info("Open orders: %d", len(orders))
    for order in orders[:10]:
        oid = order.get("id") or order.get("orderID") or order.get("order_id", "")
        LOG.info(
            "  %s side=%s price=%s size=%s",
            str(oid)[:12],
            order.get("side", "?"),
            order.get("price", "?"),
            order.get("original_size") or order.get("size", "?"),
        )

    if not orders:
        LOG.info("Nothing to cancel")
        return 0

    if not require_live(ctx, "cancel all open orders"):
        return 0

    if not confirm(ctx, f"Cancel ALL {len(orders)} open orders?"):
        LOG.info("Cancelled")
        return 0

    cancel_all_orders()
    LOG.info("Cancelled all open orders")
    return 0


def cmd_last_minute(ctx: RunContext) -> int:
    LOG.info("=== STAIR: last-minute ===")
    secs = seconds_until_close()
    min_secs = ctx.min_secs or STAIRCASE_LAST_MINUTE_MIN_SECS
    max_secs = ctx.max_secs or STAIRCASE_LAST_MINUTE_MAX_SECS

    LOG.info("Window closes in %.0fs (snipe window: %.0f–%.0fs)", secs, min_secs, max_secs)

    if secs <= min_secs:
        LOG.warning("Too late — only %.0fs left (min %.0fs)", secs, min_secs)
        return 1
    if secs >= max_secs:
        LOG.warning("Too early — %.0fs left (max %.0fs for snipe)", secs, max_secs)
        return 1

    market = discover_btc_market()
    if not market:
        return 1

    side = normalize_side(ctx.side)
    token_id = token_for_side(market, side)
    book = fetch_book(token_id)
    best_ask = book.best_ask if book.best_ask < 1 else book.mid
    size = min(ctx.size or STAIRCASE_DEFAULT_SIZE, STAIRCASE_DEFAULT_SIZE)

    LOG.info(
        "Last-minute snipe: %s $%.2f @ %.3f with %.0fs left",
        side.upper(), size, best_ask, secs,
    )

    if not require_live(ctx, f"last-minute buy {side.upper()} ${size:.2f}"):
        return 0

    if not confirm(ctx, f"Snipe LIVE {side.upper()} ${size:.2f} with {secs:.0f}s left?"):
        LOG.info("Cancelled")
        return 0

    result = place_buy_order(token_id, size, best_ask)
    log_order_result("LAST-MINUTE BUY", result)
    if result.success:
        save_state(StaircaseState(
            asset="btc",
            side=side,
            token_id=token_id,
            shares=result.fill_size,
            entry_price=result.fill_price,
            amount_usdc=size,
        ))
    return 0 if result.success else 1


def cmd_account(ctx: RunContext) -> int:
    LOG.info("=== STAIR: account ===")

    if not require_live(ctx, "fetch account balance and CLOB details"):
        return 0

    market = discover_btc_market()
    try:
        snapshot = fetch_account_snapshot(market)
    except Exception as exc:
        LOG.error("Account fetch failed: %s", exc)
        return 1

    log_account_snapshot(snapshot)
    return 0


def cmd_status(ctx: RunContext) -> int:
    LOG.info("=== STAIR: status ===")
    market = discover_btc_market()
    if market:
        LOG.info("\n%s", format_market_summary(market))

    state = load_state()
    if state.token_id:
        LOG.info(
            "Saved state: %s %s shares=%.2f entry=%.3f",
            state.side.upper(), state.token_id[:12], state.shares, state.entry_price,
        )

    if ctx.live or ctx.yes:
        balance = get_usdc_balance()
        LOG.info("USDC balance: $%.2f", balance)

        orders = get_open_orders()
        LOG.info("Open orders: %d", len(orders))
        for order in orders[:10]:
            oid = order.get("id") or order.get("orderID") or ""
            LOG.info(
                "  %s side=%s price=%s status=%s",
                str(oid)[:12],
                order.get("side", "?"),
                order.get("price", "?"),
                order.get("status", "?"),
            )

        for label, tid in (
            ("UP", market.up_token_id if market else ""),
            ("DOWN", market.down_token_id if market else ""),
        ):
            if tid:
                bal = get_token_balance(tid)
                if bal > 0:
                    LOG.info("Position %s: %.2f shares (token %s...)", label, bal, tid[:12])
    else:
        LOG.info("Pass --live for balance/orders (needs CLOB auth)")

    return 0


def cmd_run_staircase(ctx: RunContext) -> int:
    LOG.info("=== STAIR: run-staircase ===")
    steps = [
        ("discover", lambda: cmd_discover(ctx)),
        ("status", lambda: cmd_status(ctx)),
        ("buy (dry-run preview)", lambda: _dry_buy_preview(ctx)),
    ]

    if ctx.live:
        steps.extend([
            ("buy (live)", lambda: cmd_buy(ctx)),
            ("status after buy", lambda: cmd_status(ctx)),
            ("take-profit preview", lambda: _dry_tp_preview(ctx)),
            ("stop-loss preview", lambda: _dry_sl_preview(ctx)),
        ])
        if confirm(ctx, "Run sell/exit stair now?"):
            steps.append(("sell", lambda: cmd_sell(ctx)))
        if confirm(ctx, "Run cancel stair?"):
            steps.append(("cancel", lambda: cmd_cancel(ctx)))
    else:
        LOG.info("Dry-run mode — live order stairs skipped. Re-run with --live.")

    for name, fn in steps:
        LOG.info("--- Step: %s ---", name)
        if not ctx.auto and not confirm(ctx, f"Run step '{name}'?"):
            LOG.info("Skipped remaining steps")
            break
        rc = fn()
        if rc != 0:
            LOG.error("Step '%s' failed (rc=%d)", name, rc)
            return rc
        time.sleep(0.5)

    LOG.info("Staircase complete")
    return 0


def _dry_buy_preview(ctx: RunContext) -> int:
    saved = ctx.live
    ctx.live = False
    rc = cmd_buy(ctx)
    ctx.live = saved
    return rc


def _dry_tp_preview(ctx: RunContext) -> int:
    saved = ctx.live
    ctx.live = False
    rc = cmd_take_profit(ctx)
    ctx.live = saved
    return rc


def _dry_sl_preview(ctx: RunContext) -> int:
    saved = ctx.live
    ctx.live = False
    rc = cmd_stop_loss(ctx)
    ctx.live = saved
    return rc
