"""
Offline whale profiler: discover top wallets on Polymarket 5-min markets.

Runs as a scheduled job (daily via cron), NOT in the hot trading path.

Process:
1. Query Polymarket Data API for recent trades on 5-min crypto markets
2. Aggregate by wallet: count trades, calculate win rate, compute PnL
3. Filter for top performers (50+ trades, 70%+ win rate, positive PnL)
4. For each top wallet, pull their last 500 trades with full context
5. Output wallet profiles for pattern extraction

Data source: Polymarket Data API (free, no auth required)
- GET https://data-api.polymarket.com/trades
- GET https://data-api.polymarket.com/events
"""

import logging
import time
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"

# Minimum thresholds for a wallet to be considered "top"
MIN_TRADES = 50
MIN_WIN_RATE = 0.70
MIN_PNL = 100.0  # $100 minimum total PnL
MIN_ACTIVE_DAYS = 3  # Must have traded in the last 3 days

# How many wallets to track
MAX_TRACKED_WALLETS = 20

# API pagination
TRADES_PER_PAGE = 1000
REQUEST_DELAY = 0.3  # seconds between API calls


@dataclass
class WalletStats:
    """Aggregated statistics for a single wallet."""
    address: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_wagered: float = 0.0
    last_trade_ts: int = 0
    trades: list = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades

    @property
    def avg_bet_size(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.total_wagered / self.total_trades


@dataclass
class WalletTrade:
    """A single trade by a wallet, enriched with market context."""
    wallet_address: str
    timestamp: int            # Unix seconds
    window_ts: int            # 5-min window start timestamp
    asset: str                # btc, eth, sol, xrp
    direction: str            # UP or DOWN
    token_price: float        # Price paid for the token
    bet_size: float           # USDC wagered
    outcome: str              # WIN or LOSS
    seconds_left: int = 0     # Seconds remaining when trade was placed
    btc_delta_pct: float = 0.0  # Populated later by pattern_extractor


def _get_json(url: str, params: dict = None) -> dict | list | None:
    """Make a GET request with retry logic."""
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d/3): %s %s", attempt + 1, url, e)
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
    return None


def discover_5min_market_ids(days: int = 7) -> list[dict]:
    """
    Find recent 5-min crypto UP/DOWN market IDs from Gamma API.

    Returns list of dicts with market metadata including condition_id
    and token IDs needed to fetch trades.
    """
    markets = []
    slugs_seen = set()

    # Search for recent 5-min events
    for asset in ["btc", "eth", "sol", "xrp"]:
        params = {
            "slug_contains": f"{asset}-updown-5m",
            "closed": "true",
            "limit": 200,
            "order": "endDate",
            "ascending": "false",
        }

        data = _get_json(f"{GAMMA_API_BASE}/events", params)
        if not data:
            continue

        for event in data:
            slug = event.get("slug", "")
            if slug in slugs_seen:
                continue
            slugs_seen.add(slug)

            for market in event.get("markets", []):
                condition_id = market.get("conditionId", "")
                clob_token_ids = market.get("clobTokenIds", [])
                if condition_id and len(clob_token_ids) >= 2:
                    markets.append({
                        "condition_id": condition_id,
                        "slug": slug,
                        "asset": asset,
                        "up_token_id": clob_token_ids[0],
                        "down_token_id": clob_token_ids[1],
                        "end_date": event.get("endDate", ""),
                    })

        time.sleep(REQUEST_DELAY)

    logger.info("Discovered %d 5-min markets across all assets", len(markets))
    return markets


def fetch_trades_for_market(condition_id: str, limit: int = TRADES_PER_PAGE) -> list[dict]:
    """Fetch trades for a single market from the Data API."""
    params = {
        "market": condition_id,
        "limit": limit,
    }
    data = _get_json(f"{DATA_API_BASE}/trades", params)
    return data if isinstance(data, list) else []


def aggregate_wallet_stats(markets: list[dict], max_markets: int = 500) -> dict[str, WalletStats]:
    """
    Fetch trades across multiple markets and aggregate by wallet.

    Args:
        markets: List of market dicts from discover_5min_market_ids.
        max_markets: Maximum number of markets to scan.

    Returns:
        Dict mapping wallet address to WalletStats.
    """
    wallets: dict[str, WalletStats] = {}

    for i, market in enumerate(markets[:max_markets]):
        if i > 0 and i % 50 == 0:
            logger.info("Scanned %d/%d markets, found %d unique wallets", i, len(markets), len(wallets))

        trades = fetch_trades_for_market(market["condition_id"])
        time.sleep(REQUEST_DELAY)

        for trade in trades:
            address = trade.get("maker", "") or trade.get("taker", "")
            if not address:
                continue

            if address not in wallets:
                wallets[address] = WalletStats(address=address)

            ws = wallets[address]
            ws.total_trades += 1

            price = float(trade.get("price", 0))
            size = float(trade.get("size", 0))
            side = trade.get("side", "")
            outcome = trade.get("outcome", "")

            bet_size = price * size
            ws.total_wagered += bet_size

            # Determine if this was a winning trade
            is_win = (side == "BUY" and outcome == "1") or (side == "SELL" and outcome == "0")
            if is_win:
                ws.wins += 1
                ws.total_pnl += size * (1.0 - price)
            else:
                ws.losses += 1
                ws.total_pnl -= bet_size

            trade_ts = int(trade.get("timestamp", 0))
            if trade_ts > ws.last_trade_ts:
                ws.last_trade_ts = trade_ts

            # Store raw trade for later analysis
            ws.trades.append({
                "timestamp": trade_ts,
                "asset": market["asset"],
                "condition_id": market["condition_id"],
                "side": side,
                "price": price,
                "size": size,
                "outcome": outcome,
            })

    logger.info("Aggregated stats for %d wallets", len(wallets))
    return wallets


def filter_top_wallets(wallets: dict[str, WalletStats]) -> list[WalletStats]:
    """
    Filter wallets to find top performers.

    Criteria:
    - 50+ trades on 5-min markets
    - 70%+ win rate
    - Positive PnL > $100
    - Active in the last 3 days
    """
    now = int(time.time())
    active_cutoff = now - (MIN_ACTIVE_DAYS * 24 * 60 * 60)

    top = []
    for ws in wallets.values():
        if ws.total_trades < MIN_TRADES:
            continue
        if ws.win_rate < MIN_WIN_RATE:
            continue
        if ws.total_pnl < MIN_PNL:
            continue
        if ws.last_trade_ts < active_cutoff:
            continue
        top.append(ws)

    # Sort by win rate * PnL (balances consistency with profitability)
    top.sort(key=lambda w: w.win_rate * w.total_pnl, reverse=True)

    # Keep top N
    top = top[:MAX_TRACKED_WALLETS]

    logger.info(
        "Filtered to %d top wallets (from %d total). Best: %s (%.1f%% win rate, $%.2f PnL)",
        len(top),
        len(wallets),
        top[0].address[:10] + "..." if top else "N/A",
        top[0].win_rate * 100 if top else 0,
        top[0].total_pnl if top else 0,
    )

    return top


def fetch_wallet_trade_history(
    address: str,
    markets: list[dict],
    max_trades: int = 500,
) -> list[WalletTrade]:
    """
    Fetch detailed trade history for a specific wallet across 5-min markets.

    This is used to build a comprehensive profile of the wallet's entry patterns.
    """
    wallet_trades: list[WalletTrade] = []

    for market in markets:
        if len(wallet_trades) >= max_trades:
            break

        trades = fetch_trades_for_market(market["condition_id"])
        time.sleep(REQUEST_DELAY)

        for trade in trades:
            trader = trade.get("maker", "") or trade.get("taker", "")
            if trader.lower() != address.lower():
                continue

            trade_ts = int(trade.get("timestamp", 0))
            price = float(trade.get("price", 0))
            size = float(trade.get("size", 0))
            side = trade.get("side", "")
            outcome = trade.get("outcome", "")

            # Determine direction and result
            direction = "UP" if side == "BUY" else "DOWN"
            is_win = (side == "BUY" and outcome == "1") or (side == "SELL" and outcome == "0")

            # Estimate window_ts from trade timestamp
            window_ts = trade_ts - (trade_ts % 300)
            seconds_left = (window_ts + 300) - trade_ts

            wallet_trades.append(WalletTrade(
                wallet_address=address,
                timestamp=trade_ts,
                window_ts=window_ts,
                asset=market["asset"],
                direction=direction,
                token_price=price,
                bet_size=price * size,
                outcome="WIN" if is_win else "LOSS",
                seconds_left=max(0, seconds_left),
            ))

    logger.info("Fetched %d trades for wallet %s...", len(wallet_trades), address[:10])
    return wallet_trades


def run_profiler(days: int = 7, max_markets: int = 500) -> list[tuple[WalletStats, list[WalletTrade]]]:
    """
    Full profiler pipeline: discover markets → aggregate → filter → fetch history.

    Returns list of (WalletStats, [WalletTrade]) tuples for each top wallet.
    """
    logger.info("Starting whale profiler (scanning last %d days)...", days)

    # Step 1: Discover markets
    markets = discover_5min_market_ids(days=days)
    if not markets:
        logger.error("No 5-min markets found")
        return []

    # Step 2: Aggregate wallet stats
    wallets = aggregate_wallet_stats(markets, max_markets=max_markets)

    # Step 3: Filter top wallets
    top_wallets = filter_top_wallets(wallets)
    if not top_wallets:
        logger.warning("No wallets met the top performer criteria")
        return []

    # Step 4: Fetch detailed history for each top wallet
    results = []
    for ws in top_wallets:
        trade_history = fetch_wallet_trade_history(ws.address, markets)
        results.append((ws, trade_history))

    logger.info("Profiler complete: %d wallets profiled", len(results))
    return results
