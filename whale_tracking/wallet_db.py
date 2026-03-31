"""
Store and retrieve whale wallet profiles and trade history in Supabase.

This module bridges the profiler/pattern_extractor output with the
Supabase tracked_wallets and whale_trades tables. Used by:
- Profiler cron job: writes profiles after daily re-profiling
- Live monitor: reads tracked wallet addresses on startup
- Dashboard: reads wallet stats for the whale leaderboard
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY
from whale_tracking.pattern_extractor import WalletProfile, EntryCondition
from whale_tracking.profiler import WalletTrade

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    """Create a Supabase client using service key (bypasses RLS)."""
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _entry_conditions_to_json(conditions: list[EntryCondition]) -> list[dict]:
    """Serialize entry conditions for JSONB storage."""
    return [
        {
            "delta_min": ec.delta_min,
            "delta_max": ec.delta_max,
            "seconds_left_min": ec.seconds_left_min,
            "seconds_left_max": ec.seconds_left_max,
            "trade_count": ec.trade_count,
            "wins": ec.wins,
            "losses": ec.losses,
            "win_rate": round(ec.win_rate, 4),
        }
        for ec in conditions
    ]


def upsert_wallet_profile(profile: WalletProfile) -> bool:
    """
    Insert or update a wallet profile in the tracked_wallets table.

    Uses the address as the unique key for upsert.
    """
    client = _get_client()

    data = {
        "address": profile.address,
        "total_trades": profile.total_trades,
        "win_rate": round(profile.win_rate, 6),
        "total_pnl": round(profile.total_pnl, 4),
        "avg_entry_delta_pct": profile.avg_entry_delta_pct,
        "avg_entry_seconds_left": profile.avg_entry_seconds_left,
        "avg_token_price_paid": profile.avg_token_price_paid,
        "preferred_assets": profile.preferred_assets,
        "entry_conditions": _entry_conditions_to_json(profile.entry_conditions),
        "last_profiled_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
    }

    try:
        result = (
            client.table("tracked_wallets")
            .upsert(data, on_conflict="address")
            .execute()
        )
        logger.info("Upserted wallet profile: %s...", profile.address[:10])
        return True
    except Exception as e:
        logger.error("Failed to upsert wallet %s: %s", profile.address[:10], e)
        return False


def save_wallet_profiles(profiles: list[WalletProfile]) -> int:
    """
    Save multiple wallet profiles. Returns count of successful upserts.
    """
    success = 0
    for profile in profiles:
        if upsert_wallet_profile(profile):
            success += 1
    logger.info("Saved %d/%d wallet profiles", success, len(profiles))
    return success


def save_whale_trades(trades: list[WalletTrade]) -> int:
    """
    Batch insert whale trades into the whale_trades table.

    Inserts in batches of 100 to stay within API limits.
    """
    client = _get_client()
    batch_size = 100
    total_inserted = 0

    for i in range(0, len(trades), batch_size):
        batch = trades[i:i + batch_size]
        rows = [
            {
                "wallet_address": t.wallet_address,
                "window_ts": t.window_ts,
                "asset": t.asset,
                "direction": t.direction,
                "token_price": round(t.token_price, 4),
                "bet_size": round(t.bet_size, 4),
                "seconds_left": t.seconds_left,
                "btc_delta_pct": round(t.btc_delta_pct, 6),
                "result": t.outcome,
            }
            for t in batch
        ]

        try:
            client.table("whale_trades").insert(rows).execute()
            total_inserted += len(rows)
        except Exception as e:
            logger.error("Failed to insert whale trades batch %d: %s", i // batch_size, e)

    logger.info("Inserted %d/%d whale trades", total_inserted, len(trades))
    return total_inserted


def get_tracked_addresses() -> set[str]:
    """
    Load all active tracked wallet addresses from Supabase.

    Used by the live monitor on startup to know which wallets to watch.
    """
    client = _get_client()

    try:
        result = (
            client.table("tracked_wallets")
            .select("address")
            .eq("is_active", True)
            .execute()
        )
        addresses = {row["address"] for row in result.data}
        logger.info("Loaded %d tracked wallet addresses", len(addresses))
        return addresses
    except Exception as e:
        logger.error("Failed to load tracked addresses: %s", e)
        return set()


def get_wallet_profiles() -> list[dict]:
    """
    Load all active wallet profiles from Supabase.

    Returns raw dicts matching the tracked_wallets table schema.
    Used by the pattern signal scorer.
    """
    client = _get_client()

    try:
        result = (
            client.table("tracked_wallets")
            .select("*")
            .eq("is_active", True)
            .order("win_rate", desc=True)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.error("Failed to load wallet profiles: %s", e)
        return []


def deactivate_stale_wallets(days_inactive: int = 7) -> int:
    """
    Mark wallets as inactive if they haven't been profiled recently.

    Returns count of deactivated wallets.
    """
    client = _get_client()
    cutoff = datetime.now(timezone.utc)

    try:
        # Fetch wallets with stale profiles
        result = (
            client.table("tracked_wallets")
            .select("id, address, last_profiled_at")
            .eq("is_active", True)
            .execute()
        )

        stale_ids = []
        for row in result.data:
            profiled_at = row.get("last_profiled_at")
            if not profiled_at:
                stale_ids.append(row["id"])
                continue

            profiled_dt = datetime.fromisoformat(profiled_at.replace("Z", "+00:00"))
            age_days = (cutoff - profiled_dt).total_seconds() / 86400
            if age_days > days_inactive:
                stale_ids.append(row["id"])

        if stale_ids:
            client.table("tracked_wallets").update(
                {"is_active": False}
            ).in_("id", stale_ids).execute()

        logger.info("Deactivated %d stale wallets", len(stale_ids))
        return len(stale_ids)
    except Exception as e:
        logger.error("Failed to deactivate stale wallets: %s", e)
        return 0


def clear_old_whale_trades(days_to_keep: int = 90) -> int:
    """
    Delete whale trades older than days_to_keep to manage row budget.

    Returns count of deleted rows.
    """
    client = _get_client()
    cutoff = datetime.now(timezone.utc)
    cutoff_ts = int(cutoff.timestamp()) - (days_to_keep * 86400)

    try:
        result = (
            client.table("whale_trades")
            .delete()
            .lt("window_ts", cutoff_ts)
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.info("Deleted %d whale trades older than %d days", count, days_to_keep)
        return count
    except Exception as e:
        logger.error("Failed to clear old whale trades: %s", e)
        return 0
