# Polymarket 5-Min Trading Bot

Automated trading bot for Polymarket's 5-minute crypto UP/DOWN markets. It reads Binance spot prices and Polymarket order books, scores entry signals, sizes positions with fractional Kelly, and actively manages exits within each 5-minute window. A Next.js dashboard reads live state from local PostgreSQL. Trade events are pushed to Telegram.

Paper trading is the default. Live execution requires Polymarket CLOB credentials and USDC on Polygon.

## Architecture

```
Binance WS ──┐
             ├──► bot.py (strategy + risk + execution)
Polymarket WS┘         │
                       ├──► PostgreSQL ──► dashboard/ (Next.js API routes)
                       └──► Telegram (trade exits, level ups, errors)

Gamma API ──► market discovery (condition IDs, token IDs)
Data API  ──► whale tracking (offline profiler + live monitor)
```

Each 5-minute window:

1. Discover active markets via the Gamma API (`execution/market_discovery.py`).
2. Subscribe to CLOB WebSocket order books for UP/DOWN tokens.
3. Classify volatility regime from Binance candles (`strategy/regime.py`).
4. Score signals from window delta, oracle lag, book imbalance, whale activity, and multi-exchange consensus (`strategy/signals.py`).
5. Size the bet with quarter-Kelly, capped by a capital-preservation phase (`strategy/kelly.py`, `bot.py`).
6. Enter and poll every 1.5s for exit conditions (take profit, stop loss, edge decay, resolution).
7. Log the trade to PostgreSQL and notify Telegram.

The bot can re-enter the same window up to 3 times if time and risk limits allow.

## Project structure

```
bot.py                  Entry point (paper by default, --live for CLOB orders)
config.py               Assets, bankroll limits, API credentials
preflight.py            Pre-run checks for env, deps, WS, PostgreSQL, Telegram, CLOB

data/
  binance_ws.py         Binance spot price + 1m candle stream
  polymarket_ws.py      Polymarket CLOB order book WebSocket
  historical.py         Historical 1m candles for backtests
  db.py                 PostgreSQL persistence (trades, bot state)
  pg.py                 PostgreSQL connection helpers

strategy/
  signals.py            Weighted signal stack (min score: 3.0)
  regime.py             ATR-based volatility regime + entry timing
  kelly.py              Fractional Kelly sizing (default 25%)
  reversal.py           Late-window contrarian reversal detection

execution/
  market_discovery.py   Gamma API — 5-min market slugs and token IDs
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
  logger.py             Logging setup
  health.py             HTTP health server (port 8080, not wired into bot.py)
```

## Strategy summary

**Markets:** Polymarket 5-min UP/DOWN markets. Slugs follow `{asset}-updown-5m-{window_ts}`. Market discovery supports BTC, ETH, SOL, and XRP; `config.ASSETS` currently trades BTC only.

**Trade types:**

| Type | When |
|------|------|
| `SNIPE` | Standard signal-driven entry |
| `DONE_DEAL` | Token ≥ $0.90, <15s left, signal > 6, whale confirmation — full phase-allowed size |
| `REVERSAL` | Late-window contrarian play (15% of bankroll) |

**Entry:** Token price between $0.65–$0.93. Signal score must exceed 3.0. Entry timing depends on regime (15–60s before window close).

**Exit triggers** (first match wins): `TAKE_PROFIT_10PCT`, `RESOLUTION_WIN`, `ACCEPTABLE_PROFIT`, `EDGE_VANISHED_PROFIT`, `BREAKEVEN_EXIT`, `STOP_LOSS`, `RESOLUTION_LOSS`.

**Risk limits** (from `config.py`, overridable via env):

- Daily loss limit: 20% of today's starting balance
- Peak drawdown cap: 40%
- Consecutive loss pause: 5 losses skips one window
- Minimum bet: $4.75 (bot stops if balance falls below this)

**Capital phases** (balance relative to `INITIAL_BANKROLL`):

| Phase | Ratio | Max bet |
|-------|-------|---------|
| 1 — Protecting Principal | < 2× | min(initial, balance) |
| 2 — House Money | 2–3× | balance − initial |
| 3 — Scaling Up | 3–5× | 50% of balance |
| 4 — Full Compound | ≥ 5× | 75% of balance |

Level milestones: $40 → $80 → $160 → … → $10,240.

## Setup

### PostgreSQL

```bash
docker compose up -d          # starts postgres:16 on port 5432
# Schema is applied automatically on first start via scripts/init_db.sql
# Or manually: python -c "from data import db; db.init_db()"
```

### Python bot

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL, TELEGRAM_*, etc.
python preflight.py    # paper-mode checks
python bot.py          # paper trading
python bot.py --live   # live CLOB execution
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

## Environment variables

### Bot (`.env` in project root)

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID for notifications |
| `POLY_PRIVATE_KEY` | Live only | Wallet private key for CLOB signing |
| `POLY_FUNDER_ADDRESS` | Live only | Funder/proxy wallet address |
| `POLY_SIGNATURE_TYPE` | Live only | Signature type (default `1`) |
| `RELAYER_API_KEY` | Live claims | Polymarket relayer API key |
| `RELAYER_API_KEY_ADDRESS` | Live claims | Relayer key address |
| `STARTING_BANKROLL` | No | Starting balance (default `20.00`) |
| `INITIAL_BANKROLL` | No | Phase baseline (default `10.00`) |
| `MIN_BET` | No | Minimum bet / blow-up threshold (default `4.75`) |
| `DAILY_LOSS_LIMIT` | No | Fraction (default `0.20`) |
| `DRAWDOWN_CAP` | No | Fraction (default `0.40`) |
| `CONSECUTIVE_LOSS_PAUSE` | No | Loss streak before skip (default `5`) |

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

- **PostgreSQL:** Single source of truth for `trades`, `bot_state`, `levels`, `tracked_wallets`, `whale_trades`, `commands`, plus bot-internal `predictions` and `window_prices`.
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
