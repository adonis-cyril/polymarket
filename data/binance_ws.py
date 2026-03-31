"""
Binance websocket client for real-time price feeds and 1-min candles.

Connects to Binance combined streams for BTC/ETH/SOL/XRP:
- Mini-ticker stream: real-time price updates (~1s frequency)
- Kline 1m stream: 1-minute candle data for ATR/volatility calculations

Maintains:
- Current price per asset (updated every ~1s)
- Rolling price history buffer (last 120s of tick prices for reversal detection)
- Rolling 1-min candle buffer (last 60 candles per asset for ATR calculation)
"""

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

from config import ASSETS, BINANCE_SYMBOLS, BINANCE_WS_URL, CANDLE_BUFFER_SIZE, PRICE_HISTORY_SECONDS

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    """A single 1-minute candle."""
    open_time: int       # Unix ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int      # Unix ms
    is_closed: bool


@dataclass
class PriceTick:
    """A single price observation with timestamp."""
    timestamp: float     # Unix seconds (time.time())
    price: float


@dataclass
class AssetData:
    """All tracked data for a single asset."""
    current_price: float = 0.0
    price_history: deque = field(default_factory=lambda: deque(maxlen=600))
    candles: deque = field(default_factory=lambda: deque(maxlen=CANDLE_BUFFER_SIZE))
    last_update: float = 0.0


class BinanceWebsocket:
    """
    Manages websocket connections to Binance for real-time price data.

    Usage:
        bws = BinanceWebsocket()
        await bws.start()       # starts background task
        price = bws.get_price("btc")
        candles = bws.get_candles("btc", count=30)
        price_20s_ago = bws.get_price_at("btc", seconds_ago=20)
        await bws.stop()
    """

    def __init__(self):
        self._data: dict[str, AssetData] = {asset: AssetData() for asset in ASSETS}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._connected = asyncio.Event()
        self._reconnect_delay = 1.0

    async def start(self):
        """Start the websocket connection in a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_forever())
        # Wait for initial connection (up to 10 seconds)
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Binance WS initial connection timed out, will keep retrying in background")

    async def stop(self):
        """Stop the websocket connection."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._connected.clear()

    def is_connected(self) -> bool:
        return self._connected.is_set()

    # ----- Public data accessors -----

    def get_price(self, asset: str) -> float:
        """Get the current price for an asset. Returns 0.0 if no data yet."""
        return self._data[asset].current_price

    def get_price_at(self, asset: str, seconds_ago: float) -> Optional[float]:
        """
        Get the price from approximately `seconds_ago` seconds in the past.
        Returns the closest available tick, or None if no data in that range.
        """
        target_time = time.time() - seconds_ago
        history = self._data[asset].price_history

        if not history:
            return None

        # Binary-ish search: history is ordered by time, find closest to target
        best: Optional[PriceTick] = None
        best_diff = float("inf")

        for tick in history:
            diff = abs(tick.timestamp - target_time)
            if diff < best_diff:
                best_diff = diff
                best = tick

        # Only return if we found something within 5 seconds of the target
        if best and best_diff <= 5.0:
            return best.price
        return None

    def get_candles(self, asset: str, count: int = 30) -> list[Candle]:
        """
        Get the last `count` closed 1-min candles for an asset.
        Returns oldest-first order.
        """
        candles = self._data[asset].candles
        closed = [c for c in candles if c.is_closed]
        return list(closed)[-count:]

    def get_all_prices(self) -> dict[str, float]:
        """Get current prices for all assets."""
        return {asset: self._data[asset].current_price for asset in ASSETS}

    def get_price_change_pct(self, asset: str, seconds_ago: float) -> Optional[float]:
        """
        Calculate percentage price change from `seconds_ago` to now.
        Returns None if historical price is unavailable.
        """
        current = self.get_price(asset)
        past = self.get_price_at(asset, seconds_ago)

        if not past or past == 0 or current == 0:
            return None

        return ((current - past) / past) * 100.0

    # ----- Internal websocket management -----

    def _build_stream_url(self) -> str:
        """Build the combined streams URL for all assets."""
        streams = []
        for asset in ASSETS:
            symbol = BINANCE_SYMBOLS[asset].lower()
            streams.append(f"{symbol}@miniTicker")
            streams.append(f"{symbol}@kline_1m")
        stream_path = "/".join(streams)
        return f"{BINANCE_WS_URL}/{stream_path}"

    async def _run_forever(self):
        """Main loop: connect, receive messages, reconnect on failure."""
        while self._running:
            try:
                url = self._build_stream_url()
                logger.info("Connecting to Binance WS: %s", url)

                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._connected.set()
                    self._reconnect_delay = 1.0
                    logger.info("Binance WS connected")

                    async for raw_msg in ws:
                        if not self._running:
                            break
                        try:
                            self._handle_message(json.loads(raw_msg))
                        except Exception:
                            logger.exception("Error handling Binance WS message")

            except ConnectionClosed as e:
                logger.warning("Binance WS connection closed: %s", e)
            except Exception:
                logger.exception("Binance WS connection error")

            self._connected.clear()

            if self._running:
                logger.info("Reconnecting in %.1fs...", self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)

    def _handle_message(self, msg: dict):
        """Route incoming message to the appropriate handler."""
        event_type = msg.get("e")

        if event_type == "24hrMiniTicker":
            self._handle_ticker(msg)
        elif event_type == "kline":
            self._handle_kline(msg)

    def _handle_ticker(self, msg: dict):
        """Handle mini-ticker update: update current price and price history."""
        symbol = msg.get("s", "")
        price = float(msg.get("c", 0))  # 'c' = close price

        asset = self._symbol_to_asset(symbol)
        if not asset:
            return

        now = time.time()
        data = self._data[asset]
        data.current_price = price
        data.last_update = now

        # Append to price history, prune old entries
        data.price_history.append(PriceTick(timestamp=now, price=price))
        self._prune_price_history(data)

    def _handle_kline(self, msg: dict):
        """Handle kline/candle update: update or append candle."""
        kline = msg.get("k", {})
        symbol = kline.get("s", "")

        asset = self._symbol_to_asset(symbol)
        if not asset:
            return

        candle = Candle(
            open_time=kline["t"],
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            close_time=kline["T"],
            is_closed=kline["x"],
        )

        candles = self._data[asset].candles

        # Update the last candle if same open_time, otherwise append
        if candles and candles[-1].open_time == candle.open_time:
            candles[-1] = candle
        else:
            candles.append(candle)

    def _symbol_to_asset(self, symbol: str) -> Optional[str]:
        """Convert Binance symbol (e.g., 'BTCUSDT') to asset key (e.g., 'btc')."""
        symbol_upper = symbol.upper()
        for asset, sym in BINANCE_SYMBOLS.items():
            if sym == symbol_upper:
                return asset
        return None

    def _prune_price_history(self, data: AssetData):
        """Remove price ticks older than PRICE_HISTORY_SECONDS."""
        cutoff = time.time() - PRICE_HISTORY_SECONDS
        while data.price_history and data.price_history[0].timestamp < cutoff:
            data.price_history.popleft()
