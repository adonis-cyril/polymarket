# Polymarket 5-Min Trading Bot

Automated bot for Polymarket 5-minute crypto UP/DOWN markets. It streams Binance spot prices and Polymarket order books, scores entries, sizes with fractional Kelly, and manages exits within each window. State lives in local PostgreSQL; optional Telegram alerts and a Next.js dashboard.

**Paper trading is the default.** Live trading needs Polymarket CLOB credentials and USDC on Polygon.

## Quick start

### 1. Database

```bash
docker compose up -d
```

Schema applies on first start (`scripts/init_db.sql`). macOS without Docker: `./scripts/setup_postgres_local.sh`.

### 2. Configure

```bash
uv sync
cp .env.example .env
```

Set at minimum: `DATABASE_URL`, `ADMIN_PASSWORD`. For live: `POLY_PRIVATE_KEY`, `POLY_FUNDER_ADDRESS`. Optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### 3. Run

**Terminal UI (recommended):**

```bash
uv run python start.py
```

Password-gated 2-pane console — `connect`, `status`, `balance`, `buy`/`sell`, bot control. See `terminal/README.md`.

**Headless bot:**

```bash
uv run python preflight.py
uv run python bot.py              # paper
uv run python bot.py --live       # live CLOB
uv run python bot.py --hft        # quick-scalp mode
```

### 4. Dashboard

```bash
cd dashboard && npm install
cp ../.env.example .env.local     # DATABASE_URL, ADMIN_PASSWORD
npm run dev                       # http://localhost:3000
```

Admin panel at `/admin` — pause, resume, or force-skip via PostgreSQL commands the bot polls each window.

## How it works

```
Binance WS ──┐
             ├──► bot.py ──► PostgreSQL ──► dashboard/
Polymarket WS┘         └──► Telegram (optional)
```

Each 5-minute window: discover markets (Gamma API) → subscribe to CLOB books → score signals (delta, oracle lag, book imbalance, whales) → Kelly-sized entry → active exits → log trade.

| Mode | How to enable | Behavior |
|------|---------------|----------|
| Standard | default / `BOT_MODE=standard` | Kelly sizing, mid-window exits, up to 3 re-entries |
| HFT scalp | `BOT_MODE=hft` or `--hft` | 2% TP / 1.5% SL, 30s max hold, faster polling |

**Small bets:** Polymarket requires 5 shares minimum. A $1 bet only works when ask ≤ $0.20. Set `BET_SIZE=1.00` and `MAX_SESSION_SPEND=5.00` in `.env` for capped recovery runs.

## Checks before live

```bash
uv run python preflight.py --live       # full subsystem check
python scripts/check_status.py          # DNS, API, wallet, CLOB WS
python scripts/check_binance.py         # Binance REST + WS feeds
```

## Key environment variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL (required) |
| `ADMIN_PASSWORD` | TUI + dashboard admin |
| `POLY_PRIVATE_KEY` | Live CLOB signing |
| `POLY_FUNDER_ADDRESS` | Wallet / proxy address |
| `POLY_SIGNATURE_TYPE` | `1` proxy, `3` deposit wallet |
| `STARTING_BANKROLL` / `INITIAL_BANKROLL` | Balance + phase baseline |
| `BET_SIZE` | Fixed USDC per trade (`0` = Kelly/HFT) |
| `MAX_SESSION_SPEND` | Session cap (`0` = unlimited) |
| `BOT_MODE` | `standard` or `hft` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Alerts (optional) |

Full list in `.env.example`. HFT tuning: `HFT_TAKE_PROFIT_PCT`, `HFT_STOP_LOSS_PCT`, `HFT_MAX_HOLD_SECONDS`, etc.

## Useful scripts

| Script | Purpose |
|--------|---------|
| `scripts/check_status.py` | Connectivity + wallet report |
| `scripts/check_binance.py` | Price/candle feed health |
| `scripts/refresh_markets.py` | Full Polymarket catalog cache |
| `scripts/btc_15s_trade.py` | One-shot $1 live smoke test |
| `backtest/run_validation.py` | Historical replay |

## Deployment

`deploy/setup.sh` targets Ubuntu ARM (Oracle Cloud). Installs deps, systemd unit (`deploy/polybot.service`), runs preflight. Add `--live` to `ExecStart` for real orders.

## Project layout

| Path | Role |
|------|------|
| `start.py` / `terminal/` | TUI workstation |
| `bot.py` | Trading engine |
| `strategy/` | Signals, regime, Kelly, reversal |
| `execution/` | Market discovery, CLOB orders |
| `data/` | WebSockets, DB, market cache |
| `dashboard/` | Next.js UI |
| `notifications/` | Telegram + admin polling |
