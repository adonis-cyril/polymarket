#!/usr/bin/env python3
"""
Binance REST + WebSocket connectivity check for spot market data.

Verifies klines, ticker price, and live miniTicker/kline streams per asset.
Public endpoints only — no API key required.

Usage:
    python scripts/check_binance.py
    python scripts/check_binance.py --quick
    python scripts/check_binance.py --assets btc,eth,sol
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import logging

logging.basicConfig(level=logging.ERROR)

import requests

from config import BINANCE_SYMBOLS as CONFIG_BINANCE_SYMBOLS
from data.historical import BINANCE_KLINES_URL, HistoricalCandle

DEFAULT_ASSETS = ["btc", "eth", "sol"]
DEFAULT_BINANCE_SYMBOLS = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "sol": "SOLUSDT",
}
BINANCE_PRICE_URL = "https://data-api.binance.vision/api/v3/ticker/price"
WS_TIMEOUT = 10.0

WIDTH = 72

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"


@dataclass
class Row:
    label: str
    value: str
    status: str  # ok | warn | fail | skip


@dataclass
class AssetResult:
    asset: str
    rows: list[Row] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(r.status == "fail" for r in self.rows)


def _status_icon(status: str) -> str:
    return {
        "ok": f"{GREEN}●{RESET}",
        "warn": f"{YELLOW}●{RESET}",
        "fail": f"{RED}●{RESET}",
        "skip": f"{DIM}○{RESET}",
    }.get(status, " ")


def _line(char: str = "─") -> str:
    return f"{DIM}{char * WIDTH}{RESET}"


def _header(title: str) -> None:
    print()
    print(f"  {BOLD}{CYAN}{title}{RESET}")
    print(f"  {_line()}")


def _row(label: str, value: str, status: str = "info", indent: int = 2) -> None:
    icon = _status_icon(status)
    print(f"{' ' * indent}{icon} {label:<30} {value}")


def _section_box(title: str) -> None:
    print()
    inner = f" {title} "
    pad = max(0, WIDTH - len(title) - 2)
    left = pad // 2
    right = pad - left
    print(f"{BOLD}{CYAN}╔{'═' * left}{inner}{'═' * right}╗{RESET}")
    print(f"{BOLD}{CYAN}║{' ' * WIDTH}║{RESET}")
    print(f"{BOLD}{CYAN}╚{'═' * WIDTH}╝{RESET}")


def _parse_assets(raw: Optional[str]) -> list[str]:
    if not raw:
        return list(DEFAULT_ASSETS)
    assets = [a.strip().lower() for a in raw.split(",") if a.strip()]
    if not assets:
        raise ValueError("No assets specified")
    return assets


def _resolve_symbols(assets: list[str]) -> dict[str, str]:
    symbols = dict(DEFAULT_BINANCE_SYMBOLS)
    symbols.update(CONFIG_BINANCE_SYMBOLS)
    missing = [a for a in assets if a not in symbols]
    if missing:
        raise ValueError(f"Unknown asset(s): {', '.join(missing)}")
    return {a: symbols[a] for a in assets}


def _apply_binance_scope(assets: list[str], symbols: dict[str, str]) -> None:
    """Point config + binance_ws at the assets under test."""
    import config
    import data.binance_ws as bw
    import data.historical as hist

    config.ASSETS = list(assets)
    config.BINANCE_SYMBOLS = dict(symbols)
    bw.ASSETS = list(assets)
    bw.BINANCE_SYMBOLS = dict(symbols)
    hist.BINANCE_SYMBOLS = dict(symbols)


def _closed_candles(candles: list[HistoricalCandle]) -> list[HistoricalCandle]:
    now_ms = int(time.time() * 1000)
    return [c for c in candles if c.close_time <= now_ms]


def _format_ohlcv(candle: HistoricalCandle) -> str:
    return (
        f"O={candle.open:,.2f}  H={candle.high:,.2f}  "
        f"L={candle.low:,.2f}  C={candle.close:,.2f}  V={candle.volume:,.4f}"
    )


def check_rest_klines(asset: str, symbols: dict[str, str]) -> Row:
    symbol = symbols[asset]
    t0 = time.perf_counter()
    try:
        resp = requests.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": "1m", "limit": 6},
            timeout=10,
        )
        resp.raise_for_status()
        raw = [
            HistoricalCandle(
                open_time=k[0],
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                close_time=k[6],
            )
            for k in resp.json()
        ]

        closed = _closed_candles(raw)
        if len(closed) < 5:
            ms = int((time.perf_counter() - t0) * 1000)
            return Row(
                "REST klines",
                f"only {len(closed)} closed candle(s) ({ms} ms)",
                "fail",
            )

        latest = closed[-1]
        ms = int((time.perf_counter() - t0) * 1000)
        return Row(
            "REST klines",
            f"5 closed 1m bars ({ms} ms)  latest {_format_ohlcv(latest)}",
            "ok",
        )
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return Row("REST klines", f"failed ({ms} ms): {exc}", "fail")


def check_rest_price(asset: str, symbols: dict[str, str]) -> Row:
    symbol = symbols[asset]
    t0 = time.perf_counter()
    try:
        resp = requests.get(
            BINANCE_PRICE_URL,
            params={"symbol": symbol},
            timeout=10,
        )
        ms = int((time.perf_counter() - t0) * 1000)
        resp.raise_for_status()
        payload = resp.json()
        price = float(payload["price"])
        return Row(
            "REST ticker price",
            f"${price:,.2f}  ({ms} ms)",
            "ok",
        )
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return Row("REST ticker price", f"failed ({ms} ms): {exc}", "fail")


async def check_websocket(
    assets: list[str],
    symbols: dict[str, str],
) -> dict[str, list[Row]]:
    from data.binance_ws import BinanceWebsocket

    _apply_binance_scope(assets, symbols)
    ws = BinanceWebsocket()
    results: dict[str, list[Row]] = {a: [] for a in assets}

    t0 = time.perf_counter()
    try:
        await ws.start()

        if not ws.is_connected():
            detail = f"not connected ({int((time.perf_counter() - t0) * 1000)} ms)"
            for asset in assets:
                results[asset].append(Row("WebSocket connect", detail, "fail"))
                results[asset].append(Row("WebSocket price", "skipped — no connection", "fail"))
                results[asset].append(Row("WebSocket OHLCV", "skipped — no connection", "fail"))
            return results

        connect_ms = int((time.perf_counter() - t0) * 1000)
        for asset in assets:
            results[asset].append(
                Row("WebSocket connect", f"combined miniTicker + kline_1m ({connect_ms} ms)", "ok"),
            )

        baseline_prices = {a: ws.get_price(a) for a in assets}
        deadline = time.time() + WS_TIMEOUT
        live_assets: set[str] = set()

        while time.time() < deadline and len(live_assets) < len(assets):
            for asset in assets:
                if asset in live_assets:
                    continue
                price = ws.get_price(asset)
                last_update = ws._data[asset].last_update
                fresh = last_update > 0 and (time.time() - last_update) <= 5.0
                changed = baseline_prices[asset] > 0 and price != baseline_prices[asset]
                if price > 0 and (fresh or changed or baseline_prices[asset] == 0):
                    live_assets.add(asset)
            if len(live_assets) < len(assets):
                await asyncio.sleep(0.25)

        for asset in assets:
            price = ws.get_price(asset)
            if asset in live_assets and price > 0:
                elapsed = int((time.perf_counter() - t0) * 1000)
                results[asset].append(
                    Row("WebSocket price", f"${price:,.2f}  live update ({elapsed} ms)", "ok"),
                )
            else:
                results[asset].append(
                    Row(
                        "WebSocket price",
                        f"no update within {int(WS_TIMEOUT)}s",
                        "fail",
                    ),
                )

            closed = ws.get_candles(asset, count=5)
            if closed:
                latest = closed[-1]
                source = "seeded + live" if len(closed) >= 2 else "buffer"
                results[asset].append(
                    Row(
                        "WebSocket OHLCV",
                        f"{len(closed)} closed 1m bar(s) ({source})  latest {_format_ohlcv(latest)}",
                        "ok",
                    ),
                )
            else:
                results[asset].append(
                    Row("WebSocket OHLCV", "no closed 1m candles in buffer", "fail"),
                )

    except Exception as exc:
        for asset in assets:
            if not results[asset]:
                results[asset].append(Row("WebSocket", str(exc), "fail"))
    finally:
        await ws.stop()

    return results


def check_asset_rest(asset: str, symbols: dict[str, str]) -> AssetResult:
    symbol = symbols[asset]
    result = AssetResult(asset=asset)
    result.rows.append(
        Row("Symbol", symbol, "info"),
    )
    result.rows.append(check_rest_klines(asset, symbols))
    result.rows.append(check_rest_price(asset, symbols))
    return result


def print_asset_section(asset: str, rows: list[Row]) -> None:
    _header(f"{asset.upper()} — Binance spot")
    for row in rows:
        _row(row.label, row.value, row.status)


def print_summary(all_rows: list[Row]) -> None:
    fails = sum(1 for r in all_rows if r.status == "fail")
    warns = sum(1 for r in all_rows if r.status == "warn")

    print()
    print(f"  {_line('═')}")
    if fails:
        verdict = f"{RED}{BOLD}ISSUES FOUND{RESET} — {fails} check(s) failed"
    elif warns:
        verdict = f"{YELLOW}{BOLD}OK WITH WARNINGS{RESET} — {warns} item(s) need attention"
    else:
        verdict = f"{GREEN}{BOLD}ALL CLEAR{RESET}"

    print(f"  {BOLD}SUMMARY:{RESET} {verdict}")
    print(f"  {DIM}→ Public REST: {BINANCE_KLINES_URL}{RESET}")
    print(f"  {DIM}→ WebSocket: combined miniTicker + kline_1m per asset{RESET}")
    print(f"  {_line('═')}")
    print()


async def run(quick: bool, assets: list[str]) -> int:
    now = time.strftime("%Y-%m-%d %H:%M:%S %Z").strip() or time.strftime("%Y-%m-%d %H:%M:%S")
    symbols = _resolve_symbols(assets)

    print()
    _section_box("BINANCE — REST & LIVE OHLCV CHECK")
    asset_label = ", ".join(a.upper() for a in assets)
    mode = "REST only (--quick)" if quick else "REST + WebSocket"
    print(f"  {DIM}{now}{RESET}  ·  assets: {asset_label}  ·  {mode}")

    all_rows: list[Row] = []
    rest_by_asset = {a: check_asset_rest(a, symbols) for a in assets}

    ws_by_asset: dict[str, list[Row]] = {}
    if quick:
        skip_rows = [
            Row("WebSocket connect", "skipped (--quick)", "skip"),
            Row("WebSocket price", "skipped (--quick)", "skip"),
            Row("WebSocket OHLCV", "skipped (--quick)", "skip"),
        ]
        ws_by_asset = {a: list(skip_rows) for a in assets}
    else:
        ws_by_asset = await check_websocket(assets, symbols)

    for asset in assets:
        rows = list(rest_by_asset[asset].rows)
        rows.extend(ws_by_asset[asset])
        print_asset_section(asset, rows)
        all_rows.extend(rows)

    print_summary(all_rows)
    return 1 if any(r.status == "fail" for r in all_rows) else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Binance REST + WebSocket connectivity check (public market data)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="REST only — skip WebSocket probes",
    )
    parser.add_argument(
        "--assets",
        default=None,
        help=f"Comma-separated assets to check (default: {','.join(DEFAULT_ASSETS)})",
    )
    args = parser.parse_args()

    try:
        assets = _parse_assets(args.assets)
        _resolve_symbols(assets)
    except ValueError as exc:
        print(f"{RED}Error:{RESET} {exc}", file=sys.stderr)
        sys.exit(1)

    code = asyncio.run(run(quick=args.quick, assets=assets))
    sys.exit(code)


if __name__ == "__main__":
    main()
