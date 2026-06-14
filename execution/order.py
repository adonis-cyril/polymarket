"""
Live order execution via Polymarket CLOB API.

Maker-first strategy:
1. Post limit order at best_ask - $0.01 (captures maker rebate)
2. Wait up to 3 seconds for fill
3. If unfilled, cancel and send FAK market order at best_ask

For sells (active management exits):
1. Post limit sell at target price
2. If urgent (stop loss, time stop), send FAK market sell immediately

Uses py-clob-client SDK for order signing and submission.
"""

import logging
import time
from typing import Optional
from dataclasses import dataclass

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from config import (
    POLY_PRIVATE_KEY, POLY_FUNDER_ADDRESS, POLY_SIGNATURE_TYPE,
    POLY_CLOB_URL, POLY_CHAIN_ID,
)

logger = logging.getLogger(__name__)

MAKER_WAIT_SECONDS = 3.0
MAKER_PRICE_OFFSET = 0.01  # Post $0.01 below best ask for maker rebate


@dataclass
class OrderResult:
    """Result of an order execution attempt."""
    success: bool
    order_id: str = ""
    fill_price: float = 0.0
    fill_size: float = 0.0
    execution_type: str = ""  # MAKER or TAKER
    error: str = ""


_client: Optional[ClobClient] = None
_v2_client = None
MIN_SHARES = 5.0


def _uses_deposit_wallet() -> bool:
    """POLY_1271 deposit-wallet flow requires py-clob-client-v2."""
    return POLY_SIGNATURE_TYPE == 3


def get_clob_client() -> ClobClient:
    """Get or create the CLOB client singleton."""
    global _client
    if _client is None:
        if not POLY_PRIVATE_KEY:
            raise RuntimeError("POLY_PRIVATE_KEY not set")

        # py-clob-client uses raw requests; bypass ISP DNS hijacks first
        from utils.polymarket_connectivity import install_dns_patch
        install_dns_patch()

        _client = ClobClient(
            POLY_CLOB_URL,
            key=POLY_PRIVATE_KEY,
            chain_id=POLY_CHAIN_ID,
            signature_type=POLY_SIGNATURE_TYPE,
            funder=POLY_FUNDER_ADDRESS,
        )

        # Derive API credentials from private key (always fresh)
        _client.set_api_creds(_client.create_or_derive_api_creds())

        logger.info("CLOB client initialized for %s", POLY_FUNDER_ADDRESS[:10])

    return _client


def _get_v2_client():
    """CLOB client for deposit-wallet (signature_type=3) accounts."""
    global _v2_client
    if _v2_client is None:
        from py_clob_client_v2.client import ClobClient as ClobClientV2
        from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType

        v1 = get_clob_client()
        _v2_client = ClobClientV2(
            POLY_CLOB_URL,
            chain_id=POLY_CHAIN_ID,
            key=POLY_PRIVATE_KEY,
            signature_type=POLY_SIGNATURE_TYPE,
            funder=POLY_FUNDER_ADDRESS,
            creds=v1.creds,
        )
        try:
            _v2_client.update_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL),
            )
        except Exception as exc:
            logger.warning("Deposit-wallet allowance sync failed: %s", exc)
        logger.info("CLOB v2 client initialized for deposit wallet %s", POLY_FUNDER_ADDRESS[:10])
    return _v2_client


def compute_buy_shares(amount_usdc: float, best_ask: float) -> float:
    """
    Size a buy to stay within ``amount_usdc``.

    Polymarket requires at least MIN_SHARES. If the minimum would exceed the
    budget at the current ask, raises ValueError instead of oversizing.
    """
    price = round(best_ask, 2)
    if price <= 0:
        raise ValueError(f"Invalid ask price: {best_ask}")

    shares = round(amount_usdc / price, 2)
    if shares < MIN_SHARES:
        min_notional = round(MIN_SHARES * price, 2)
        if min_notional > amount_usdc:
            raise ValueError(
                f"Cannot buy within ${amount_usdc:.2f}: Polymarket minimum is "
                f"{MIN_SHARES:.0f} shares, which costs ${min_notional:.2f} at "
                f"${price:.2f} ask"
            )
        shares = MIN_SHARES

    notional = round(shares * price, 2)
    if notional > amount_usdc:
        raise ValueError(
            f"Order notional ${notional:.2f} exceeds ${amount_usdc:.2f} budget "
            f"({shares:.2f} shares @ ${price:.2f})"
        )
    return shares


def get_fee_rate() -> float:
    """Query current fee rate from CLOB API."""
    try:
        client = get_clob_client()
        # The py-clob-client doesn't have a direct fee-rate method,
        # so we check via the order book or use the default
        # Polymarket maker fee: 0% (maker rebate), taker fee: ~0.5-1%
        return 0.005  # 0.5% conservative estimate
    except Exception as e:
        logger.warning("Failed to query fee rate: %s, using default", e)
        return 0.005


def place_buy_order(
    token_id: str,
    amount_usdc: float,
    best_ask: float,
) -> OrderResult:
    """
    Place a buy order using maker-first strategy.

    1. Post GTC limit order at best_ask - $0.01
    2. Wait MAKER_WAIT_SECONDS for fill
    3. If unfilled, cancel and send FAK at best_ask
    """
    try:
        max_shares = compute_buy_shares(amount_usdc, best_ask)
    except ValueError as exc:
        logger.error("Buy rejected: %s", exc)
        return OrderResult(success=False, error=str(exc))

    if _uses_deposit_wallet():
        return _place_buy_order_v2(token_id, amount_usdc, best_ask, max_shares)

    client = get_clob_client()

    # Calculate shares (cap at budget-validated size)
    maker_price = round(best_ask - MAKER_PRICE_OFFSET, 2)
    maker_price = max(maker_price, 0.01)
    shares = min(amount_usdc / maker_price, max_shares)

    logger.info(
        "BUY: posting maker limit at $%.2f for %.1f shares ($%.2f)",
        maker_price, shares, amount_usdc,
    )

    # Step 1: Maker limit order (GTC)
    try:
        order_args = OrderArgs(
            price=maker_price,
            size=round(shares, 2),
            side=BUY,
            token_id=token_id,
        )
        signed_order = client.create_order(order_args)
        response = client.post_order(signed_order, OrderType.GTC)

        order_id = response.get("orderID", "")
        if not order_id:
            logger.warning("No order ID returned: %s", response)
            # Fall through to taker
        else:
            # Step 2: Wait for fill
            fill = _wait_for_fill(client, order_id, MAKER_WAIT_SECONDS)
            if fill:
                logger.info("MAKER fill: %s at $%.2f", order_id[:8], maker_price)
                return OrderResult(
                    success=True, order_id=order_id,
                    fill_price=maker_price, fill_size=shares,
                    execution_type="MAKER",
                )

            # Step 3: Cancel unfilled maker order
            try:
                client.cancel(order_id)
                logger.info("Cancelled unfilled maker order %s", order_id[:8])
            except Exception:
                pass

    except Exception as e:
        logger.warning("Maker order failed: %s", e)

    # Step 3: FAK market order at best_ask
    logger.info("Falling back to FAK at $%.2f", best_ask)
    try:
        taker_shares = max_shares
        order_args = OrderArgs(
            price=best_ask,
            size=round(taker_shares, 2),
            side=BUY,
            token_id=token_id,
        )
        signed_order = client.create_order(order_args)
        response = client.post_order(signed_order, OrderType.FAK)

        order_id = response.get("orderID", "")
        logger.info("FAK order placed: %s", order_id[:8] if order_id else "no ID")

        return OrderResult(
            success=True, order_id=order_id,
            fill_price=best_ask, fill_size=taker_shares,
            execution_type="TAKER",
        )

    except Exception as e:
        logger.error("FAK order failed: %s", e)
        return OrderResult(success=False, error=str(e))


def place_sell_order(
    token_id: str,
    shares: float,
    target_price: float,
    urgent: bool = False,
) -> OrderResult:
    """
    Place a sell order.

    If urgent (stop loss, time stop): FAK market sell immediately.
    If not urgent (take profit): GTC limit sell at target price.
    """
    if _uses_deposit_wallet():
        return _place_sell_order_v2(token_id, shares, target_price, urgent)

    client = get_clob_client()

    if urgent:
        # Immediate market sell via FAK
        logger.info("URGENT SELL: FAK at $%.2f for %.1f shares", target_price, shares)
        try:
            order_args = OrderArgs(
                price=round(target_price, 2),
                size=round(shares, 2),
                side=SELL,
                token_id=token_id,
            )
            signed_order = client.create_order(order_args)
            response = client.post_order(signed_order, OrderType.FAK)
            order_id = response.get("orderID", "")

            return OrderResult(
                success=True, order_id=order_id,
                fill_price=target_price, fill_size=shares,
                execution_type="TAKER",
            )
        except Exception as e:
            logger.error("Urgent sell failed: %s", e)
            return OrderResult(success=False, error=str(e))
    else:
        # Limit sell at target price (GTC)
        logger.info("SELL: limit at $%.2f for %.1f shares", target_price, shares)
        try:
            order_args = OrderArgs(
                price=round(target_price, 2),
                size=round(shares, 2),
                side=SELL,
                token_id=token_id,
            )
            signed_order = client.create_order(order_args)
            response = client.post_order(signed_order, OrderType.GTC)
            order_id = response.get("orderID", "")

            # Wait briefly for fill
            fill = _wait_for_fill(client, order_id, 2.0)
            if fill:
                return OrderResult(
                    success=True, order_id=order_id,
                    fill_price=target_price, fill_size=shares,
                    execution_type="MAKER",
                )

            # If not filled, cancel and sell at market
            try:
                client.cancel(order_id)
            except Exception:
                pass

            # FAK fallback
            order_args = OrderArgs(
                price=round(target_price * 0.98, 2),  # Accept 2% slippage
                size=round(shares, 2),
                side=SELL,
                token_id=token_id,
            )
            signed_order = client.create_order(order_args)
            response = client.post_order(signed_order, OrderType.FAK)
            order_id = response.get("orderID", "")

            return OrderResult(
                success=True, order_id=order_id,
                fill_price=target_price * 0.98, fill_size=shares,
                execution_type="TAKER",
            )

        except Exception as e:
            logger.error("Sell order failed: %s", e)
            return OrderResult(success=False, error=str(e))


def _place_buy_order_v2(
    token_id: str,
    amount_usdc: float,
    best_ask: float,
    shares: float,
) -> OrderResult:
    """Deposit-wallet buy: FAK limit at best ask (min 5 shares)."""
    from py_clob_client_v2.clob_types import OrderArgsV2, OrderType as OrderTypeV2

    client = _get_v2_client()
    price = round(best_ask, 2)
    notional = round(shares * price, 2)

    logger.info(
        "BUY (v2): FAK %.2f shares @ $%.2f (~$%.2f, requested $%.2f)",
        shares, price, notional, amount_usdc,
    )

    try:
        order_args = OrderArgsV2(
            price=price,
            size=shares,
            side="BUY",
            token_id=token_id,
        )
        signed_order = client.create_order(order_args)
        response = client.post_order(signed_order, OrderTypeV2.FAK)
        order_id = response.get("orderID", response.get("id", ""))
        return OrderResult(
            success=True,
            order_id=order_id,
            fill_price=price,
            fill_size=shares,
            execution_type="TAKER",
        )
    except Exception as exc:
        logger.error("v2 buy failed: %s", exc)
        return OrderResult(success=False, error=str(exc))


def _place_sell_order_v2(
    token_id: str,
    shares: float,
    target_price: float,
    urgent: bool,
) -> OrderResult:
    """Deposit-wallet sell."""
    from py_clob_client_v2.clob_types import OrderArgsV2, OrderType as OrderTypeV2

    client = _get_v2_client()
    price = round(target_price, 2)
    size = round(shares, 4)
    order_type = OrderTypeV2.FAK if urgent else OrderTypeV2.GTC
    label = "URGENT SELL" if urgent else "SELL"

    logger.info("%s (v2): %s %.2f shares @ $%.2f", label, order_type, size, price)

    try:
        order_args = OrderArgsV2(
            price=price,
            size=size,
            side="SELL",
            token_id=token_id,
        )
        signed_order = client.create_order(order_args)
        response = client.post_order(signed_order, order_type)
        order_id = response.get("orderID", response.get("id", ""))
        return OrderResult(
            success=True,
            order_id=order_id,
            fill_price=price,
            fill_size=size,
            execution_type="TAKER" if urgent else "MAKER",
        )
    except Exception as exc:
        logger.error("v2 sell failed: %s", exc)
        return OrderResult(success=False, error=str(exc))


def cancel_all_orders():
    """Cancel all open orders."""
    try:
        client = get_clob_client()
        client.cancel_all()
        logger.info("Cancelled all open orders")
    except Exception as e:
        logger.warning("Failed to cancel all orders: %s", e)


def _wait_for_fill(client: ClobClient, order_id: str, timeout: float) -> bool:
    """Poll for order fill within timeout seconds."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            order = client.get_order(order_id)
            status = order.get("status", "")
            if status == "MATCHED" or status == "FILLED":
                return True
            if status in ("CANCELLED", "EXPIRED"):
                return False
        except Exception:
            pass
        time.sleep(0.5)
    return False
