#!/usr/bin/env python3
"""
Polymarket connection & account status — formatted terminal report.

Checks ISP/DNS, Gamma + CLOB REST, CLOB WebSocket, wallet auth, and USDC balance.

Usage:
    python scripts/check_status.py           # Full report
    python scripts/check_status.py --quick   # Skip WebSocket (faster)
    python scripts/check_status.py --dns-only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

# Project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

# Suppress noisy connectivity warnings during the formatted report
import logging

logging.basicConfig(level=logging.ERROR)

from utils.polymarket_connectivity import (  # noqa: E402
    POLYMARKET_HOSTS,
    clob_get,
    detect_dns_hijack,
    gamma_get,
    install_dns_patch,
    resolve_public,
    resolve_system,
)

WIDTH = 72

# ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
WHITE = "\033[97m"


@dataclass
class Row:
    label: str
    value: str
    status: str  # ok | warn | fail | skip | info


def _status_icon(status: str) -> str:
    return {
        "ok": f"{GREEN}●{RESET}",
        "warn": f"{YELLOW}●{RESET}",
        "fail": f"{RED}●{RESET}",
        "skip": f"{DIM}○{RESET}",
        "info": f"{CYAN}●{RESET}",
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


def check_dns_rows() -> tuple[list[Row], bool]:
    """Return DNS rows and whether any hijack was detected."""
    rows: list[Row] = []
    hijacked = False

    for host in POLYMARKET_HOSTS:
        system_ips = resolve_system(host)
        public_ips = resolve_public(host)
        hijack_msg = detect_dns_hijack(host)

        sys_ip = system_ips[0] if system_ips else "—"
        pub_ip = public_ips[0] if public_ips else "—"

        if hijack_msg:
            hijacked = True
            rows.append(Row(host[:32], f"sys {sys_ip} → pub {pub_ip}", "warn"))
            rows.append(Row("  └ hijack", "ISP returns block-page IP (not Cloudflare)", "warn"))
        elif not system_ips and not public_ips:
            rows.append(Row(host, "unresolvable", "fail"))
        elif not system_ips:
            rows.append(Row(host, f"system fail, public {pub_ip}", "warn"))
        else:
            match = set(system_ips) & set(public_ips)
            detail = sys_ip if match else f"{sys_ip} (public {pub_ip})"
            rows.append(Row(host, detail, "ok" if match else "warn"))

    auto_fix = os.getenv("POLYMARKET_DNS_AUTO_FIX", "true").lower() in ("true", "1", "yes")
    dns_servers = os.getenv("POLYMARKET_DNS_SERVERS", "1.1.1.1, 8.8.8.8 (default)")

    if hijacked:
        if auto_fix:
            rows.append(Row("Auto-bypass", f"POLYMARKET_DNS_AUTO_FIX=true ({dns_servers})", "ok"))
        else:
            rows.append(Row("Auto-bypass", "disabled — set POLYMARKET_DNS_AUTO_FIX=true or use VPN", "fail"))
    else:
        rows.append(Row("ISP / DNS", "No hijack detected on Polymarket hosts", "ok"))

    return rows, hijacked


def check_http_endpoints() -> list[Row]:
    rows: list[Row] = []
    install_dns_patch()

    endpoints = (
        ("Gamma REST", gamma_get, "/events", {"limit": 1}),
        ("CLOB REST", clob_get, "/time", None),
    )
    for name, fn, path, params in endpoints:
        t0 = time.perf_counter()
        try:
            resp = fn(path, params=params)
            ms = int((time.perf_counter() - t0) * 1000)
            if resp.ok:
                rows.append(Row(name, f"HTTP {resp.status_code}  ({ms} ms)", "ok"))
            else:
                rows.append(Row(name, f"HTTP {resp.status_code}  ({ms} ms)", "fail"))
        except Exception as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            rows.append(Row(name, f"failed ({ms} ms): {exc}", "fail"))

    return rows


async def check_clob_ws() -> Row:
    from data.polymarket_ws import PolymarketWebsocket

    install_dns_patch()
    token_id = None
    try:
        resp = clob_get("/sampling-markets", params={"limit": 5})
        if resp.ok:
            payload = resp.json()
            markets = payload if isinstance(payload, list) else payload.get("data", [])
            for market in markets:
                for token in market.get("tokens", []):
                    token_id = token.get("token_id")
                    if token_id:
                        break
                if token_id:
                    break
    except Exception:
        pass

    if not token_id:
        return Row("CLOB WebSocket", "no token for subscription test", "fail")

    ws = PolymarketWebsocket()
    t0 = time.perf_counter()
    try:
        await ws.start()
        await ws.subscribe(token_id)
        connected = ws.is_connected()
        if connected:
            await asyncio.sleep(3)
            connected = ws.is_connected()
        ms = int((time.perf_counter() - t0) * 1000)
        book = ws.get_order_book(token_id) if connected else None
        await ws.stop()

        if connected:
            detail = f"connected ({ms} ms)"
            if book and book.best_bid > 0 and book.best_ask < 1:
                detail += f"  bid={book.best_bid:.3f}  ask={book.best_ask:.3f}"
            return Row("CLOB WebSocket", detail, "ok")
        return Row("CLOB WebSocket", f"timeout ({ms} ms)", "fail")
    except Exception as exc:
        await ws.stop()
        return Row("CLOB WebSocket", str(exc), "fail")


def _short_addr(addr: str) -> str:
    if addr.startswith("0x") and len(addr) > 12:
        return f"{addr[:6]}…{addr[-4:]}"
    return addr or "—"


_SIGNATURE_TYPE_LABELS = {
    0: "EOA",
    1: "POLY_PROXY",
    2: "POLY_GNOSIS_SAFE",
    3: "DEPOSIT_WALLET",
}


def check_account() -> list[Row]:
    from config import POLY_FUNDER_ADDRESS, POLY_PRIVATE_KEY, POLY_SIGNATURE_TYPE

    rows: list[Row] = []

    if not POLY_PRIVATE_KEY:
        rows.append(Row("Private key", "POLY_PRIVATE_KEY not set in .env", "skip"))
        rows.append(Row("USDC balance", "skipped — no credentials", "skip"))
        rows.append(Row("Open positions", "skipped — no credentials", "skip"))
        return rows

    rows.append(Row("Funder (positions)", _short_addr(POLY_FUNDER_ADDRESS), "info"))

    try:
        import execution.order as order_mod

        order_mod._client = None
        from execution.order import get_clob_client

        client = get_clob_client()
        signer = client.get_address()
        rows.append(Row("Signer (EOA)", _short_addr(signer), "info"))
        if POLY_FUNDER_ADDRESS and signer:
            same = signer.lower() == POLY_FUNDER_ADDRESS.lower()
            sig_label = _SIGNATURE_TYPE_LABELS.get(
                POLY_SIGNATURE_TYPE, f"type {POLY_SIGNATURE_TYPE}",
            )
            if same:
                mapping = f"signer = funder ({sig_label})"
            else:
                mapping = f"signer controls funder ({sig_label})"
            rows.append(Row("Wallet mapping", mapping, "ok" if not same else "info"))
        rows.append(Row("CLOB auth", "API credentials derived OK", "ok"))

        from execution.balance import get_position_value_usd, get_usdc_balance, get_positions

        balance = get_usdc_balance()
        position_value = get_position_value_usd()
        if balance > 0:
            rows.append(Row("CLOB USDC (tradable)", f"${balance:,.2f}", "ok"))
        else:
            rows.append(Row("CLOB USDC (tradable)", "$0.00", "warn"))

        if position_value is not None:
            pos_status = "ok" if position_value > 0 else "info"
            rows.append(Row(
                "Positions (data-api)",
                f"${position_value:,.2f} mark-to-market",
                pos_status,
            ))
            total = balance + position_value
            total_status = "ok" if total > 0 else "warn"
            rows.append(Row(
                "Total (CLOB cash + positions)",
                f"${total:,.2f}",
                total_status,
            ))

        positions = get_positions()
        n = len(positions) if positions else 0
        pos_count_status = "ok" if n > 0 else "info"
        rows.append(Row("Open positions (count)", str(n), pos_count_status))

        if balance == 0 and (position_value is None or position_value == 0):
            rows.append(Row(
                "Hint",
                "Set POLY_FUNDER_ADDRESS to deposit wallet from Settings (not Rabby EOA)",
                "warn",
            ))
        elif n == 0 and position_value and position_value > 0:
            rows.append(Row(
                "Hint",
                "Position value > 0 but position list empty — data-api may be lagging",
                "warn",
            ))
    except Exception as exc:
        rows.append(Row("CLOB auth", f"failed: {exc}", "fail"))
        rows.append(Row("USDC balance", "unavailable", "fail"))
        rows.append(Row("Open positions", "unavailable", "fail"))

    return rows


def print_rows(rows: list[Row]) -> None:
    for r in rows:
        _row(r.label, r.value, r.status)


def print_summary(
    dns_hijacked: bool,
    all_rows: list[Row],
) -> None:
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

    extra = []
    if dns_hijacked:
        extra.append("ISP DNS hijack detected (auto-bypass may be active)")
    patch_active = install_dns_patch()
    if patch_active:
        extra.append("DNS override patch applied for this session")

    print(f"  {BOLD}SUMMARY:{RESET} {verdict}")
    for note in extra:
        print(f"  {DIM}→ {note}{RESET}")
    print(f"  {_line('═')}")
    print()


async def run(quick: bool, dns_only: bool) -> int:
    now = time.strftime("%Y-%m-%d %H:%M:%S %Z").strip() or time.strftime("%Y-%m-%d %H:%M:%S")

    print()
    _section_box("POLYMARKET — CONNECTION & ACCOUNT STATUS")
    print(f"  {DIM}{now}{RESET}  ·  project: {os.path.basename(os.path.dirname(os.path.dirname(__file__)))}")

    all_rows: list[Row] = []

    _header("DNS / ISP (Polymarket hosts)")
    dns_rows, hijacked = check_dns_rows()
    print_rows(dns_rows)
    all_rows.extend(dns_rows)

    if dns_only:
        print_summary(hijacked, all_rows)
        return 1 if any(r.status == "fail" for r in dns_rows) else 0

    _header("API connectivity")
    http_rows = check_http_endpoints()
    print_rows(http_rows)
    all_rows.extend(http_rows)

    if not quick:
        _header("Live data")
        ws_row = await check_clob_ws()
        print_rows([ws_row])
        all_rows.append(ws_row)
    else:
        _row("CLOB WebSocket", "skipped (--quick)", "skip")

    _header("Account (CLOB wallet)")
    acct_rows = check_account()
    print_rows(acct_rows)
    all_rows.extend(acct_rows)

    print_summary(hijacked, all_rows)

    return 1 if any(r.status == "fail" for r in all_rows) else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Formatted Polymarket connection & account status report",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Skip CLOB WebSocket test (faster)",
    )
    parser.add_argument(
        "--dns-only", action="store_true",
        help="Only check ISP/DNS resolution",
    )
    args = parser.parse_args()
    code = asyncio.run(run(quick=args.quick, dns_only=args.dns_only))
    sys.exit(code)


if __name__ == "__main__":
    main()
