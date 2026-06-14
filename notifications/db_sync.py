"""
Dashboard sync helpers: admin commands and level milestones.

Trade and bot_state writes go through data/db.py (PostgreSQL is the source of truth).
"""

import logging
from datetime import datetime, timezone

from data.pg import dict_cursor, get_connection

logger = logging.getLogger(__name__)


def push_level_reached(level: int, target: float, trades_taken: int, hours_elapsed: float) -> bool:
    try:
        with get_connection() as conn:
            cur = dict_cursor(conn)
            cur.execute(
                """
                UPDATE levels
                SET reached_at = %s, trades_taken = %s, time_elapsed_hours = %s
                WHERE level = %s
                """,
                (
                    datetime.now(timezone.utc),
                    trades_taken,
                    round(hours_elapsed, 2),
                    level,
                ),
            )
        return True
    except Exception as e:
        logger.error("Failed to update level %d: %s", level, e)
        return False


def check_commands() -> list[dict]:
    try:
        with get_connection() as conn:
            cur = dict_cursor(conn)
            cur.execute(
                """
                SELECT id, command, payload, executed, created_at
                FROM commands
                WHERE executed = FALSE
                ORDER BY created_at
                """
            )
            commands = [dict(row) for row in cur.fetchall()]

            for cmd in commands:
                cur.execute(
                    "UPDATE commands SET executed = TRUE WHERE id = %s",
                    (cmd["id"],),
                )

        return commands
    except Exception as e:
        logger.error("Failed to check commands: %s", e)
        return []
