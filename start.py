#!/usr/bin/env python3
"""
Polymarket primary entry point — password gate + terminal workstation.

Usage:
    python start.py
    uv run python start.py
    uv run polymarket
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Polymarket Trading Workstation (TUI)",
    )
    parser.add_argument(
        "--skip-auth",
        action="store_true",
        help="Skip password gate (dev only)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Password retry limit (default: 3)",
    )
    args = parser.parse_args(argv)

    if not args.skip_auth:
        from terminal.auth import authenticate_interactive

        if not authenticate_interactive(max_attempts=args.max_attempts):
            return 1

    from terminal.app import PolymarketTUI

    try:
        app = PolymarketTUI()
        app.run()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
