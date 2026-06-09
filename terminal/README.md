# Polymarket Terminal

Hummingbot-inspired 2-pane trading console for the Polymarket bot.

## Run

```bash
uv sync
cp .env.example .env   # ADMIN_PASSWORD + DATABASE_URL

uv run python start.py
# or
uv run polymarket
```

## Output routing

| Destination | Content |
|-------------|---------|
| Below `>>>` (left bottom) | Short command replies — `status`, `balance`, `config`, `run`, `stop` (≤20 lines) |
| Activity pane (right) | Bot stdout, loguru logs, preflight, connect flow, long test output |

## Layout

| Area | Content |
|------|---------|
| Top bar | Version, mode/strategy, balance, connectivity |
| Left pane | Overview, markets, or positions |
| Right pane | Live activity — bot logs, trades, long output, preflight |
| Metrics bar | Trades, P&L, return%, duration, threads, memory |
| Command bar | `>>>` prompt + short command output below |

## Commands

On launch the left pane shows the **POLYADONIS** welcome screen — no stats until you connect.

Core: `connect`, `status`, `config`, `balance`, `buy`, `sell`, `cancel`, `refresh`, `positions`, `markets`, `help`, `quit`

- `connect` — preflight checks, start data sync, verify services
- `status` — health check (Gamma, CLOB, PostgreSQL, bot)
- `config` — bets and bot settings from `.env`
- `balance` — USDC balance from CLOB (`--live` for auth)

Trading flags: `--live`, `--side up|down`, `--size N`, `--shares N`, `--urgent`, `--order-id ID`

Extended: `bot`, `pause`, `resume`, `staircase`, `preflight`, `screen bot|tests|settings`

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `F5` | Force refresh |
| `Ctrl+T` | Focus activity pane |
| `Ctrl+S` | Run status command |
| `Ctrl+Q` / `q` | Quit |
| `?` | Help modal |
| `Ctrl+P` | Command list |

Legacy screens (F2/F3/F4 removed from main view): `screen bot|tests|settings`

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for module layout and data flow.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Type `connect` + Enter, input clears, nothing happens | Textual 8 message handlers use `on_<message>` (e.g. `on_command_submitted`), not `on_<widget>_<message>` | Fixed in current tree — update and restart |
| `connect` runs but left pane still idle | Preflight failed (often missing `DATABASE_URL`) | Read activity pane output; set `.env` from `.env.example` |
| Logs missing in activity pane during tests | Loguru sink on app thread | Harmless in production; TUI uses thread-safe dispatch |

Commands always echo `>>> your-command` in the activity pane before running. Short feedback (`Running connect…`) appears below the prompt while work is in progress.

## Env

| Variable | Default | Purpose |
|----------|---------|---------|
| `TUI_THEME` | `polyadonis` | `polyadonis`, `bloomberg`, `midnight`, `light` |
| `TUI_REFRESH_INTERVAL` | `2.0` | Poll interval (seconds) |
| `TUI_LOG_LEVEL` | `INFO` | Console log level |
