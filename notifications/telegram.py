"""Telegram bot notifications via Bot API."""

import logging

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        resp = requests.post(
            _API_URL.format(token=TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if not resp.ok:
            logger.error("Telegram API error: %s", resp.text)
            return False
        return True
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)
        return False


def notify_bot_started(mode: str, balance: float) -> bool:
    return send_message(
        f"<b>Bot started</b>\nMode: {mode}\nBalance: ${balance:.2f}"
    )


def notify_bot_stopped(balance: float) -> bool:
    return send_message(f"<b>Bot stopped</b>\nBalance: ${balance:.2f}")


def notify_trade_exit(
    asset: str,
    direction: str,
    exit_reason: str,
    net_pnl: float,
    balance: float,
    result: str,
) -> bool:
    emoji = "✅" if result == "WIN" else "❌"
    sign = "+" if net_pnl >= 0 else ""
    return send_message(
        f"{emoji} <b>Trade exit</b>\n"
        f"{asset.upper()} {direction} — {exit_reason}\n"
        f"P&amp;L: {sign}${net_pnl:.2f}\n"
        f"Balance: ${balance:.2f}"
    )


def notify_level_up(level: int, balance: float, hours: float) -> bool:
    return send_message(
        f"🎯 <b>Level {level} reached!</b>\n"
        f"Balance: ${balance:.2f}\n"
        f"Time: {hours:.1f}h"
    )


def notify_paused(reason: str) -> bool:
    return send_message(f"⏸ <b>Bot paused</b>\n{reason}")


def notify_error(message: str) -> bool:
    return send_message(f"⚠️ <b>Error</b>\n{message}")
