"""
Store and retrieve whale wallet profiles and trade history in PostgreSQL.
"""

import json
import logging
from datetime import datetime, timezone

from data.pg import dict_cursor, get_connection
from whale_tracking.pattern_extractor import WalletProfile, EntryCondition
from whale_tracking.profiler import WalletTrade

logger = logging.getLogger(__name__)


def _entry_conditions_to_json(conditions: list[EntryCondition]) -> list[dict]:
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
    data = {
        "address": profile.address,
        "total_trades": profile.total_trades,
        "win_rate": round(profile.win_rate, 6),
        "total_pnl": round(profile.total_pnl, 4),
        "avg_entry_delta_pct": profile.avg_entry_delta_pct,
        "avg_entry_seconds_left": profile.avg_entry_seconds_left,
        "avg_token_price_paid": profile.avg_token_price_paid,
        "preferred_assets": profile.preferred_assets,
        "entry_conditions": json.dumps(_entry_conditions_to_json(profile.entry_conditions)),
        "last_profiled_at": datetime.now(timezone.utc),
        "is_active": True,
    }

    try:
        with get_connection() as conn:
            cur = dict_cursor(conn)
            cur.execute(
                """
                INSERT INTO tracked_wallets (
                    address, total_trades, win_rate, total_pnl,
                    avg_entry_delta_pct, avg_entry_seconds_left, avg_token_price_paid,
                    preferred_assets, entry_conditions, last_profiled_at, is_active
                ) VALUES (
                    %(address)s, %(total_trades)s, %(win_rate)s, %(total_pnl)s,
                    %(avg_entry_delta_pct)s, %(avg_entry_seconds_left)s, %(avg_token_price_paid)s,
                    %(preferred_assets)s, %(entry_conditions)s::jsonb, %(last_profiled_at)s, %(is_active)s
                )
                ON CONFLICT (address) DO UPDATE SET
                    total_trades = EXCLUDED.total_trades,
                    win_rate = EXCLUDED.win_rate,
                    total_pnl = EXCLUDED.total_pnl,
                    avg_entry_delta_pct = EXCLUDED.avg_entry_delta_pct,
                    avg_entry_seconds_left = EXCLUDED.avg_entry_seconds_left,
                    avg_token_price_paid = EXCLUDED.avg_token_price_paid,
                    preferred_assets = EXCLUDED.preferred_assets,
                    entry_conditions = EXCLUDED.entry_conditions,
                    last_profiled_at = EXCLUDED.last_profiled_at,
                    is_active = EXCLUDED.is_active
                """,
                data,
            )
        logger.info("Upserted wallet profile: %s...", profile.address[:10])
        return True
    except Exception as e:
        logger.error("Failed to upsert wallet %s: %s", profile.address[:10], e)
        return False


def save_wallet_profiles(profiles: list[WalletProfile]) -> int:
    success = sum(1 for p in profiles if upsert_wallet_profile(p))
    logger.info("Saved %d/%d wallet profiles", success, len(profiles))
    return success


def save_whale_trades(trades: list[WalletTrade]) -> int:
    batch_size = 100
    total_inserted = 0

    for i in range(0, len(trades), batch_size):
        batch = trades[i:i + batch_size]
        rows = [
            (
                t.wallet_address,
                t.window_ts,
                t.asset,
                t.direction,
                round(t.token_price, 4),
                round(t.bet_size, 4),
                t.seconds_left,
                round(t.btc_delta_pct, 6),
                t.outcome,
            )
            for t in batch
        ]

        try:
            with get_connection() as conn:
                cur = dict_cursor(conn)
                cur.executemany(
                    """
                    INSERT INTO whale_trades (
                        wallet_address, window_ts, asset, direction,
                        token_price, bet_size, seconds_left, btc_delta_pct, result
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
            total_inserted += len(rows)
        except Exception as e:
            logger.error("Failed to insert whale trades batch %d: %s", i // batch_size, e)

    logger.info("Inserted %d/%d whale trades", total_inserted, len(trades))
    return total_inserted


def get_tracked_addresses() -> set[str]:
    try:
        with get_connection() as conn:
            cur = dict_cursor(conn)
            cur.execute(
                "SELECT address FROM tracked_wallets WHERE is_active = TRUE"
            )
            addresses = {row["address"] for row in cur.fetchall()}
        logger.info("Loaded %d tracked wallet addresses", len(addresses))
        return addresses
    except Exception as e:
        logger.error("Failed to load tracked addresses: %s", e)
        return set()


def get_wallet_profiles() -> list[dict]:
    try:
        with get_connection() as conn:
            cur = dict_cursor(conn)
            cur.execute(
                "SELECT * FROM tracked_wallets WHERE is_active = TRUE ORDER BY win_rate DESC"
            )
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error("Failed to load wallet profiles: %s", e)
        return []


def deactivate_stale_wallets(days_inactive: int = 7) -> int:
    cutoff = datetime.now(timezone.utc)

    try:
        with get_connection() as conn:
            cur = dict_cursor(conn)
            cur.execute(
                "SELECT id, address, last_profiled_at FROM tracked_wallets WHERE is_active = TRUE"
            )
            rows = cur.fetchall()

            stale_ids = []
            for row in rows:
                profiled_at = row.get("last_profiled_at")
                if not profiled_at:
                    stale_ids.append(row["id"])
                    continue

                if profiled_at.tzinfo is None:
                    profiled_at = profiled_at.replace(tzinfo=timezone.utc)
                age_days = (cutoff - profiled_at).total_seconds() / 86400
                if age_days > days_inactive:
                    stale_ids.append(row["id"])

            if stale_ids:
                cur.execute(
                    "UPDATE tracked_wallets SET is_active = FALSE WHERE id = ANY(%s)",
                    (stale_ids,),
                )

        logger.info("Deactivated %d stale wallets", len(stale_ids))
        return len(stale_ids)
    except Exception as e:
        logger.error("Failed to deactivate stale wallets: %s", e)
        return 0


def clear_old_whale_trades(days_to_keep: int = 90) -> int:
    cutoff_ts = int(datetime.now(timezone.utc).timestamp()) - (days_to_keep * 86400)

    try:
        with get_connection() as conn:
            cur = dict_cursor(conn)
            cur.execute(
                "DELETE FROM whale_trades WHERE window_ts < %s RETURNING id",
                (cutoff_ts,),
            )
            count = len(cur.fetchall())
        logger.info("Deleted %d whale trades older than %d days", count, days_to_keep)
        return count
    except Exception as e:
        logger.error("Failed to clear old whale trades: %s", e)
        return 0
