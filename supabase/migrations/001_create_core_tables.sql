-- ============================================
-- Migration 1: Core Tables
-- trades, bot_state, levels, commands
-- ============================================

-- Trade log (bot pushes after every trade)
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    window_ts BIGINT NOT NULL,
    asset VARCHAR(10) NOT NULL,
    direction VARCHAR(4) NOT NULL,
    trade_type VARCHAR(10) NOT NULL DEFAULT 'SNIPE',
    token_price DECIMAL(10,4) NOT NULL,
    bet_size DECIMAL(10,4) NOT NULL,
    kelly_fraction DECIMAL(10,6),
    signal_score DECIMAL(10,4),
    regime VARCHAR(20),
    result VARCHAR(4) NOT NULL,
    balance_before DECIMAL(12,4) NOT NULL,
    balance_after DECIMAL(12,4) NOT NULL,
    pnl DECIMAL(10,4),
    payout_ratio DECIMAL(10,4),
    brier_rolling DECIMAL(10,6),
    win_rate_rolling DECIMAL(10,6),
    execution_type VARCHAR(10),
    whale_aligned BOOLEAN DEFAULT FALSE,
    whale_count INTEGER DEFAULT 0,
    reversal_counter_move_pct DECIMAL(10,6),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for dashboard queries
CREATE INDEX idx_trades_timestamp ON trades(timestamp DESC);
CREATE INDEX idx_trades_asset_timestamp ON trades(asset, timestamp DESC);
CREATE INDEX idx_trades_trade_type ON trades(trade_type);

-- Bot state (singleton row, id=1)
CREATE TABLE bot_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    current_balance DECIMAL(12,4),
    current_level INTEGER DEFAULT 1,
    level_target DECIMAL(12,4) DEFAULT 40.00,
    peak_balance DECIMAL(12,4),
    today_starting_balance DECIMAL(12,4),
    total_trades INTEGER DEFAULT 0,
    total_wins INTEGER DEFAULT 0,
    win_rate DECIMAL(10,6),
    brier_score DECIMAL(10,6),
    current_regime VARCHAR(20),
    kelly_alpha DECIMAL(10,4),
    consecutive_losses INTEGER DEFAULT 0,
    last_trade_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Level history (for the content challenge tracker)
CREATE TABLE levels (
    id SERIAL PRIMARY KEY,
    level INTEGER NOT NULL,
    target DECIMAL(12,4) NOT NULL,
    reached_at TIMESTAMPTZ,
    trades_taken INTEGER,
    time_elapsed_hours DECIMAL(10,2)
);

CREATE INDEX idx_levels_level ON levels(level);

-- Admin commands (dashboard writes, bot reads)
CREATE TABLE commands (
    id SERIAL PRIMARY KEY,
    command VARCHAR(50) NOT NULL,
    payload JSONB,
    executed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_commands_pending ON commands(executed, created_at) WHERE executed = FALSE;
