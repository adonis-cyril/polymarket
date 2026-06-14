#!/usr/bin/env python3
"""
Refresh the cached Polymarket active-market catalog.

Requires execution.active_markets.fetch_all_active_markets (Gamma paginator).

Usage:
    python scripts/refresh_markets.py
    python scripts/refresh_markets.py --force
    python scripts/refresh_markets.py --status
    python scripts/refresh_markets.py --slug-contains btc-updown
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from data import db
from data.market_registry import get_active_markets, get_cache_status, refresh_active_markets


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh cached Polymarket active markets")
    parser.add_argument("--force", action="store_true", help="Bypass TTL and fetch from Gamma")
    parser.add_argument("--status", action="store_true", help="Show cache status only")
    parser.add_argument("--slug-contains", default="", help="Filter results by slug substring")
    parser.add_argument("--limit", type=int, default=0, help="Limit printed results (0 = all)")
    args = parser.parse_args()

    db.init_db()

    if args.status:
        status = get_cache_status()
        for key, value in status.items():
            print(f"{key}: {value}")
        return 0

    try:
        if args.force:
            result = refresh_active_markets(force=True)
            print(
                f"Refreshed {result.count} markets via {result.source} "
                f"in {result.duration_seconds:.1f}s "
                f"(upserted={result.inserted_or_updated}, deactivated={result.deactivated})"
            )
        records = get_active_markets(
            force_refresh=args.force,
            event_slug_contains=args.slug_contains,
            limit=args.limit or None,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Active markets available: {len(records)}")
    for record in records[: min(len(records), 20)]:
        print(f"- {record.event_slug or record.market_slug} | {record.question[:80]}")
    if len(records) > 20:
        print(f"... and {len(records) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
