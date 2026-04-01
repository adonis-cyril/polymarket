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
    POLY_PRIVATE_KEY, POLY_API_KEY, POLY_API_SECRET,
    POLY_API_PASSPHRASE, POLY_FUNDER_ADDRESS, POLY_SIGNATURE_TYPE,
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


def get_clob_client() -> ClobClient:
    """Get or create the CLOB client singleton."""
    global _client
    if _client is None:
        if not POLY_PRIVATE_KEY:
            raise RuntimeError("POLY_PRIVATE_KEY not set")

        _client = ClobClient(
            POLY_CLOB_URL,
            key=POLY_PRIVATE_KEY,
            chain_id=POLY_CHAIN_ID,
            signature_type=POLY_SIGNATURE_TYPE,
            funder=POLY_FUNDER_ADDRESS,
        )

        # Set API credentials
        _client.set_api_creds(_client.create_or_derive_api_creds())

        if POLY_API_KEY:
            from py_clob_client.clob_types import ApiCreds
            _client.set_api_creds(ApiCreds(
                api_key=POLY_API_KEY,
                api_secret=POLY_API_SECRET,
                api_passphrase=POLY_API_PASSPHRASE,
            ))

        logger.info("CLOB client initialized for %s", POLY_FUNDER_ADDRESS[:10])

    return _client


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
    client = get_clob_client()

    # Calculate shares
    maker_price = round(best_ask - MAKER_PRICE_OFFSET, 2)
    maker_price = max(maker_price, 0.01)
    shares = amount_usdc / maker_price

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
        taker_shares = amount_usdc / best_ask
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
