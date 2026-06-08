-- Local PostgreSQL schema (from supabase/migrations/, without RLS/realtime)

CREATE TABLE IF NOT EXISTS trades (
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
    exit_reason VARCHAR(30),
    entry_price DECIMAL(10,4),
    exit_price DECIMAL(10,4),
    hold_duration_seconds INTEGER,
    return_pct DECIMAL(10,4),
    fee_rate DECIMAL(10,6),
    fees_paid DECIMAL(10,4),
    net_profit_after_fees DECIMAL(10,4),
    num_entries_this_window INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trades_asset_timestamp ON trades(asset, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trades_trade_type ON trades(trade_type);

CREATE TABLE IF NOT EXISTS bot_state (
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
    current_phase INTEGER DEFAULT 1,
    last_trade_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS levels (
    id SERIAL PRIMARY KEY,
    level INTEGER NOT NULL,
    target DECIMAL(12,4) NOT NULL,
    reached_at TIMESTAMPTZ,
    trades_taken INTEGER,
    time_elapsed_hours DECIMAL(10,2)
);

CREATE INDEX IF NOT EXISTS idx_levels_level ON levels(level);

CREATE TABLE IF NOT EXISTS commands (
    id SERIAL PRIMARY KEY,
    command VARCHAR(50) NOT NULL,
    payload JSONB,
    executed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_commands_pending ON commands(executed, created_at) WHERE executed = FALSE;

CREATE TABLE IF NOT EXISTS tracked_wallets (
    id SERIAL PRIMARY KEY,
    address VARCHAR(42) NOT NULL UNIQUE,
    alias VARCHAR(100),
    total_trades INTEGER,
    win_rate DECIMAL(10,6),
    total_pnl DECIMAL(12,4),
    avg_entry_delta_pct DECIMAL(10,6),
    avg_entry_seconds_left INTEGER,
    avg_token_price_paid DECIMAL(10,4),
    preferred_assets TEXT[],
    entry_conditions JSONB,
    last_profiled_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tracked_wallets_active ON tracked_wallets(is_active) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS whale_trades (
    id SERIAL PRIMARY KEY,
    wallet_address VARCHAR(42) NOT NULL,
    window_ts BIGINT NOT NULL,
    asset VARCHAR(10) NOT NULL,
    direction VARCHAR(4) NOT NULL,
    token_price DECIMAL(10,4),
    bet_size DECIMAL(12,4),
    seconds_left INTEGER,
    btc_delta_pct DECIMAL(10,6),
    result VARCHAR(4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_whale_trades_wallet ON whale_trades(wallet_address);
CREATE INDEX IF NOT EXISTS idx_whale_trades_window ON whale_trades(window_ts);

CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    win_prob DECIMAL(10,6) NOT NULL,
    actual_win BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS window_prices (
    asset VARCHAR(10) NOT NULL,
    window_ts BIGINT NOT NULL,
    open_price DECIMAL(16,8) NOT NULL,
    PRIMARY KEY (asset, window_ts)
);

INSERT INTO bot_state (id, status, current_balance, current_level, level_target, peak_balance, today_starting_balance, current_phase)
VALUES (1, 'STOPPED', 20.00, 1, 40.00, 20.00, 20.00, 1)
ON CONFLICT (id) DO NOTHING;

INSERT INTO levels (level, target)
SELECT v.level, v.target
FROM (VALUES
    (1, 40.00),
    (2, 80.00),
    (3, 160.00),
    (4, 320.00),
    (5, 640.00),
    (6, 1280.00),
    (7, 2560.00),
    (8, 5120.00),
    (9, 10240.00)
) AS v(level, target)
WHERE NOT EXISTS (SELECT 1 FROM levels l WHERE l.level = v.level);
