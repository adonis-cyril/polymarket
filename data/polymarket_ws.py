"""
Polymarket CLOB websocket client for real-time order book data.

Connects to the CLOB WebSocket for live order book updates and trade feeds.
Used during the snipe window to get real-time token prices and order book
depth for the imbalance signal.

Endpoint: wss://ws-subscriptions-clob.polymarket.com/ws/market
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


@dataclass
class OrderBookLevel:
    """A single price level in the order book."""
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    """Current order book state for a token."""
    token_id: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    last_update: float = 0.0

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 1.0

    @property
    def mid_price(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return 0.5

    @property
    def bid_depth(self) -> float:
        """Total USD depth on bid side."""
        return sum(l.price * l.size for l in self.bids)

    @property
    def ask_depth(self) -> float:
        """Total USD depth on ask side."""
        return sum(l.price * l.size for l in self.asks)

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid


@dataclass
class RecentTrade:
    """A recently observed trade."""
    token_id: str
    price: float
    size: float
    side: str  # 'BUY' or 'SELL'
    timestamp: float


class PolymarketWebsocket:
    """
    Manages websocket connection to Polymarket CLOB for order book data.

    Usage:
        pws = PolymarketWebsocket()
        await pws.start()
        await pws.subscribe(up_token_id, down_token_id)
        book = pws.get_order_book(up_token_id)
        trades = pws.get_recent_trades(condition_id)
        await pws.stop()
    """

    def __init__(self):
        self._books: dict[str, OrderBookSnapshot] = {}
        self._recent_trades: dict[str, list[RecentTrade]] = defaultdict(list)
        self._subscribed_tokens: set[str] = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ws = None
        self._connected = asyncio.Event()
        self._reconnect_delay = 1.0

    async def start(self):
        """Start the websocket connection."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_forever())
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Polymarket WS initial connection timed out")

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

    async def subscribe(self, *token_ids: str):
        """Subscribe to order book updates for given token IDs."""
        new_tokens = set(token_ids) - self._subscribed_tokens
        if not new_tokens:
            return

        for token_id in new_tokens:
            self._books[token_id] = OrderBookSnapshot(token_id=token_id)
            self._subscribed_tokens.add(token_id)

        if self._ws:
            for token_id in new_tokens:
                msg = {
                    "type": "market",
                    "assets_ids": [token_id],
                }
                try:
                    await self._ws.send(json.dumps(msg))
                    logger.debug("Subscribed to token %s", token_id[:10])
                except Exception as e:
                    logger.error("Failed to subscribe to %s: %s", token_id[:10], e)

    async def unsubscribe_all(self):
        """Unsubscribe from all tokens."""
        self._subscribed_tokens.clear()
        self._books.clear()
        self._recent_trades.clear()

    # ----- Public data accessors -----

    def get_order_book(self, token_id: str) -> Optional[OrderBookSnapshot]:
        """Get the current order book snapshot for a token."""
        return self._books.get(token_id)

    def get_best_ask(self, token_id: str) -> float:
        """Get the best ask price for a token."""
        book = self._books.get(token_id)
        return book.best_ask if book else 1.0

    def get_best_bid(self, token_id: str) -> float:
        """Get the best bid price for a token."""
        book = self._books.get(token_id)
        return book.best_bid if book else 0.0

    def get_book_imbalance(self, up_token_id: str, down_token_id: str) -> float:
        """
        Calculate order book imbalance between UP and DOWN tokens.

        Returns a value from -1.0 to +1.0:
        +1.0 = all depth on UP side (bullish)
        -1.0 = all depth on DOWN side (bearish)
         0.0 = balanced
        """
        up_book = self._books.get(up_token_id)
        down_book = self._books.get(down_token_id)

        if not up_book or not down_book:
            return 0.0

        up_depth = up_book.bid_depth
        down_depth = down_book.bid_depth
        total = up_depth + down_depth

        if total == 0:
            return 0.0

        return (up_depth - down_depth) / total

    def get_recent_trades(self, token_id: str, max_age_seconds: float = 60) -> list[RecentTrade]:
        """Get recent trades for a token within max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        trades = self._recent_trades.get(token_id, [])
        return [t for t in trades if t.timestamp >= cutoff]

    # ----- Internal websocket management -----

    async def _run_forever(self):
        """Main loop: connect, receive messages, reconnect on failure."""
        while self._running:
            try:
                logger.info("Connecting to Polymarket CLOB WS...")
                async with websockets.connect(
                    CLOB_WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    self._reconnect_delay = 1.0
                    logger.info("Polymarket CLOB WS connected")

                    # Re-subscribe to any tokens
                    for token_id in self._subscribed_tokens:
                        msg = {"type": "market", "assets_ids": [token_id]}
                        await ws.send(json.dumps(msg))

                    async for raw_msg in ws:
                        if not self._running:
                            break
                        try:
                            parsed = json.loads(raw_msg)
                            # Polymarket can send arrays of messages
                            if isinstance(parsed, list):
                                for item in parsed:
                                    if isinstance(item, dict):
                                        self._handle_message(item)
                            elif isinstance(parsed, dict):
                                self._handle_message(parsed)
                        except json.JSONDecodeError:
                            pass  # Ignore non-JSON messages (pings, etc.)
                        except Exception:
                            logger.exception("Error handling Polymarket WS message")

            except ConnectionClosed as e:
                logger.warning("Polymarket WS closed: %s", e)
            except Exception:
                logger.exception("Polymarket WS connection error")

            self._ws = None
            self._connected.clear()

            if self._running:
                logger.info("Reconnecting in %.1fs...", self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)

    def _handle_message(self, msg: dict):
        """Route message to appropriate handler."""
        msg_type = msg.get("event_type", "")

        if msg_type == "book":
            self._handle_book_snapshot(msg)
        elif msg_type == "price_change":
            self._handle_price_change(msg)
        elif msg_type == "trade":
            self._handle_trade(msg)
        elif msg_type == "last_trade_price":
            self._handle_last_trade(msg)

    def _handle_book_snapshot(self, msg: dict):
        """Handle full order book snapshot."""
        asset_id = msg.get("asset_id", "")
        if asset_id not in self._books:
            return

        book = self._books[asset_id]
        book.bids = [
            OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
            for b in msg.get("bids", [])
        ]
        book.asks = [
            OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
            for a in msg.get("asks", [])
        ]
        # Sort bids descending, asks ascending
        book.bids.sort(key=lambda l: l.price, reverse=True)
        book.asks.sort(key=lambda l: l.price)
        book.last_update = time.time()

    def _handle_price_change(self, msg: dict):
        """Handle incremental price change."""
        asset_id = msg.get("asset_id", "")
        if asset_id not in self._books:
            return

        book = self._books[asset_id]
        changes = msg.get("changes", [])

        for change in changes:
            side = change.get("side", "")
            price = float(change.get("price", 0))
            size = float(change.get("size", 0))

            levels = book.bids if side == "BUY" else book.asks

            # Remove existing level at this price
            levels[:] = [l for l in levels if abs(l.price - price) > 0.0001]

            # Add new level if size > 0
            if size > 0:
                levels.append(OrderBookLevel(price=price, size=size))

            # Re-sort
            if side == "BUY":
                levels.sort(key=lambda l: l.price, reverse=True)
            else:
                levels.sort(key=lambda l: l.price)

        book.last_update = time.time()

    def _handle_trade(self, msg: dict):
        """Handle trade event."""
        asset_id = msg.get("asset_id", "")
        if asset_id not in self._subscribed_tokens:
            return

        trade = RecentTrade(
            token_id=asset_id,
            price=float(msg.get("price", 0)),
            size=float(msg.get("size", 0)),
            side=msg.get("side", "BUY"),
            timestamp=time.time(),
        )

        self._recent_trades[asset_id].append(trade)
        # Prune old trades (keep last 2 minutes)
        cutoff = time.time() - 120
        self._recent_trades[asset_id] = [
            t for t in self._recent_trades[asset_id] if t.timestamp >= cutoff
        ]

    def _handle_last_trade(self, msg: dict):
        """Handle last trade price update."""
        asset_id = msg.get("asset_id", "")
        if asset_id not in self._books:
            return
        # Update book's last trade reference
        self._books[asset_id].last_update = time.time()
