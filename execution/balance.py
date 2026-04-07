"""
Wallet USDC balance querying with retry and lag handling.

After a position resolves, the USDC balance takes 5-10 seconds to update
via the API. This module polls until the balance reflects the resolution,
with a 30-second timeout before triggering on-chain claim.
"""

import logging
import time

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

from execution.order import get_clob_client

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2.0
MAX_POLL_SECONDS = 30.0


def get_usdc_balance() -> float:
    """Get current USDC balance from the CLOB API."""
    try:
        client = get_clob_client()
        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
        )
        balance_info = client.get_balance_allowance(params)
        if isinstance(balance_info, dict):
            balance_str = balance_info.get("balance", "0")
            # Balance is in USDC atomic units (6 decimals)
            return float(balance_str) / 1e6
        return 0.0
    except Exception as e:
        logger.warning("Failed to query balance: %s", e)
        return 0.0


def wait_for_balance_update(
    expected_min: float,
    timeout: float = MAX_POLL_SECONDS,
) -> float:
    """
    Poll balance until it reaches expected_min or timeout.

    Used after resolution to wait for the API to reflect the resolved position.

    Args:
        expected_min: Minimum balance we expect after resolution.
        timeout: Maximum seconds to wait.

    Returns:
        Current balance. If timeout reached, returns whatever the balance is.
    """
    start = time.time()
    last_balance = 0.0

    while time.time() - start < timeout:
        balance = get_usdc_balance()
        last_balance = balance

        if balance >= expected_min:
            logger.info("Balance updated: $%.2f (expected >= $%.2f)", balance, expected_min)
            return balance

        logger.debug("Balance $%.2f, waiting for $%.2f...", balance, expected_min)
        time.sleep(POLL_INTERVAL)

    logger.warning(
        "Balance poll timed out after %.0fs: $%.2f (expected >= $%.2f)",
        timeout, last_balance, expected_min,
    )
    return last_balance


def get_positions() -> list[dict]:
    """Get current open positions."""
    try:
        client = get_clob_client()
        positions = client.get_positions()
        return positions if isinstance(positions, list) else []
    except Exception as e:
        logger.warning("Failed to query positions: %s", e)
        return []
