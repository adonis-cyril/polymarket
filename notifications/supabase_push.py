"""
Push trade events and bot state to Supabase for the dashboard.

Syncs data from SQLite to the Supabase tables that the Next.js dashboard
reads. Uses the service key to bypass RLS.

Handles Supabase unavailability gracefully — the bot continues trading
even if sync fails. Unsynced trades are retried on the next cycle.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

# Lazy-loaded client
_client = None


def _get_client():
    """Get Supabase client, lazy-loaded."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            logger.warning("Supabase credentials not configured, sync disabled")
            return None
        try:
            from supabase import create_client
            _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            logger.error("Failed to create Supabase client: %s", e)
            return None
    return _client


def push_trade(trade: dict) -> bool:
    """
    Push a single trade to Supabase.

    Args:
        trade: Trade dict from SQLite (data/db.py format).

    Returns:
        True if successful.
    """
    client = _get_client()
    if not client:
        return False

    try:
        row = {
            "window_ts": trade["window_ts"],
            "asset": trade["asset"],
            "direction": trade["direction"],
            "trade_type": trade["trade_type"],
            "token_price": trade["token_price"],
            "bet_size": trade["bet_size"],
            "kelly_fraction": trade.get("kelly_fraction"),
            "signal_score": trade.get("signal_score"),
            "regime": trade.get("regime"),
            "result": trade["result"],
            "balance_before": trade["balance_before"],
            "balance_after": trade["balance_after"],
            "pnl": trade.get("pnl"),
            "payout_ratio": trade.get("payout_ratio"),
            "brier_rolling": trade.get("brier_rolling"),
            "win_rate_rolling": trade.get("win_rate_rolling"),
            "execution_type": trade.get("execution_type", "PAPER"),
            "whale_aligned": bool(trade.get("whale_aligned", False)),
            "whale_count": trade.get("whale_count", 0),
            "reversal_counter_move_pct": trade.get("reversal_counter_move_pct"),
            "exit_reason": trade.get("exit_reason"),
            "entry_price": trade.get("entry_price"),
            "exit_price": trade.get("exit_price"),
            "hold_duration_seconds": trade.get("hold_duration_seconds"),
            "return_pct": trade.get("return_pct"),
        }

        client.table("trades").insert(row).execute()
        return True
    except Exception as e:
        logger.error("Failed to push trade to Supabase: %s", e)
        return False


def push_bot_state(
    status: str,
    balance: float,
    level: int,
    level_target: float,
    peak: float,
    today_start: float,
    total_trades: int,
    total_wins: int,
    win_rate: float,
    brier_score: float,
    regime: str,
    kelly_alpha: float,
    consecutive_losses: int,
    current_phase: int = 1,
) -> bool:
    """Push bot state update to Supabase."""
    client = _get_client()
    if not client:
        return False

    try:
        data = {
            "id": 1,
            "status": status,
            "current_balance": round(balance, 4),
            "current_level": level,
            "level_target": round(level_target, 4),
            "peak_balance": round(peak, 4),
            "today_starting_balance": round(today_start, 4),
            "total_trades": total_trades,
            "total_wins": total_wins,
            "win_rate": round(win_rate, 6),
            "brier_score": round(brier_score, 6),
            "current_regime": regime,
            "kelly_alpha": round(kelly_alpha, 4),
            "consecutive_losses": consecutive_losses,
            "current_phase": current_phase,
            "last_trade_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        client.table("bot_state").upsert(data).execute()
        return True
    except Exception as e:
        logger.error("Failed to push bot state to Supabase: %s", e)
        return False


def push_level_reached(level: int, target: float, trades_taken: int, hours_elapsed: float) -> bool:
    """Record a level milestone in Supabase."""
    client = _get_client()
    if not client:
        return False

    try:
        client.table("levels").update({
            "reached_at": datetime.now(timezone.utc).isoformat(),
            "trades_taken": trades_taken,
            "time_elapsed_hours": round(hours_elapsed, 2),
        }).eq("level", level).execute()
        return True
    except Exception as e:
        logger.error("Failed to push level to Supabase: %s", e)
        return False


def sync_unsynced_trades(db_module) -> int:
    """
    Sync all unsynced trades from SQLite to Supabase.

    Args:
        db_module: The data.db module (to avoid circular imports).

    Returns:
        Number of trades successfully synced.
    """
    unsynced = db_module.get_unsynced_trades()
    if not unsynced:
        return 0

    synced_ids = []
    for trade in unsynced:
        if push_trade(trade):
            synced_ids.append(trade["id"])

    if synced_ids:
        db_module.mark_trades_synced(synced_ids)
        logger.info("Synced %d/%d trades to Supabase", len(synced_ids), len(unsynced))

    return len(synced_ids)


def check_commands() -> list[dict]:
    """
    Check for unexecuted admin commands from the dashboard.

    Returns list of command dicts. Marks them as executed.
    """
    client = _get_client()
    if not client:
        return []

    try:
        result = (
            client.table("commands")
            .select("*")
            .eq("executed", False)
            .order("created_at")
            .execute()
        )

        commands = result.data or []

        # Mark as executed
        for cmd in commands:
            client.table("commands").update(
                {"executed": True}
            ).eq("id", cmd["id"]).execute()

        return commands
    except Exception as e:
        logger.error("Failed to check commands: %s", e)
        return []
