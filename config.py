"""Environment variables and constants for the trading bot."""

import os
from decimal import Decimal

# Assets traded on Polymarket 5-min markets
ASSETS = ["btc"]

# Binance trading pair symbols
BINANCE_SYMBOLS = {
    "btc": "BTCUSDT",
}

# Binance websocket base (raw: /ws/<stream>, combined: /stream?streams=a/b)
BINANCE_WS_BASE = "wss://stream.binance.com:9443"

# Rolling buffer sizes
CANDLE_BUFFER_SIZE = 60        # Keep last 60 one-minute candles per asset
PRICE_HISTORY_SECONDS = 120    # Keep last 120 seconds of tick prices

# Polymarket
POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY", "")
POLY_FUNDER_ADDRESS = os.getenv("POLY_FUNDER_ADDRESS", "")
POLY_SIGNATURE_TYPE = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))

# Relayer
RELAYER_API_KEY = os.getenv("RELAYER_API_KEY", "")
RELAYER_API_KEY_ADDRESS = os.getenv("RELAYER_API_KEY_ADDRESS", "")

# CLOB API
POLY_CLOB_URL = "https://clob.polymarket.com"
POLY_CHAIN_ID = 137  # Polygon mainnet

# PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Telegram notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Bot config
STARTING_BANKROLL = Decimal(os.getenv("STARTING_BANKROLL", "20.00"))
INITIAL_BANKROLL = Decimal(os.getenv("INITIAL_BANKROLL", "10.00"))
MIN_BET = Decimal(os.getenv("MIN_BET", "1.00"))
# Fixed USDC per trade (0 = use Kelly / HFT fraction / reversal %)
BET_SIZE = Decimal(os.getenv("BET_SIZE", "0"))
# Total USDC exposure cap for this bot process (0 = unlimited)
MAX_SESSION_SPEND = Decimal(os.getenv("MAX_SESSION_SPEND", "0"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "0.20"))
DRAWDOWN_CAP = float(os.getenv("DRAWDOWN_CAP", "0.40"))
CONSECUTIVE_LOSS_PAUSE = int(os.getenv("CONSECUTIVE_LOSS_PAUSE", "5"))

# Bot mode: standard (default) or hft (quick scalp strategy)
BOT_MODE = os.getenv("BOT_MODE", "standard").lower()

# Realtime thinking + verbose logging during active evaluation
REALTIME_THINKING = os.getenv("REALTIME_THINKING", "true").lower() in ("true", "1", "yes")
REALTIME_LOGGING = os.getenv("REALTIME_LOGGING", "true").lower() in ("true", "1", "yes")
REALTIME_LOG_LEVEL = os.getenv("REALTIME_LOG_LEVEL", "DEBUG")
REALTIME_LOG_FILE = os.getenv("REALTIME_LOG_FILE", "logs/bot_realtime.log")

# HFT scalp parameters (used when BOT_MODE=hft or --hft)
HFT_TAKE_PROFIT_PCT = float(os.getenv("HFT_TAKE_PROFIT_PCT", "0.02"))
HFT_STOP_LOSS_PCT = float(os.getenv("HFT_STOP_LOSS_PCT", "0.015"))
HFT_MAX_HOLD_SECONDS = int(os.getenv("HFT_MAX_HOLD_SECONDS", "30"))
HFT_MIN_SIGNAL_SCORE = float(os.getenv("HFT_MIN_SIGNAL_SCORE", "2.0"))
HFT_BET_FRACTION = float(os.getenv("HFT_BET_FRACTION", "0.10"))
HFT_POLL_INTERVAL = float(os.getenv("HFT_POLL_INTERVAL", "0.5"))

# Active markets registry (full Polymarket catalog via Gamma API)
ACTIVE_MARKETS_CACHE_ENABLED = os.getenv("ACTIVE_MARKETS_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
ACTIVE_MARKETS_DB_PERSIST = os.getenv("ACTIVE_MARKETS_DB_PERSIST", "true").lower() in ("true", "1", "yes")
ACTIVE_MARKETS_CACHE_TTL = int(os.getenv("ACTIVE_MARKETS_CACHE_TTL", "300"))
ACTIVE_MARKETS_FETCH_PAGE_SIZE = int(os.getenv("ACTIVE_MARKETS_FETCH_PAGE_SIZE", "100"))
ACTIVE_MARKETS_SYNC_ON_STARTUP = os.getenv("ACTIVE_MARKETS_SYNC_ON_STARTUP", "false").lower() in ("true", "1", "yes")
