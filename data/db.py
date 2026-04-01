"""
SQLite local storage + Supabase sync for trade logging.

SQLite serves as the local source of truth for all trade data and bot state.
Supabase sync pushes data for the dashboard. If Supabase is unavailable,
the bot continues operating from SQLite alone.
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "bot_data.db"


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode for concurrent access."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Initialize SQLite tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            window_ts INTEGER NOT NULL,
            asset TEXT NOT NULL,
            direction TEXT NOT NULL,
            trade_type TEXT NOT NULL DEFAULT 'SNIPE',
            token_price REAL NOT NULL,
            bet_size REAL NOT NULL,
            kelly_fraction REAL,
            signal_score REAL,
            regime TEXT,
            result TEXT NOT NULL,
            balance_before REAL NOT NULL,
            balance_after REAL NOT NULL,
            pnl REAL,
            payout_ratio REAL,
            brier_rolling REAL,
            win_rate_rolling REAL,
            execution_type TEXT,
            whale_aligned INTEGER DEFAULT 0,
            whale_count INTEGER DEFAULT 0,
            reversal_counter_move_pct REAL,
            exit_reason TEXT,
            entry_price REAL,
            exit_price REAL,
            hold_duration_seconds INTEGER,
            return_pct REAL,
            fee_rate REAL,
            fees_paid REAL,
            net_profit_after_fees REAL,
            num_entries_this_window INTEGER DEFAULT 1,
            synced_to_supabase INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS bot_state (
            id INTEGER PRIMARY KEY DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'STOPPED',
            current_balance REAL,
            current_level INTEGER DEFAULT 1,
            level_target REAL DEFAULT 40.00,
            peak_balance REAL,
            today_starting_balance REAL,
            total_trades INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            win_rate REAL,
            brier_score REAL,
            current_regime TEXT,
            kelly_alpha REAL,
            consecutive_losses INTEGER DEFAULT 0,
            last_trade_at REAL,
            updated_at REAL
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            win_prob REAL NOT NULL,
            actual_win INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS window_prices (
            asset TEXT NOT NULL,
            window_ts INTEGER NOT NULL,
            open_price REAL NOT NULL,
            PRIMARY KEY (asset, window_ts)
        );
    """)

    # Initialize bot state if empty
    cursor = conn.execute("SELECT COUNT(*) FROM bot_state")
    if cursor.fetchone()[0] == 0:
        conn.execute("""
            INSERT INTO bot_state (id, status, current_balance, peak_balance, today_starting_balance)
            VALUES (1, 'STOPPED', 20.00, 20.00, 20.00)
        """)

    conn.commit()
    conn.close()
    logger.info("SQLite database initialized at %s", DB_PATH)


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
    """Log a trade to SQLite. Returns the trade ID."""
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO trades (
            timestamp, window_ts, asset, direction, trade_type,
            token_price, bet_size, kelly_fraction, signal_score, regime,
            result, balance_before, balance_after, pnl, payout_ratio,
            brier_rolling, win_rate_rolling, execution_type,
            whale_aligned, whale_count, reversal_counter_move_pct,
            exit_reason, entry_price, exit_price, hold_duration_seconds, return_pct,
            fee_rate, fees_paid, net_profit_after_fees, num_entries_this_window
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        time.time(), window_ts, asset, direction, trade_type,
        token_price, bet_size, kelly_fraction, signal_score, regime,
        result, balance_before, balance_after, pnl, payout_ratio,
        brier_rolling, win_rate_rolling, execution_type,
        1 if whale_aligned else 0, whale_count, reversal_counter_move_pct,
        exit_reason, entry_price, exit_price, hold_duration_seconds, return_pct,
        fee_rate, fees_paid, net_profit_after_fees, num_entries_this_window,
    ))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def log_prediction(win_prob: float, actual_win: bool):
    """Log a prediction for Brier score tracking."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO predictions (timestamp, win_prob, actual_win) VALUES (?, ?, ?)",
        (time.time(), win_prob, 1 if actual_win else 0),
    )
    conn.commit()
    conn.close()


def get_rolling_brier(window: int = 50) -> float:
    """Calculate rolling Brier score over last N predictions."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT win_prob, actual_win FROM predictions ORDER BY id DESC LIMIT ?",
        (window,),
    ).fetchall()
    conn.close()

    if not rows:
        return 0.30  # Default

    total = sum((r["win_prob"] - r["actual_win"]) ** 2 for r in rows)
    return total / len(rows)


def get_rolling_win_rate(window: int = 50) -> float:
    """Calculate rolling win rate over last N trades."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT result FROM trades ORDER BY id DESC LIMIT ?",
        (window,),
    ).fetchall()
    conn.close()

    if not rows:
        return 0.5

    wins = sum(1 for r in rows if r["result"] == "WIN")
    return wins / len(rows)


def update_bot_state(**kwargs):
    """Update bot state with given fields."""
    conn = get_connection()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values())
    values.append(time.time())
    conn.execute(f"UPDATE bot_state SET {fields}, updated_at = ? WHERE id = 1", values)
    conn.commit()
    conn.close()


def get_bot_state() -> dict:
    """Get current bot state."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM bot_state WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else {}


def save_window_open_price(asset: str, window_ts: int, open_price: float):
    """Save the opening price for a window."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO window_prices (asset, window_ts, open_price) VALUES (?, ?, ?)",
        (asset, window_ts, open_price),
    )
    conn.commit()
    conn.close()


def get_window_open_price(asset: str, window_ts: int) -> Optional[float]:
    """Get the opening price for a window."""
    conn = get_connection()
    row = conn.execute(
        "SELECT open_price FROM window_prices WHERE asset = ? AND window_ts = ?",
        (asset, window_ts),
    ).fetchone()
    conn.close()
    return row["open_price"] if row else None


def get_unsynced_trades() -> list[dict]:
    """Get trades not yet synced to Supabase."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades WHERE synced_to_supabase = 0 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_trades_synced(trade_ids: list[int]):
    """Mark trades as synced to Supabase."""
    if not trade_ids:
        return
    conn = get_connection()
    placeholders = ",".join("?" * len(trade_ids))
    conn.execute(
        f"UPDATE trades SET synced_to_supabase = 1 WHERE id IN ({placeholders})",
        trade_ids,
    )
    conn.commit()
    conn.close()


def get_consecutive_losses() -> int:
    """Count consecutive losses from the most recent trade backwards."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT result FROM trades ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    count = 0
    for row in rows:
        if row["result"] == "LOSS":
            count += 1
        else:
            break
    return count


def get_today_starting_balance() -> float:
    """Get today's starting balance (first trade of the day or current balance)."""
    conn = get_connection()
    today_start = (int(time.time()) // 86400) * 86400
    row = conn.execute(
        "SELECT balance_before FROM trades WHERE timestamp >= ? ORDER BY id ASC LIMIT 1",
        (today_start,),
    ).fetchone()
    conn.close()

    if row:
        return row["balance_before"]

    state = get_bot_state()
    return state.get("current_balance", 20.0)
