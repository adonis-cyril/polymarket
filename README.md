# Polymarket 5-Min Trading Bot

Automated trading bot for Polymarket's 5-minute crypto UP/DOWN markets. It reads Binance spot prices and Polymarket order books, scores entry signals, sizes positions with fractional Kelly, and actively manages exits within each 5-minute window. A Next.js dashboard reads live state from local PostgreSQL. Trade events are pushed to Telegram.

Paper trading is the default. Live execution requires Polymarket CLOB credentials and USDC on Polygon.

## Changes in `yo-alfred`

This branch replaces the Supabase stack with two self-hosted pieces:

### Local PostgreSQL

- **Before:** Supabase hosted Postgres + Realtime subscriptions in the dashboard.
- **After:** Local PostgreSQL via `docker compose up -d` (`postgres:16` on port 5432).
- Schema lives in `scripts/init_db.sql` and is applied on first container start.
- Bot persistence (`data/db.py`, `data/pg.py`), whale wallet tracking, and dashboard API routes (`dashboard/lib/db.ts`, `/api/*`) all read and write through `DATABASE_URL`.
- Supabase client code (`dashboard/lib/supabase.ts`, `notifications/supabase_push.py`) is removed.

### Telegram bot notifications

- **Before:** Trade and status events were pushed through Supabase.
- **After:** `notifications/telegram.py` sends alerts via the Telegram Bot API — trade exits, level-ups, pauses, errors, and bot start/stop.
- Configure with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (optional; bot runs without them).
- `notifications/db_sync.py` handles admin command polling and level milestone updates against PostgreSQL.

## Architecture

```
Binance WS ──┐
             ├──► bot.py (strategy + risk + execution)
Polymarket WS┘         │
                       ├──► PostgreSQL ──► dashboard/ (Next.js API routes)
                       └──► Telegram (trade exits, level ups, errors)

Gamma API ──► market discovery (condition IDs, token IDs)
Gamma API ──► active markets registry (full catalog cache, optional)
Data API  ──► whale tracking (offline profiler + live monitor)
```

Each 5-minute window:

1. Discover active markets via the Gamma API (`execution/market_discovery.py`).
2. Subscribe to CLOB WebSocket order books for UP/DOWN tokens.
3. Classify volatility regime from Binance candles (`strategy/regime.py`).
4. Score signals from window delta, oracle lag, book imbalance, whale activity, and multi-exchange consensus (`strategy/signals.py`).
5. Size the bet with quarter-Kelly, capped by a capital-preservation phase (`strategy/kelly.py`, `bot.py`).
6. Enter and poll for exit conditions (1.5s standard, 0.5s in HFT mode).
7. Log the trade to PostgreSQL and notify Telegram.

The bot can re-enter the same window up to 3 times if time and risk limits allow.

## Project structure

```
start.py                Primary entry — password gate + TUI workstation
bot.py                  Direct bot entry (paper by default, --live for CLOB orders)
config.py               Assets, bankroll limits, API credentials
preflight.py            Pre-run checks for env, deps, WS, PostgreSQL, Telegram, CLOB

data/
  binance_ws.py         Binance spot price + 1m candle stream
  polymarket_ws.py      Polymarket CLOB order book WebSocket
  historical.py         Historical 1m candles for backtests
  db.py                 PostgreSQL persistence (trades, bot state)
  pg.py                 PostgreSQL connection helpers
  market_registry.py    Full active-market catalog (cache + DB sync)
  market_cache.py       PostgreSQL persistence for cached_markets
  market_types.py       Normalized ActiveMarketRecord type

strategy/
  signals.py            Weighted signal stack (min score: 3.0)
  regime.py             ATR-based volatility regime + entry timing
  kelly.py              Fractional Kelly sizing (default 25%)
  reversal.py           Late-window contrarian reversal detection

execution/
  market_discovery.py   Gamma API — 5-min market slugs and token IDs
  active_markets.py     Gamma API — paginated fetch of all active markets
  order.py              CLOB buy/sell (maker-first, then FAK fallback)
  balance.py            USDC balance polling after fills
  claim.py              Relayer API for post-resolution claims

whale_tracking/
  profiler.py           Offline wallet discovery (cron job, not hot path)
  pattern_extractor.py  Historical whale pattern profiles
  live_monitor.py       Live whale presence in current market
  scorer.py             Whale signal for the signal stack
  wallet_db.py          Tracked wallet addresses from PostgreSQL

backtest/
  runner.py             Historical replay engine
  token_pricing.py      Token price estimation from Binance delta
  compare.py            Compare backtest configurations
  run_validation.py     Parameter validation script

notifications/
  db_sync.py            Admin command polling, level milestone updates
  telegram.py           Telegram Bot API notifications

dashboard/              Next.js 16 app — API routes query PostgreSQL
scripts/init_db.sql     PostgreSQL schema (applied by docker-compose or init_db())
supabase/migrations/    Historical schema reference (see README there)
deploy/                 systemd unit + Oracle Cloud ARM setup script
utils/
  logger.py                 Logging setup
  realtime_log.py           Verbose decision stream (REALTIME_* env)
  polymarket_connectivity.py DNS patch, retries, shared HTTP session
  health.py                 HTTP health server (port 8080, not wired into bot.py)

scripts/
  check_status.py           Connection & wallet status report
  check_binance.py          Binance REST + live OHLCV feed check
  setup_postgres_local.sh   Homebrew PostgreSQL 16 setup (macOS)
  refresh_markets.py        Active-market registry refresh / query
  fetch_active_markets.py   Gamma fetch → JSON cache
  btc_15s_trade.py          One-shot $1 live trade smoke test
  live_staircase.py         Entry point for live staircase tests

tests/
  test_order_sizing.py      compute_buy_shares budget enforcement
  test_bet_sizing.py        BET_SIZE / MAX_SESSION_SPEND resolution
  live_staircase/           Manual live CLOB test harness
```

## Strategy summary

**Markets:** Polymarket 5-min UP/DOWN markets. Slugs follow `{asset}-updown-5m-{window_ts}`. Market discovery supports BTC, ETH, SOL, and XRP; `config.ASSETS` currently trades BTC only.

**Modes:**

| Mode | Flag / env | Behavior |
|------|------------|----------|
| Standard (default) | `BOT_MODE=standard` | Kelly-sized entries, active mid-window exits, up to 3 re-entries |
| HFT scalp | `BOT_MODE=hft` or `--hft` | 2% TP / 1.5% SL, max 30s hold, lower signal threshold (2.0) |

### HFT mode

HFT mode runs the same 5-minute UP/DOWN markets but optimizes for **quick scalps** — tighter exits, faster polling, and a lower signal bar — instead of riding positions through mid-window edge decay to resolution.

**Enable:**

```bash
# .env
BOT_MODE=hft

# or CLI (overrides BOT_MODE)
python bot.py --hft          # paper
python bot.py --hft --live   # live CLOB
```

**How it differs from standard:**

| Aspect | Standard | HFT |
|--------|----------|-----|
| Sizing | Quarter-Kelly; DONE_DEAL and reversal use phase caps | `HFT_BET_FRACTION` of balance (default 10%), capped by capital phase |
| Min signal score | 3.0 | 2.0 (`HFT_MIN_SIGNAL_SCORE`) |
| Trade types | `SNIPE`, `DONE_DEAL`, `REVERSAL` | `HFT_SCALP` only |
| Expensive-token filter | Skips asks > $0.91 unless net return at resolution ≥ 7% | Disabled |
| Late-window reversal | Enabled (15–90s left) | Disabled |
| Position poll interval | 1.5s | 0.5s (`HFT_POLL_INTERVAL`) |
| Exit logic | Take profit, acceptable profit, edge decay, breakeven, stop loss, resolution | Fixed % TP/SL, time stop, then resolution |

**HFT exit triggers** (first match wins): token price ≥ entry × (1 + `HFT_TAKE_PROFIT_PCT`) with positive net return → `HFT_TAKE_PROFIT`; price ≤ entry × (1 − `HFT_STOP_LOSS_PCT`) → `HFT_STOP_LOSS`; hold time ≥ `HFT_MAX_HOLD_SECONDS` → `HFT_TIME_EXIT`; window close → `RESOLUTION_WIN` / `RESOLUTION_LOSS`. HFT stop-loss and time exits use urgent FAK sells in live mode.

**HFT parameters** (override in `.env`; see `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `HFT_TAKE_PROFIT_PCT` | `0.02` | Quick profit target (2% above entry) |
| `HFT_STOP_LOSS_PCT` | `0.015` | Tight stop (1.5% below entry) |
| `HFT_MAX_HOLD_SECONDS` | `30` | Force exit if TP/SL not hit |
| `HFT_MIN_SIGNAL_SCORE` | `2.0` | Lower entry threshold for faster fills |
| `HFT_BET_FRACTION` | `0.10` | Fraction of balance per scalp |
| `HFT_POLL_INTERVAL` | `0.5` | Position poll interval (seconds) |

HFT still respects the same risk limits (daily loss, drawdown, consecutive-loss pause, `MAX_SESSION_SPEND`) and can re-enter up to 3 times per window when time allows. `BET_SIZE` overrides the HFT fraction when set to a non-zero value.

**Trade types (standard mode):**

| Type | When |
|------|------|
| `SNIPE` | Standard signal-driven entry (quarter-Kelly) |
| `DONE_DEAL` | Token ≥ $0.90, <15s left, signal > 6, whale confirmation — full phase-allowed size |
| `REVERSAL` | Late-window contrarian play (15% of bankroll, or `BET_SIZE` when set) |
| `HFT_SCALP` | HFT mode only — fraction of balance per scalp |

**Signal stack** (`strategy/signals.py`): weighted window delta (7), oracle lag (3), book imbalance (2), whale pattern (2), live whale (1.5), multi-exchange consensus (1). Minimum score 3.0 (2.0 in HFT). Regime from ATR (`strategy/regime.py`) gates entry timing and skips `HIGH_VOL` windows.

**Entry:** Token price between $0.65–$0.93. Entry timing depends on regime (15–60s before window close).

**Exit triggers** (first match wins):

- **Standard:** `TAKE_PROFIT_10PCT`, `RESOLUTION_WIN`, `ACCEPTABLE_PROFIT`, `EDGE_VANISHED_PROFIT`, `BREAKEVEN_EXIT`, `STOP_LOSS`, `RESOLUTION_LOSS`
- **HFT:** `HFT_TAKE_PROFIT`, `HFT_STOP_LOSS`, `HFT_TIME_EXIT`, then resolution

**Risk limits** (from `config.py`, overridable via env):

- Daily loss limit: 20% of today's starting balance
- Peak drawdown cap: 40%
- Consecutive loss pause: 5 losses skips one window
- Minimum bet: $1.00 default (bot stops if balance falls below this)
- Session spend cap: `MAX_SESSION_SPEND` (0 = unlimited) — stops new entries after cumulative bet notional is reached

**Capital phases** (balance relative to `INITIAL_BANKROLL`):

| Phase | Ratio | Max bet |
|-------|-------|---------|
| 1 — Protecting Principal | < 2× | min(initial, balance) |
| 2 — House Money | 2–3× | balance − initial |
| 3 — Scaling Up | 3–5× | 50% of balance |
| 4 — Full Compound | ≥ 5× | 75% of balance |

Level milestones: $40 → $80 → $160 → … → $10,240.

### Small-bet / recovery config ($1 trades, $5 session cap)

Polymarket enforces a **5-share minimum** per order. A **$1** bet only fits when the ask is **≤ $0.20** (`5 × $0.20 = $1.00`). The bot and `execution/order.py` enforce this via `compute_buy_shares` before any live order is sent; entries at higher asks are skipped.

Example `.env` for up to five $1 trades:

```bash
STARTING_BANKROLL=5.00
INITIAL_BANKROLL=5.00
MIN_BET=1.00
BET_SIZE=1.00          # fixed USDC per trade (0 = Kelly / HFT fraction)
MAX_SESSION_SPEND=5.00 # stop after $5 total exposure this run
```

`BET_SIZE` overrides Kelly, HFT fraction, DONE_DEAL, and reversal sizing. `MAX_SESSION_SPEND` is tracked in-process (resets when the bot restarts).

## Setup

### PostgreSQL

```bash
docker compose up -d          # starts postgres:16 on port 5432
# Schema is applied automatically on first start via scripts/init_db.sql
# Or manually: python -c "from data import db; db.init_db()"
```

**Without Docker (macOS + Homebrew):** use native PostgreSQL 16 on port 5432 so `DATABASE_URL` stays the same (`postgresql://polymarket:polymarket@localhost:5432/polymarket`).

```bash
brew install postgresql@16
brew services start postgresql@16
./scripts/setup_postgres_local.sh   # creates user/db, applies scripts/init_db.sql
# Or manually:
# export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
# psql postgres -c "CREATE ROLE polymarket WITH LOGIN PASSWORD 'polymarket';"
# psql postgres -c "CREATE DATABASE polymarket OWNER polymarket;"
# psql -d polymarket -f scripts/init_db.sql
# python -c "from data import db; db.init_db()"   # as polymarket via DATABASE_URL in .env
```

Ensure `postgresql@16` is running before `python preflight.py`. If tables were created as your macOS user, re-run `./scripts/setup_postgres_local.sh` (it assigns ownership to `polymarket`) or connect with the same role that ran `init_db.sql`.

### Primary workflow (TUI workstation)

```bash
uv sync
cp .env.example .env   # set DATABASE_URL, ADMIN_PASSWORD, etc.
uv run python start.py # password gate → Hummingbot-style 2-pane trading console
# or: uv run polymarket
```

The TUI provides a keyboard-first 2-pane layout: left pane (markets/positions/bot status), right activity console (trades, logs, commands), and a `>>>` command bar (`buy`, `sell`, `cancel`, `refresh`, `positions`, `markets`, `help`, `quit`). Extended screens via `screen bot|tests|settings`. See `terminal/README.md` and `terminal/ARCHITECTURE.md`.

### Python bot (direct CLI)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL, TELEGRAM_*, etc.
python preflight.py    # paper-mode checks
python bot.py          # paper trading
python bot.py --live   # live CLOB execution
python bot.py --hft    # HFT scalp mode (paper; set BOT_MODE=hft in .env)
python bot.py --hft --live
```

Or with **uv**:

```bash
uv sync
uv run python preflight.py
uv run python bot.py
```

You can also start the bot from the TUI (`screen bot` or `bot start paper|live`).

**Before live trading**, run [operational checks](#operational-checks) (`preflight.py` and `scripts/check_status.py`).

### Live execution tests

Manual harness for real CLOB paths (default dry-run; pass `--live` for real orders). See `tests/live_staircase/README.md`.

```bash
python -m tests.live_staircase discover
python -m tests.live_staircase account --live
python -m tests.live_staircase buy --side up --size 1.00 --live
python scripts/live_staircase.py         # alternate entry point
```

One-shot $1 BTC 5m trade (buy UP, hold 15s, sell) using the same order paths as the bot:

```bash
python scripts/btc_15s_trade.py --live   # requires POLY_* credentials
```

### Dashboard

```bash
cd dashboard
npm install
cp ../.env.example .env.local   # set DATABASE_URL and ADMIN_PASSWORD
npm run dev                     # http://localhost:3000
```

Admin panel: `/admin` — sends `PAUSE`, `RESUME`, or `FORCE_SKIP` commands to PostgreSQL; the bot polls these each window.

Dashboard components poll API routes every few seconds (no Supabase Realtime).

### Backtesting

```bash
python backtest/run_validation.py
```

Or programmatically:

```python
from data.historical import fetch_all_assets
from backtest.runner import BacktestConfig, run_backtest

candles = fetch_all_assets(days=7)
result = run_backtest(candles, BacktestConfig())
result.print_summary()
```

### Fetch all active markets

The bot's hot path still uses slug-based 5-min discovery (`execution/market_discovery.py`). For the full Polymarket catalog, use the active-markets registry:

```bash
python scripts/refresh_markets.py --force    # pull from Gamma + persist to PostgreSQL
python scripts/refresh_markets.py --status   # cache metadata
python scripts/refresh_markets.py --slug-contains btc-updown
```

Programmatic access:

```python
from data.market_registry import get_active_markets, refresh_active_markets

markets = get_active_markets()                          # cache-first
markets = get_active_markets(event_slug_contains="nba") # filter by slug
result = refresh_active_markets(force=True)             # bypass TTL
```

Fetcher contract: `execution.active_markets.fetch_all_active_markets(page_size=...)` returns `list[ActiveMarketRecord]`. Registry handles TTL, PostgreSQL upserts, and deactivating markets missing from the latest sync.

Set `ACTIVE_MARKETS_SYNC_ON_STARTUP=true` to refresh in the background when `bot.py` starts.

JSON export (no DB required):

```bash
python scripts/fetch_active_markets.py
python scripts/fetch_active_markets.py --output data/cache/active_markets.json --stats
```

## Operational checks

Run these before starting the bot — especially before `--live`.

### Preflight (`preflight.py`)

End-to-end readiness check for every subsystem the bot depends on. Exits `0` when all required checks pass.

```bash
python preflight.py           # paper-mode checks
python preflight.py --live    # include CLOB auth + USDC balance
```

| # | Check | What it verifies |
|---|-------|------------------|
| 1 | Environment variables | `.env` exists; `config.py` loads; bankroll, `MIN_BET`, asset list; optional `DATABASE_URL` / Telegram vars |
| 2 | Python dependencies | Core imports (`websockets`, `requests`, `python-dotenv`, `aiohttp`, `psycopg2-binary`); optional `py-clob-client` / `web3` |
| 3 | PostgreSQL database | `DATABASE_URL` or `PG_*` configured; `init_db()` succeeds; `bot_state` readable |
| 4 | Binance WebSocket | Connects and receives spot prices for all configured assets (10s timeout) |
| 5 | Market discovery | Gamma API reachable; active 5-min markets found (or API OK with none in current window) |
| 6 | Active markets cache | Optional full-catalog registry status (skipped when `ACTIVE_MARKETS_CACHE_ENABLED=false`) |
| 7 | CLOB WebSocket | Subscribes to a live token; connection stable >5s; order book snapshot when available |
| 8 | Signal pipeline | Strategy modules import (`signals`, `regime`, `kelly`, `reversal`) |
| 9 | Telegram notifications | `getMe` API call when `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` set (skipped if unset) |
| 10 | CLOB auth (live) | `POLY_PRIVATE_KEY` → CLOB client init + USDC balance query — **only with `--live`**; skipped in paper mode |

### Connection & account status (`scripts/check_status.py`)

Formatted terminal dashboard for Polymarket connectivity and wallet health. Useful before live runs and when debugging ISP/DNS blocks.

```bash
python scripts/check_status.py           # full report
python scripts/check_status.py --quick   # skip CLOB WebSocket probe
python scripts/check_status.py --dns-only
```

**DNS / ISP** — resolves each Polymarket host (`gamma-api`, `clob`, etc.) via system DNS vs public DNS; flags ISP hijack/block-page IPs; reports whether `POLYMARKET_DNS_AUTO_FIX` bypass is active.

**API connectivity** — Gamma REST (`/events`) and CLOB REST (`/time`) latency and HTTP status (uses DNS patch when needed).

**Live data** — CLOB WebSocket connect + subscribe test on a sampling-market token; reports bid/ask when book data arrives (skipped with `--quick`).

**Account (CLOB wallet)** — when `POLY_PRIVATE_KEY` is set: funder vs signer addresses, signature type mapping, derived API credentials, tradable USDC balance, open position count and mark-to-market value from the Data API, plus hints when balance is $0 or position data looks stale.

Ends with a summary verdict: `ALL CLEAR`, `OK WITH WARNINGS`, or `ISSUES FOUND`. Exit code `1` if any check failed.

### Binance market data (`scripts/check_binance.py`)

Checks Binance public REST and WebSocket feeds for BTC, ETH, and SOL (independent of `config.ASSETS`). Useful before live runs when price/candle data must be healthy.

```bash
python scripts/check_binance.py
python scripts/check_binance.py --quick
python scripts/check_binance.py --assets btc,eth,sol
```

**REST** — `/api/v3/klines` (last 5 closed 1m candles + latest OHLCV) and `/api/v3/ticker/price` per asset.

**WebSocket** — combined `miniTicker` + `kline_1m` stream via `BinanceWebsocket`; verifies live price updates within ~10s and at least one closed 1m candle in the buffer (REST-seeded counts). Skipped with `--quick`. No API key required.

## Order execution & deposit wallets

Live orders go through `execution/order.py`:

1. **Maker-first buy:** GTC limit at `best_ask - $0.01`, 3s wait, then FAK fallback
2. **Sells:** GTC at target; urgent exits (stop loss, time stop) use FAK immediately
3. **Budget guard:** `compute_buy_shares(amount_usdc, best_ask)` sizes to stay within budget and rejects orders where the 5-share minimum would exceed notional

**Deposit wallets** (`POLY_SIGNATURE_TYPE=3`) use `py-clob-client-v2` for allowance sync and FAK orders. Proxy wallets (`POLY_SIGNATURE_TYPE=1`, default) use `py-clob-client`.

ISP DNS blocks are auto-bypassed via `utils/polymarket_connectivity.py` (optional overrides in `.env.example`).

## Environment variables

### Bot (`.env` in project root)

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID for notifications |
| `POLY_PRIVATE_KEY` | Live only | Wallet private key for CLOB signing |
| `POLY_FUNDER_ADDRESS` | Live only | Funder/proxy wallet address |
| `POLY_SIGNATURE_TYPE` | Live only | `1` proxy wallet, `3` deposit wallet (v2 client) |
| `RELAYER_API_KEY` | Live claims | Polymarket relayer API key |
| `RELAYER_API_KEY_ADDRESS` | Live claims | Relayer key address |
| `STARTING_BANKROLL` | No | Starting balance (default `20.00`) |
| `INITIAL_BANKROLL` | No | Phase baseline (default `10.00`) |
| `MIN_BET` | No | Minimum bet / blow-up threshold (default `1.00`) |
| `BET_SIZE` | No | Fixed USDC per trade; `0` = Kelly/HFT sizing (default `0`) |
| `MAX_SESSION_SPEND` | No | Total USDC cap for one bot run; `0` = unlimited (default `0`) |
| `DAILY_LOSS_LIMIT` | No | Fraction (default `0.20`) |
| `BOT_MODE` | No | `standard` or `hft` |
| `HFT_*` | No | HFT scalp params — see [HFT mode](#hft-mode) and `.env.example` |
| `DRAWDOWN_CAP` | No | Fraction (default `0.40`) |
| `CONSECUTIVE_LOSS_PAUSE` | No | Loss streak before skip (default `5`) |
| `ACTIVE_MARKETS_CACHE_ENABLED` | No | Enable full-market registry cache (default `true`) |
| `ACTIVE_MARKETS_DB_PERSIST` | No | Persist catalog to `cached_markets` table (default `true`) |
| `ACTIVE_MARKETS_CACHE_TTL` | No | Seconds before re-fetching Gamma (default `300`) |
| `ACTIVE_MARKETS_FETCH_PAGE_SIZE` | No | Gamma pagination page size (default `100`) |
| `ACTIVE_MARKETS_SYNC_ON_STARTUP` | No | Background refresh when bot starts (default `false`) |

CLOB API credentials are derived from `POLY_PRIVATE_KEY` at runtime — no separate API key env vars are read by the bot.

Alternatively set `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DATABASE` instead of `DATABASE_URL`.

### Dashboard (`dashboard/.env.local`)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection (server-side only) |
| `ADMIN_PASSWORD` | Password for `/admin` panel |

## Deployment

`deploy/setup.sh` targets Ubuntu 22.04+ ARM (Oracle Cloud). It creates a venv, installs dependencies, copies `deploy/polybot.service` to systemd, and runs preflight.

```bash
sudo systemctl start polybot
sudo systemctl stop polybot
journalctl -u polybot -f
```

For live mode, add `--live` to `ExecStart` in the systemd unit and restart.

Working directory: `/home/ubuntu/polymarket`. PostgreSQL required for bot and dashboard.

## Data storage

- **PostgreSQL:** Single source of truth for `trades`, `bot_state`, `levels`, `tracked_wallets`, `whale_trades`, `commands`, plus bot-internal `predictions`, `window_prices`, and optional `cached_markets` / `market_cache_meta` for the full active-market catalog.
- **Telegram:** Push notifications for trade exits, level ups, pauses, errors, and bot start/stop.

## External APIs

| Service | Used for |
|---------|----------|
| Binance WebSocket | Spot prices, 1m candles |
| Polymarket CLOB WebSocket | Order books, live prices |
| Polymarket Gamma API | Market discovery |
| Polymarket CLOB REST | Order placement (live) |
| Polymarket Data API | Whale trade history |
| Polymarket Relayer | Post-resolution claims |
| Coinbase / Kraken REST | Multi-exchange signal confirmation |
