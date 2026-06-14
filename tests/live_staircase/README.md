# Live Staircase Test Suite

Manual on-demand tests for Polymarket **live execution paths**. Each "stair" exercises one real code path (`market_discovery`, `order`, `balance`) with structured logging — build and verify one step before stacking the next.

**Default is dry-run.** Pass `--live` to submit real orders.

## Setup

```bash
cp .env.example .env   # POLY_PRIVATE_KEY, POLY_FUNDER_ADDRESS required for --live
pip install -r requirements.txt
```

Optional env vars (see `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `STAIRCASE_DEFAULT_SIZE` | `2.00` | Default bet size (USDC) |
| `STAIRCASE_TP_PCT` | `0.02` | Take-profit % |
| `STAIRCASE_SL_PCT` | `0.015` | Stop-loss % |
| `STAIRCASE_LOG_FILE` | `logs/staircase.log` | File log path |

## Commands

```bash
# Discover current BTC 5m window (no auth)
python -m tests.live_staircase discover

# Account details (USDC balance, allowance, funder, orders — needs --live)
python -m tests.live_staircase account --live

# Market + position snapshot (balance/orders need --live)
python -m tests.live_staircase status --live

# Buy UP token, $2 default
python -m tests.live_staircase buy --side up --size 2.00 --live

# Sell / urgent exit
python -m tests.live_staircase sell --side up --live
python -m tests.live_staircase exit --side up --live

# Take-profit / stop-loss
python -m tests.live_staircase take-profit --side up --live
python -m tests.live_staircase stop-loss --side up --live

# Cancel orders
python -m tests.live_staircase cancel --live
python -m tests.live_staircase cancel --order-id <id> --live

# Last-minute snipe (15–60s left, configurable)
python -m tests.live_staircase last-minute --side up --live

# Full guided flow
python -m tests.live_staircase run-staircase
python -m tests.live_staircase run-staircase --live --auto
```

Equivalent entry point:

```bash
python scripts/live_staircase.py discover
```

## Recommended first run

1. **Discover (dry-run)** — confirms Gamma API + market slugs:
   ```bash
   python -m tests.live_staircase discover
   ```

2. **Account (live auth only)** — confirms CLOB credentials and USDC balance:
   ```bash
   python -m tests.live_staircase account --live
   ```

   Example output:
   ```
   === STAIR: account ===
   Account config:
     funder_address=0x...
     signer_address=0x...
     signature_type=1 (POLY_PROXY)
     private_key=set
     collateral_token=0x...
   USDC collateral:
     balance=$12.34
     allowance=$12.34
   Open orders: 0
   Conditional positions: none (current BTC window)
   ```

3. **Status** — same auth path plus current BTC market books:
   ```bash
   python -m tests.live_staircase status --live
   ```

4. **Small live buy** — default $2, confirms order path:
   ```bash
   python -m tests.live_staircase buy --side up --size 2.00 --live
   ```

State from a successful buy is saved to `logs/staircase_state.json` for sell/TP/SL stairs.

## Safety

- `--live` required for real orders; without it, commands log intent only
- Interactive confirmation before each live order (skip with `--yes` or `--auto`)
- Default size is small ($2); override with `--size`
- Does **not** start the main `bot.py` trading loop
