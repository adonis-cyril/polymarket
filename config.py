"""Environment variables and constants for the trading bot."""

import os
from decimal import Decimal

# Assets traded on Polymarket 5-min markets
ASSETS = ["btc"]

# Binance trading pair symbols
BINANCE_SYMBOLS = {
    "btc": "BTCUSDT",
}

# Binance websocket base URL
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

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
INITIAL_BANKROLL = float(os.getenv("INITIAL_BANKROLL", "10.00"))
MIN_BET = Decimal(os.getenv("MIN_BET", "4.75"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "0.20"))
DRAWDOWN_CAP = float(os.getenv("DRAWDOWN_CAP", "0.40"))
CONSECUTIVE_LOSS_PAUSE = int(os.getenv("CONSECUTIVE_LOSS_PAUSE", "5"))
