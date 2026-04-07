"""
Preflight readiness check for the Polymarket trading bot.

Systematically verifies every subsystem the bot depends on
and reports pass/fail with actionable error messages.

Usage:
    python preflight.py              # Paper mode checks
    python preflight.py --live       # Include CLOB auth + balance
"""

import argparse
import asyncio
import importlib
import logging
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
SKIP = "\033[93m[SKIP]\033[0m"


class CheckResult:
    def __init__(self, name, status, detail):
        self.name = name
        self.status = status
        self.detail = detail


def check_env_vars():
    """Check 1: .env file exists and config loads correctly."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return CheckResult(
            "Environment variables",
            FAIL,
            ".env file not found — copy .env.example to .env",
        )

    try:
        from config import (
            STARTING_BANKROLL, INITIAL_BANKROLL, MIN_BET, ASSETS,
        )
    except Exception as e:
        return CheckResult(
            "Environment variables",
            FAIL,
            f"config.py failed to load: {e}",
        )

    placeholders = ("...", "your-anon-key-here", "0x...")
    configured = []
    for var in ("SUPABASE_URL", "SUPABASE_KEY",
                "GMAIL_ADDRESS"):
        val = os.getenv(var, "")
        if val and val not in placeholders:
            configured.append(var.split("_")[0].lower())

    detail = (
        f"Bankroll=${float(STARTING_BANKROLL):.2f}, "
        f"min_bet=${float(MIN_BET):.2f}, "
        f"{len(ASSETS)} assets"
    )
    if configured:
        detail += f", optional: {', '.join(configured)}"
    return CheckResult("Environment variables", PASS, detail)


def check_dependencies():
    """Check 2: Python dependencies can be imported."""
    modules = [
        ("websockets", "websockets"),
        ("requests", "requests"),
        ("dotenv", "python-dotenv"),
        ("aiohttp", "aiohttp"),
    ]

    missing = []
    for mod_name, pkg_name in modules:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append(pkg_name)

    # Optional deps
    optional_missing = []
    optional = [
        ("supabase", "supabase"),
        ("py_clob_client", "py-clob-client"),
        ("web3", "web3"),
    ]
    for mod_name, pkg_name in optional:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            optional_missing.append(pkg_name)

    if missing:
        return CheckResult(
            "Python dependencies",
            FAIL,
            f"Missing: {', '.join(missing)} — "
            "run: pip install -r requirements.txt",
        )

    detail = "All core imports OK"
    if optional_missing:
        detail += f" (optional missing: {', '.join(optional_missing)})"
    return CheckResult("Python dependencies", PASS, detail)


def check_database():
    """Check 3: SQLite database initializes and works."""
    try:
        from data import db
        db.init_db()
        state = db.get_bot_state()
        return CheckResult(
            "SQLite database",
            PASS,
            f"Tables OK, state has {len(state)} fields",
        )
    except Exception as e:
        return CheckResult(
            "SQLite database",
            FAIL,
            f"init_db() failed: {e}",
        )


async def check_binance_ws():
    """Check 4: Binance WebSocket connects and receives data."""
    try:
        from data.binance_ws import BinanceWebsocket
        from config import ASSETS

        ws = BinanceWebsocket()
        await ws.start()

        if not ws.is_connected():
            await ws.stop()
            return CheckResult(
                "Binance WebSocket",
                FAIL,
                "Failed to connect — check network/firewall",
            )

        # Wait for price data (up to 10s)
        deadline = time.time() + 10
        while time.time() < deadline:
            prices = ws.get_all_prices()
            assets_with_data = sum(
                1 for p in prices.values() if p > 0
            )
            if assets_with_data >= len(ASSETS):
                break
            await asyncio.sleep(0.5)

        prices = ws.get_all_prices()
        assets_with_data = sum(1 for p in prices.values() if p > 0)
        await ws.stop()

        if assets_with_data == 0:
            return CheckResult(
                "Binance WebSocket",
                FAIL,
                "Connected but no price data received",
            )

        price_str = ", ".join(
            f"{a.upper()}=${p:,.2f}"
            for a, p in prices.items() if p > 0
        )
        return CheckResult(
            "Binance WebSocket",
            PASS,
            f"{assets_with_data}/{len(ASSETS)} assets: {price_str}",
        )
    except Exception as e:
        return CheckResult(
            "Binance WebSocket",
            FAIL,
            f"Error: {e}",
        )


def check_market_discovery():
    """Check 5: Polymarket Gamma API returns markets."""
    try:
        from execution.market_discovery import (
            discover_all_markets, seconds_until_close,
        )

        markets = discover_all_markets()
        remaining = seconds_until_close()

        if not markets:
            return CheckResult(
                "Market discovery",
                PASS,
                "Gamma API reachable but no active markets "
                f"right now ({remaining:.0f}s left in window)",
            )

        names = ", ".join(
            f"{m.asset.upper()}" for m in markets.values()
        )
        return CheckResult(
            "Market discovery",
            PASS,
            f"Found {len(markets)} markets: {names} "
            f"({remaining:.0f}s left)",
        )
    except Exception as e:
        return CheckResult(
            "Market discovery",
            FAIL,
            f"Gamma API error: {e}",
        )


async def check_polymarket_ws():
    """Check 6: Polymarket CLOB WebSocket connects."""
    try:
        from data.polymarket_ws import PolymarketWebsocket

        ws = PolymarketWebsocket()
        await ws.start()

        connected = ws.is_connected()
        await ws.stop()

        if connected:
            return CheckResult(
                "CLOB WebSocket",
                PASS,
                "Connected to Polymarket CLOB WS",
            )
        return CheckResult(
            "CLOB WebSocket",
            FAIL,
            "Connection timed out",
        )
    except Exception as e:
        return CheckResult(
            "CLOB WebSocket",
            FAIL,
            f"Error: {e}",
        )


def check_signal_pipeline():
    """Check 7: Signal pipeline functions are callable."""
    try:
        from strategy.signals import (
            analyze_signals, MIN_SIGNAL_SCORE,
        )
        from strategy.regime import classify_from_binance_ws
        from strategy.kelly import calculate_kelly_bet
        from strategy.reversal import ReversalDetector

        return CheckResult(
            "Signal pipeline",
            PASS,
            f"All strategy modules loaded, "
            f"min score threshold: {MIN_SIGNAL_SCORE}",
        )
    except Exception as e:
        return CheckResult(
            "Signal pipeline",
            FAIL,
            f"Import error: {e}",
        )


def check_supabase():
    """Check 8: Supabase client connects."""
    from config import SUPABASE_URL, SUPABASE_KEY

    if not SUPABASE_URL or not SUPABASE_KEY:
        return CheckResult(
            "Supabase sync",
            SKIP,
            "Credentials not configured (optional)",
        )

    try:
        from supabase import create_client
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Try a lightweight query
        client.table("bot_state").select("*").limit(1).execute()
        return CheckResult(
            "Supabase sync",
            PASS,
            "Connected, bot_state table accessible",
        )
    except ImportError:
        return CheckResult(
            "Supabase sync",
            SKIP,
            "supabase package not installed",
        )
    except Exception as e:
        return CheckResult(
            "Supabase sync",
            FAIL,
            f"Connection failed: {e}",
        )


def check_clob_auth():
    """Check 9: CLOB client initializes and can query balance."""
    from config import POLY_PRIVATE_KEY

    if not POLY_PRIVATE_KEY:
        return CheckResult(
            "CLOB auth (live)",
            SKIP,
            "POLY_PRIVATE_KEY not set",
        )

    try:
        # Reset singleton so we test fresh initialization
        import execution.order as order_mod
        order_mod._client = None

        from execution.order import get_clob_client
        get_clob_client()

        from execution.balance import get_usdc_balance
        balance = get_usdc_balance()

        if balance == 0.0:
            return CheckResult(
                "CLOB auth (live)",
                PASS,
                "Authenticated, balance: $0.00 USDC "
                "(fund wallet to trade)",
            )

        return CheckResult(
            "CLOB auth (live)",
            PASS,
            f"Authenticated, balance: ${balance:.2f} USDC",
        )
    except Exception as e:
        return CheckResult(
            "CLOB auth (live)",
            FAIL,
            f"Auth failed: {e}",
        )


async def run_preflight(live_mode: bool):
    print()
    print("POLYMARKET BOT — PREFLIGHT CHECK")
    print("=" * 50)

    results = []

    # Sync checks (1-3)
    results.append(check_env_vars())
    results.append(check_dependencies())
    results.append(check_database())

    # Async checks (4, 6) in parallel
    binance_result, poly_ws_result = await asyncio.gather(
        check_binance_ws(),
        check_polymarket_ws(),
    )
    results.append(binance_result)

    # Sync check (5)
    results.append(check_market_discovery())

    # Polymarket WS result
    results.append(poly_ws_result)

    # Sync check (7)
    results.append(check_signal_pipeline())

    # Conditional checks (8-9)
    results.append(check_supabase())

    if live_mode:
        results.append(check_clob_auth())
    else:
        results.append(CheckResult(
            "CLOB auth (live)",
            SKIP,
            "Run with --live to test",
        ))

    # Print results
    for r in results:
        print(f"  {r.status} {r.name:<26s} {r.detail}")

    print("=" * 50)

    passed = sum(1 for r in results if r.status == PASS)
    failed = sum(1 for r in results if r.status == FAIL)
    skipped = sum(1 for r in results if r.status == SKIP)
    testable = passed + failed

    print(
        f"  RESULT: {passed}/{testable} passed, "
        f"{skipped} skipped"
    )

    if failed == 0:
        mode = "live trading" if live_mode else "paper trading"
        print(f"  Bot is ready for {mode}.")
    else:
        print("  Fix the failures above before running the bot.")

    print()
    return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Bot Preflight Check",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Include CLOB auth and balance checks",
    )
    args = parser.parse_args()

    ok = asyncio.run(run_preflight(args.live))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
