"""Shared helpers for live staircase commands."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

from execution.market_discovery import (
    Market,
    discover_market,
    get_market_prices,
    seconds_until_close,
)
from tests.live_staircase.config import (
    STAIRCASE_DEFAULT_SIZE,
    STAIRCASE_STATE_FILE,
)
from config import POLY_FUNDER_ADDRESS, POLY_PRIVATE_KEY, POLY_SIGNATURE_TYPE
from tests.live_staircase.log import LOG
from utils.polymarket_connectivity import clob_get

_SIGNATURE_TYPE_LABELS = {
    0: "EOA",
    1: "POLY_PROXY",
    2: "GNOSIS_SAFE",
}


@dataclass
class BookSnapshot:
    token_id: str
    best_bid: float = 0.0
    best_ask: float = 1.0
    mid: float = 0.5


@dataclass
class StaircaseState:
    """Persisted context between manual stair steps."""
    asset: str = "btc"
    side: str = ""
    token_id: str = ""
    shares: float = 0.0
    entry_price: float = 0.0
    amount_usdc: float = 0.0
    updated_at: float = 0.0


@dataclass
class RunContext:
    live: bool = False
    yes: bool = False
    auto: bool = False
    size: float = field(default_factory=lambda: STAIRCASE_DEFAULT_SIZE)
    side: str = "up"
    shares: Optional[float] = None
    entry_price: Optional[float] = None
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    order_id: Optional[str] = None
    min_secs: float = 15.0
    max_secs: float = 60.0


def discover_btc_market() -> Optional[Market]:
    market = discover_market("btc")
    if not market:
        LOG.error("BTC 5m market not found for current window")
    return market


def normalize_side(side: str) -> str:
    s = side.strip().lower()
    if s not in ("up", "down"):
        raise ValueError(f"Invalid side '{side}' — use 'up' or 'down'")
    return s


def token_for_side(market: Market, side: str) -> str:
    side = normalize_side(side)
    return market.up_token_id if side == "up" else market.down_token_id


def fetch_book(token_id: str) -> BookSnapshot:
    """Fetch order book via public CLOB REST (no auth required)."""
    book = BookSnapshot(token_id=token_id)
    try:
        resp = clob_get("/book", params={"token_id": token_id})
        if resp.ok:
            data = resp.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if bids:
                book.best_bid = max(float(b["price"]) for b in bids)
            if asks:
                book.best_ask = min(float(a["price"]) for a in asks)
            if book.best_bid and book.best_ask:
                book.mid = (book.best_bid + book.best_ask) / 2
            return book
    except Exception as exc:
        LOG.warning("REST book fetch failed: %s", exc)

    try:
        from execution.order import get_clob_client

        summary = get_clob_client().get_order_book(token_id)
        bids = getattr(summary, "bids", None) or []
        asks = getattr(summary, "asks", None) or []
        if bids:
            book.best_bid = max(float(b.price) for b in bids)
        if asks:
            book.best_ask = min(float(a.price) for a in asks)
        if book.best_bid and book.best_ask:
            book.mid = (book.best_bid + book.best_ask) / 2
    except Exception as exc:
        LOG.warning("CLOB client book fetch failed: %s", exc)

    return book


def format_market_summary(market: Market) -> str:
    secs = seconds_until_close()
    prices = get_market_prices(market.condition_id) or {}
    up_book = fetch_book(market.up_token_id)
    down_book = fetch_book(market.down_token_id)

    lines = [
        f"asset=BTC slug={market.slug}",
        f"question={market.question or '(no question)'}",
        f"window_ts={market.window_ts} close_in={secs:.0f}s",
        f"condition_id={market.condition_id}",
        f"UP   token={market.up_token_id}",
        f"     gamma={prices.get('up_price', 'n/a')} book bid={up_book.best_bid:.3f} ask={up_book.best_ask:.3f}",
        f"DOWN token={market.down_token_id}",
        f"     gamma={prices.get('down_price', 'n/a')} book bid={down_book.best_bid:.3f} ask={down_book.best_ask:.3f}",
    ]
    return "\n".join(lines)


def require_live(ctx: RunContext, action: str) -> bool:
    if ctx.live:
        return True
    LOG.info("[DRY-RUN] Would %s — pass --live to execute", action)
    return False


def confirm(ctx: RunContext, prompt: str) -> bool:
    if ctx.auto or ctx.yes:
        LOG.info("Auto-confirmed: %s", prompt)
        return True
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except EOFError:
        LOG.warning("No TTY — use --yes or --auto to skip prompts")
        return False
    return answer in ("y", "yes")


def load_state() -> StaircaseState:
    path = Path(STAIRCASE_STATE_FILE)
    if not path.exists():
        return StaircaseState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return StaircaseState(**data)
    except Exception as exc:
        LOG.warning("Could not load state file: %s", exc)
        return StaircaseState()


def save_state(state: StaircaseState) -> None:
    path = Path(STAIRCASE_STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = time.time()
    path.write_text(json.dumps(state.__dict__, indent=2), encoding="utf-8")
    LOG.info("Saved staircase state to %s", path)


def resolve_shares(ctx: RunContext, token_id: str) -> float:
    if ctx.shares and ctx.shares > 0:
        return ctx.shares

    state = load_state()
    if state.token_id == token_id and state.shares > 0:
        LOG.info("Using shares from saved state: %.2f", state.shares)
        return state.shares

    balance = get_token_balance(token_id)
    if balance > 0:
        LOG.info("Using conditional token balance: %.2f shares", balance)
        return balance

    raise ValueError(
        "No shares found — pass --shares or run 'buy' first to save state"
    )


def resolve_entry_price(ctx: RunContext, token_id: str, fallback: float) -> float:
    if ctx.entry_price and ctx.entry_price > 0:
        return ctx.entry_price
    state = load_state()
    if state.token_id == token_id and state.entry_price > 0:
        return state.entry_price
    return fallback


def _atomic_to_units(raw) -> float:
    return float(raw or "0") / 1e6


def _balance_allowance(asset_type: AssetType, token_id: str | None = None) -> dict:
    """Fetch balance and allowance from CLOB (auth required)."""
    from execution.order import get_clob_client

    params = BalanceAllowanceParams(asset_type=asset_type)
    if token_id:
        params.token_id = token_id
    info = get_clob_client().get_balance_allowance(params)
    if not isinstance(info, dict):
        return {"balance": 0.0, "allowance": 0.0}
    return {
        "balance": _atomic_to_units(info.get("balance", "0")),
        "allowance": _atomic_to_units(info.get("allowance", "0")),
    }


def fetch_account_snapshot(market: Market | None = None) -> dict:
    """Collect authenticated CLOB account details."""
    from execution.order import get_clob_client

    client = get_clob_client()
    collateral = _balance_allowance(AssetType.COLLATERAL)
    orders = get_open_orders()

    closed_only = None
    try:
        raw = client.get_closed_only_mode()
        if isinstance(raw, dict):
            closed_only = raw.get("closed_only", raw.get("closedOnly"))
        else:
            closed_only = raw
    except Exception as exc:
        LOG.debug("closed_only_mode lookup failed: %s", exc)

    positions: list[dict] = []
    if market:
        for label, token_id in (
            ("UP", market.up_token_id),
            ("DOWN", market.down_token_id),
        ):
            info = _balance_allowance(AssetType.CONDITIONAL, token_id=token_id)
            if info["balance"] > 0 or info["allowance"] > 0:
                positions.append({
                    "side": label,
                    "token_id": token_id,
                    "shares": info["balance"],
                    "allowance": info["allowance"],
                })

    sig_label = _SIGNATURE_TYPE_LABELS.get(
        POLY_SIGNATURE_TYPE, f"type_{POLY_SIGNATURE_TYPE}",
    )

    return {
        "funder_address": POLY_FUNDER_ADDRESS,
        "signer_address": client.get_address(),
        "signature_type": POLY_SIGNATURE_TYPE,
        "signature_type_label": sig_label,
        "private_key_set": bool(POLY_PRIVATE_KEY),
        "collateral_address": client.get_collateral_address(),
        "usdc_balance": collateral["balance"],
        "usdc_allowance": collateral["allowance"],
        "closed_only_mode": closed_only,
        "open_orders_count": len(orders),
        "open_orders": orders[:10],
        "positions": positions,
    }


def log_account_snapshot(snapshot: dict) -> None:
    """Emit structured account lines to staircase logger."""
    LOG.info("Account config:")
    LOG.info("  funder_address=%s", snapshot["funder_address"] or "(not set)")
    LOG.info(
        "  signer_address=%s",
        snapshot.get("signer_address") or "(unknown)",
    )
    LOG.info(
        "  signature_type=%s (%s)",
        snapshot["signature_type"],
        snapshot["signature_type_label"],
    )
    LOG.info(
        "  private_key=%s",
        "set" if snapshot["private_key_set"] else "not set",
    )
    if snapshot.get("collateral_address"):
        LOG.info("  collateral_token=%s", snapshot["collateral_address"])

    LOG.info("USDC collateral:")
    LOG.info("  balance=$%.2f", snapshot["usdc_balance"])
    LOG.info("  allowance=$%.2f", snapshot["usdc_allowance"])

    if snapshot.get("closed_only_mode") is not None:
        LOG.info("  closed_only_mode=%s", snapshot["closed_only_mode"])

    LOG.info("Open orders: %d", snapshot["open_orders_count"])
    for order in snapshot.get("open_orders", []):
        oid = order.get("id") or order.get("orderID") or order.get("order_id", "")
        LOG.info(
            "  %s side=%s price=%s size=%s status=%s",
            str(oid)[:12],
            order.get("side", "?"),
            order.get("price", "?"),
            order.get("original_size") or order.get("size", "?"),
            order.get("status", "?"),
        )

    positions = snapshot.get("positions", [])
    if positions:
        LOG.info("Conditional positions:")
        for pos in positions:
            LOG.info(
                "  %s shares=%.2f allowance=%.2f token=%s...",
                pos["side"],
                pos["shares"],
                pos["allowance"],
                pos["token_id"][:12],
            )
    else:
        LOG.info("Conditional positions: none (current BTC window)")


def get_token_balance(token_id: str) -> float:
    try:
        from execution.order import get_clob_client

        client = get_clob_client()
        params = BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL,
            token_id=token_id,
        )
        info = client.get_balance_allowance(params)
        if isinstance(info, dict):
            return _atomic_to_units(info.get("balance", "0"))
    except Exception as exc:
        LOG.debug("Conditional balance lookup failed: %s", exc)
    return 0.0


def get_open_orders() -> list[dict]:
    try:
        from execution.order import get_clob_client

        orders = get_clob_client().get_orders()
        if isinstance(orders, list):
            return orders
        if isinstance(orders, dict):
            return orders.get("data", orders.get("orders", []))
    except Exception as exc:
        LOG.warning("Failed to fetch open orders: %s", exc)
    return []


def log_order_result(label: str, result) -> None:
    if result.success:
        LOG.info(
            "%s OK id=%s price=%.3f size=%.2f type=%s",
            label,
            (result.order_id or "")[:12],
            result.fill_price,
            result.fill_size,
            result.execution_type,
        )
    else:
        LOG.error("%s FAILED: %s", label, result.error)
