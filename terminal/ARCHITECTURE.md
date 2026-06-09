# Terminal Architecture

Hummingbot-inspired TUI for Polymarket — simplified to two main panes.

## Hummingbot → Polymarket mapping

| Hummingbot pane | Our component | Notes |
|-----------------|---------------|-------|
| Input (lower left) | `ui/widgets/command_bar.py` | `>>>` prompt, command history |
| Output (upper left) | `ui/widgets/left_pane.py` | POLYADONIS welcome, markets, positions |
| Log (right) | `ui/widgets/activity_pane.py` | Trades, fills, signals, errors |
| Top nav bar | `ui/widgets/top_bar.py` | Connection, account, strategy/mode |
| Bottom nav bar | `ui/widgets/metrics_bar.py` | Trades, P&L, return%, duration, mem |

Deferred (hooks only): tab system for order book (`commands` can open tabs later), Ctrl+F log search.

## Module layout

```
terminal/
├── ui/              Textual app, layout, widgets
├── market_data/     Async polling (providers + orchestrator)
├── engine/          Trading actions (buy/sell/cancel)
├── state/           Centralized AppState
├── commands/        Registry + handlers
├── logging/         loguru → activity pane sink
├── events/          Pub/sub between layers
└── core/            Shared models
```

## Data flow

```
connect command ──► preflight + orchestrator.start()
market_data/orchestrator ──poll (after connect)──► state/store
        │                              │
        └──── emit events ────────────►│
                                       ▼
                              events/bus ──► ui/app (sync widgets)
commands/registry ──► engine/trading (buy/sell/cancel)
commands/connection ──► connect | status | balance
        │                      │
        └──── emit ────────────┴──► activity pane + state
logging/setup ──callback──► activity pane (loguru sink)
```

## Event bus

- `STATE_UPDATED`, `TRADES_UPDATED`, `MARKETS_UPDATED`, `CONNECTIVITY_UPDATED`
- `REFRESH_REQUESTED`, `LEFT_VIEW_CHANGED`, `ACTIVITY_EVENT`
- `COMMAND_EXECUTED`, `NOTIFICATION`, `ERROR`

## Extensibility

- New commands: `registry.register(name, desc, handler)`
- New left views: extend `LeftView` enum + `left_pane.py`
- Order book tab: future `tab open order_book <slug>` command
- Charts: optional widget in left pane without layout change
