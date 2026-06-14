"""
PostgreSQL persistence for cached Polymarket active markets.

Used by data.market_registry to serve the full market list without
re-hitting Gamma on every consumer call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from data.market_types import ActiveMarketRecord
from data.pg import dict_cursor, get_connection

logger = logging.getLogger(__name__)

_UPSERT_SQL = """
INSERT INTO cached_markets (
    condition_id, event_id, event_slug, market_slug, question,
    outcomes, clob_token_ids, active, closed, end_date,
    volume_24hr, liquidity, gamma_updated_at, fetched_at, deactivated_at
) VALUES (
    %(condition_id)s, %(event_id)s, %(event_slug)s, %(market_slug)s, %(question)s,
    %(outcomes)s::jsonb, %(clob_token_ids)s::jsonb, %(active)s, %(closed)s, %(end_date)s,
    %(volume_24hr)s, %(liquidity)s, %(gamma_updated_at)s, %(fetched_at)s, NULL
)
ON CONFLICT (condition_id) DO UPDATE SET
    event_id = EXCLUDED.event_id,
    event_slug = EXCLUDED.event_slug,
    market_slug = EXCLUDED.market_slug,
    question = EXCLUDED.question,
    outcomes = EXCLUDED.outcomes,
    clob_token_ids = EXCLUDED.clob_token_ids,
    active = EXCLUDED.active,
    closed = EXCLUDED.closed,
    end_date = EXCLUDED.end_date,
    volume_24hr = EXCLUDED.volume_24hr,
    liquidity = EXCLUDED.liquidity,
    gamma_updated_at = EXCLUDED.gamma_updated_at,
    fetched_at = EXCLUDED.fetched_at,
    deactivated_at = NULL
"""


def get_cache_meta() -> dict:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT * FROM market_cache_meta WHERE id = 1")
        row = cur.fetchone()
    return dict(row) if row else {}


def update_cache_meta(
    *,
    last_full_sync_at: Optional[datetime] = None,
    last_sync_count: Optional[int] = None,
    sync_status: Optional[str] = None,
):
    now = datetime.now(timezone.utc)
    fields = ["updated_at = %s"]
    values: list = [now]

    if last_full_sync_at is not None:
        fields.append("last_full_sync_at = %s")
        values.append(last_full_sync_at)
    if last_sync_count is not None:
        fields.append("last_sync_count = %s")
        values.append(last_sync_count)
    if sync_status is not None:
        fields.append("sync_status = %s")
        values.append(sync_status)

    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            f"UPDATE market_cache_meta SET {', '.join(fields)} WHERE id = 1",
            values,
        )


def list_active_markets(
    *,
    event_slug_contains: str = "",
    limit: Optional[int] = None,
) -> list[ActiveMarketRecord]:
    clauses = ["active = TRUE", "closed = FALSE"]
    params: list = []

    if event_slug_contains:
        clauses.append("(event_slug ILIKE %s OR market_slug ILIKE %s)")
        pattern = f"%{event_slug_contains}%"
        params.extend([pattern, pattern])

    sql = (
        "SELECT * FROM cached_markets "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY volume_24hr DESC NULLS LAST, fetched_at DESC"
    )
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [ActiveMarketRecord.from_db_row(dict(row)) for row in rows]


def get_market_by_condition_id(condition_id: str) -> Optional[ActiveMarketRecord]:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT * FROM cached_markets WHERE condition_id = %s",
            (condition_id,),
        )
        row = cur.fetchone()
    return ActiveMarketRecord.from_db_row(dict(row)) if row else None


def upsert_markets(records: list[ActiveMarketRecord], *, fetched_at: Optional[datetime] = None) -> int:
    if not records:
        return 0

    fetched_at = fetched_at or datetime.now(timezone.utc)
    rows = []
    for record in records:
        row = record.to_db_row()
        row["fetched_at"] = fetched_at
        rows.append(row)

    with get_connection() as conn:
        cur = conn.cursor()
        for row in rows:
            cur.execute(_UPSERT_SQL, row)
    return len(rows)


def deactivate_missing(active_condition_ids: set[str], *, deactivated_at: Optional[datetime] = None) -> int:
    """Mark markets absent from the latest full sync as inactive."""
    deactivated_at = deactivated_at or datetime.now(timezone.utc)

    with get_connection() as conn:
        cur = dict_cursor(conn)
        if active_condition_ids:
            cur.execute(
                """
                UPDATE cached_markets
                SET active = FALSE, closed = TRUE, deactivated_at = %s
                WHERE active = TRUE
                  AND condition_id <> ALL(%s)
                RETURNING condition_id
                """,
                (deactivated_at, list(active_condition_ids)),
            )
        else:
            cur.execute(
                """
                UPDATE cached_markets
                SET active = FALSE, closed = TRUE, deactivated_at = %s
                WHERE active = TRUE
                RETURNING condition_id
                """,
                (deactivated_at,),
            )
        rows = cur.fetchall()

    count = len(rows)
    if count:
        logger.info("Deactivated %d stale cached markets", count)
    return count


def count_active_markets() -> int:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT COUNT(*) AS count FROM cached_markets WHERE active = TRUE AND closed = FALSE",
        )
        row = cur.fetchone()
    return int(row["count"]) if row else 0
