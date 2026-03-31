-- ============================================
-- Migration 2: Whale Tracking Tables
-- tracked_wallets, whale_trades
-- ============================================

-- Tracked whale wallets
CREATE TABLE tracked_wallets (
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

CREATE INDEX idx_tracked_wallets_active ON tracked_wallets(is_active) WHERE is_active = TRUE;

-- Whale trade history (for pattern extraction)
CREATE TABLE whale_trades (
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

CREATE INDEX idx_whale_trades_wallet ON whale_trades(wallet_address);
CREATE INDEX idx_whale_trades_window ON whale_trades(window_ts);
