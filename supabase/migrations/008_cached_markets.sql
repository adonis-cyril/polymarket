-- Cached Polymarket active markets (full catalog sync)

CREATE TABLE IF NOT EXISTS cached_markets (
    condition_id VARCHAR(66) PRIMARY KEY,
    event_id VARCHAR(32),
    event_slug VARCHAR(255) NOT NULL DEFAULT '',
    market_slug VARCHAR(255) NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    outcomes JSONB NOT NULL DEFAULT '[]',
    clob_token_ids JSONB NOT NULL DEFAULT '[]',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    closed BOOLEAN NOT NULL DEFAULT FALSE,
    end_date TIMESTAMPTZ,
    volume_24hr DECIMAL(20,4),
    liquidity DECIMAL(20,4),
    gamma_updated_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cached_markets_active ON cached_markets(active) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS idx_cached_markets_event_slug ON cached_markets(event_slug);
CREATE INDEX IF NOT EXISTS idx_cached_markets_fetched_at ON cached_markets(fetched_at DESC);

CREATE TABLE IF NOT EXISTS market_cache_meta (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_full_sync_at TIMESTAMPTZ,
    last_sync_count INTEGER DEFAULT 0,
    sync_status VARCHAR(20) NOT NULL DEFAULT 'idle',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO market_cache_meta (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
