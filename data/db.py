"""
PostgreSQL storage for trade logging and bot state.

PostgreSQL is the single source of truth for trades, bot state, and dashboard data.
The bot requires a running PostgreSQL instance (see docker-compose.yml).
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from data.pg import dict_cursor, get_connection

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent.parent / "scripts" / "init_db.sql"


def init_db():
    """Initialize PostgreSQL tables if they don't exist."""
    sql = _SCHEMA_PATH.read_text()
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    statements = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]

    with get_connection() as conn:
        cur = conn.cursor()
        for stmt in statements:
            cur.execute(stmt)
    logger.info("PostgreSQL schema initialized")


def log_trade(
    window_ts: int,
    asset: str,
    direction: str,
    trade_type: str,
    token_price: float,
    bet_size: float,
    kelly_fraction: float,
    signal_score: float,
    regime: str,
    result: str,
    balance_before: float,
    balance_after: float,
    pnl: float,
    payout_ratio: float,
    brier_rolling: float,
    win_rate_rolling: float,
    execution_type: str = "PAPER",
    whale_aligned: bool = False,
    whale_count: int = 0,
    reversal_counter_move_pct: float = 0.0,
    exit_reason: str = "",
    entry_price: float = 0.0,
    exit_price: float = 0.0,
    hold_duration_seconds: int = 0,
    return_pct: float = 0.0,
    fee_rate: float = 0.0,
    fees_paid: float = 0.0,
    net_profit_after_fees: float = 0.0,
    num_entries_this_window: int = 1,
) -> int:
    """Log a trade. Returns the trade ID."""
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            """
            INSERT INTO trades (
                timestamp, window_ts, asset, direction, trade_type,
                token_price, bet_size, kelly_fraction, signal_score, regime,
                result, balance_before, balance_after, pnl, payout_ratio,
                brier_rolling, win_rate_rolling, execution_type,
                whale_aligned, whale_count, reversal_counter_move_pct,
                exit_reason, entry_price, exit_price, hold_duration_seconds, return_pct,
                fee_rate, fees_paid, net_profit_after_fees, num_entries_this_window
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            ) RETURNING id
            """,
            (
                datetime.now(timezone.utc), window_ts, asset, direction, trade_type,
                token_price, bet_size, kelly_fraction, signal_score, regime,
                result, balance_before, balance_after, pnl, payout_ratio,
                brier_rolling, win_rate_rolling, execution_type,
                whale_aligned, whale_count, reversal_counter_move_pct,
                exit_reason, entry_price, exit_price, hold_duration_seconds, return_pct,
                fee_rate, fees_paid, net_profit_after_fees, num_entries_this_window,
            ),
        )
        trade_id = cur.fetchone()["id"]
    return trade_id


def log_prediction(win_prob: float, actual_win: bool):
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            "INSERT INTO predictions (timestamp, win_prob, actual_win) VALUES (%s, %s, %s)",
            (datetime.now(timezone.utc), win_prob, actual_win),
        )


def get_rolling_brier(window: int = 50) -> float:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT win_prob, actual_win FROM predictions ORDER BY id DESC LIMIT %s",
            (window,),
        )
        rows = cur.fetchall()

    if not rows:
        return 0.30

    total = sum((float(r["win_prob"]) - (1 if r["actual_win"] else 0)) ** 2 for r in rows)
    return total / len(rows)


def get_rolling_win_rate(window: int = 50) -> float:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT result FROM trades ORDER BY id DESC LIMIT %s",
            (window,),
        )
        rows = cur.fetchall()

    if not rows:
        return 0.5

    wins = sum(1 for r in rows if r["result"] == "WIN")
    return wins / len(rows)


def update_bot_state(**kwargs):
    """Update bot state with given fields."""
    if not kwargs:
        return

    kwargs["updated_at"] = datetime.now(timezone.utc)
    fields = ", ".join(f"{k} = %s" for k in kwargs)
    values = list(kwargs.values())

    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(f"UPDATE bot_state SET {fields} WHERE id = 1", values)


def sync_bot_state(
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
):
    """Full bot_state upsert for dashboard sync."""
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            """
            INSERT INTO bot_state (
                id, status, current_balance, current_level, level_target,
                peak_balance, today_starting_balance, total_trades, total_wins,
                win_rate, brier_score, current_regime, kelly_alpha,
                consecutive_losses, current_phase, last_trade_at, updated_at
            ) VALUES (
                1, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                current_balance = EXCLUDED.current_balance,
                current_level = EXCLUDED.current_level,
                level_target = EXCLUDED.level_target,
                peak_balance = EXCLUDED.peak_balance,
                today_starting_balance = EXCLUDED.today_starting_balance,
                total_trades = EXCLUDED.total_trades,
                total_wins = EXCLUDED.total_wins,
                win_rate = EXCLUDED.win_rate,
                brier_score = EXCLUDED.brier_score,
                current_regime = EXCLUDED.current_regime,
                kelly_alpha = EXCLUDED.kelly_alpha,
                consecutive_losses = EXCLUDED.consecutive_losses,
                current_phase = EXCLUDED.current_phase,
                last_trade_at = EXCLUDED.last_trade_at,
                updated_at = EXCLUDED.updated_at
            """,
            (
                status, round(balance, 4), level, round(level_target, 4),
                round(peak, 4), round(today_start, 4), total_trades, total_wins,
                round(win_rate, 6), round(brier_score, 6), regime, round(kelly_alpha, 4),
                consecutive_losses, current_phase, now, now,
            ),
        )


_FLOAT_STATE_FIELDS = (
    "current_balance", "level_target", "peak_balance",
    "today_starting_balance", "win_rate", "brier_score", "kelly_alpha",
)


def get_bot_state() -> dict:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT * FROM bot_state WHERE id = 1")
        row = cur.fetchone()
    state = dict(row) if row else {}
    for field in _FLOAT_STATE_FIELDS:
        if field in state and state[field] is not None:
            state[field] = float(state[field])
    return state


def save_window_open_price(asset: str, window_ts: int, open_price: float):
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            """
            INSERT INTO window_prices (asset, window_ts, open_price)
            VALUES (%s, %s, %s)
            ON CONFLICT (asset, window_ts) DO UPDATE SET open_price = EXCLUDED.open_price
            """,
            (asset, window_ts, open_price),
        )


def get_window_open_price(asset: str, window_ts: int) -> Optional[float]:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT open_price FROM window_prices WHERE asset = %s AND window_ts = %s",
            (asset, window_ts),
        )
        row = cur.fetchone()
    return float(row["open_price"]) if row else None


def get_consecutive_losses() -> int:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT result FROM trades ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()

    count = 0
    for row in rows:
        if row["result"] == "LOSS":
            count += 1
        else:
            break
    return count


def get_today_starting_balance() -> float:
    today_start = (int(time.time()) // 86400) * 86400
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute(
            """
            SELECT balance_before FROM trades
            WHERE EXTRACT(EPOCH FROM timestamp) >= %s
            ORDER BY id ASC LIMIT 1
            """,
            (today_start,),
        )
        row = cur.fetchone()

    if row:
        return float(row["balance_before"])

    state = get_bot_state()
    return float(state.get("current_balance", 20.0))
