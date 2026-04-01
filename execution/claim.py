"""
On-chain position claiming via the Polymarket Relayer API.

After a market resolves, positions are automatically claimable. The CLOB API
usually reflects this within 5-10 seconds, but if balance doesn't update,
we trigger an explicit claim via the Relayer API (gasless).

Relayer API: https://relayer.polymarket.com
Headers: RELAYER_API_KEY, RELAYER_API_KEY_ADDRESS
"""

import logging
from typing import Optional

import requests

from config import RELAYER_API_KEY, RELAYER_API_KEY_ADDRESS

logger = logging.getLogger(__name__)

RELAYER_URL = "https://relayer.polymarket.com"
REQUEST_TIMEOUT = 15


def claim_position(condition_id: str) -> bool:
    """
    Trigger on-chain claim for a resolved position via Relayer API.

    Args:
        condition_id: The market's condition ID.

    Returns:
        True if claim was submitted successfully.
    """
    if not RELAYER_API_KEY:
        logger.warning("Relayer API key not configured, cannot claim")
        return False

    headers = {
        "RELAYER_API_KEY": RELAYER_API_KEY,
        "RELAYER_API_KEY_ADDRESS": RELAYER_API_KEY_ADDRESS,
        "Content-Type": "application/json",
    }

    try:
        # Submit redeem transaction via relayer
        payload = {
            "type": "redeem",
            "conditionId": condition_id,
        }

        resp = requests.post(
            f"{RELAYER_URL}/submit-transaction",
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        tx_hash = data.get("transactionHash", "")
        logger.info("Claim submitted: condition=%s tx=%s", condition_id[:10], tx_hash[:10] if tx_hash else "pending")
        return True

    except requests.RequestException as e:
        logger.error("Failed to claim position %s: %s", condition_id[:10], e)
        return False


def get_transaction_status(tx_id: str) -> Optional[str]:
    """Check status of a relayer transaction."""
    if not RELAYER_API_KEY:
        return None

    headers = {
        "RELAYER_API_KEY": RELAYER_API_KEY,
        "RELAYER_API_KEY_ADDRESS": RELAYER_API_KEY_ADDRESS,
    }

    try:
        resp = requests.get(
            f"{RELAYER_URL}/transaction/{tx_id}",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("status", "unknown")
    except requests.RequestException as e:
        logger.warning("Failed to check tx status: %s", e)
        return None
