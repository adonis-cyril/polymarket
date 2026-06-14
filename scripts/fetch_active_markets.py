#!/usr/bin/env python3
"""
Fetch all active Polymarket markets from the Gamma API.

Usage:
    python scripts/fetch_active_markets.py
    python scripts/fetch_active_markets.py --output data/active_markets.json
    python scripts/fetch_active_markets.py --max-pages 2 --stats
    python scripts/fetch_active_markets.py --use-cache --cache-ttl 600
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.active_markets import (
    DEFAULT_CACHE_TTL,
    fetch_all_active_markets,
    load_cached_markets,
    markets_to_dicts,
    save_markets_cache,
)
from utils.logger import setup_logging

DEFAULT_CACHE_PATH = Path("data/cache/active_markets.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch all active Polymarket markets (Gamma API, read-only)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Write JSON export to this file",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"Cache file path (default: {DEFAULT_CACHE_PATH})",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Return cached result if fresh (see --cache-ttl)",
    )
    parser.add_argument(
        "--cache-ttl",
        type=float,
        default=DEFAULT_CACHE_TTL,
        help=f"Cache TTL in seconds (default: {DEFAULT_CACHE_TTL})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit pagination (for testing or partial syncs)",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived markets still marked active",
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=0.1,
        help="Seconds between API page requests (rate limiting)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print summary stats to stderr",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Print top N markets by 24h volume to stdout",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    setup_logging(level="DEBUG" if args.verbose else "INFO")

    result = None
    if args.use_cache:
        result = load_cached_markets(args.cache, ttl_seconds=args.cache_ttl)
        if result:
            logging.info(
                "Using cached markets (%d items, age %.0fs)",
                result.total,
                __import__("time").time() - result.fetched_at,
            )

    if result is None:
        def _on_page(page: int, batch: list, cursor: str | None) -> None:
            logging.info("Page %d: +%d markets (more=%s)", page, len(batch), bool(cursor))

        result = fetch_all_active_markets(
            include_archived=args.include_archived,
            max_pages=args.max_pages,
            page_delay=args.page_delay,
            on_page=_on_page if args.verbose else None,
        )
        save_markets_cache(args.cache, result)

    out_path = args.output or args.cache
    if args.output or not args.use_cache:
        save_markets_cache(out_path, result)

    if args.stats:
        print(
            f"Markets: {result.total} | Pages: {result.pages_fetched} | "
            f"Duration: {result.duration_seconds:.1f}s | "
            f"Truncated: {result.truncated}",
            file=sys.stderr,
        )

    if args.top > 0:
        ranked = sorted(result.markets, key=lambda m: m.volume_24hr, reverse=True)
        for m in ranked[: args.top]:
            print(
                f"{m.volume_24hr:>12.2f}  {m.slug[:60]:<60}  {m.question[:80]}",
            )
    elif not args.stats:
        print(json.dumps({
            "total": result.total,
            "pages_fetched": result.pages_fetched,
            "duration_seconds": round(result.duration_seconds, 2),
            "truncated": result.truncated,
            "cache": str(out_path),
        }, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
