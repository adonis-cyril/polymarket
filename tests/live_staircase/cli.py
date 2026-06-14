"""CLI entry point for the live staircase test suite."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import argparse
import sys

from tests.live_staircase.commands import (
    cmd_account,
    cmd_buy,
    cmd_cancel,
    cmd_discover,
    cmd_last_minute,
    cmd_run_staircase,
    cmd_sell,
    cmd_status,
    cmd_stop_loss,
    cmd_take_profit,
)
from tests.live_staircase.config import STAIRCASE_DEFAULT_SIZE
from tests.live_staircase.helpers import RunContext
from tests.live_staircase.log import setup_logging


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--live", action="store_true",
        help="Submit real orders (default: dry-run)",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmations")
    parser.add_argument("--auto", action="store_true", help="Run staircase without prompts")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    parser.add_argument(
        "--size", type=float, default=None,
        help=f"Order size in USDC (default: ${STAIRCASE_DEFAULT_SIZE:.2f})",
    )
    parser.add_argument("--side", choices=["up", "down"], default="up", help="UP or DOWN token")
    parser.add_argument("--shares", type=float, default=None, help="Shares for sell stairs")
    parser.add_argument("--entry-price", type=float, default=None, help="Entry price for TP/SL")
    parser.add_argument("--tp-pct", type=float, default=None, help="Take-profit %% (e.g. 0.02)")
    parser.add_argument("--sl-pct", type=float, default=None, help="Stop-loss %% (e.g. 0.015)")
    parser.add_argument("--order-id", default=None, help="Single order ID to cancel")
    parser.add_argument("--min-secs", type=float, default=None, help="Last-minute min seconds left")
    parser.add_argument("--max-secs", type=float, default=None, help="Last-minute max seconds left")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    _add_common_args(common)

    parser = argparse.ArgumentParser(
        description="Polymarket live staircase — manual on-demand execution tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m tests.live_staircase discover\n"
            "  python -m tests.live_staircase account --live\n"
            "  python -m tests.live_staircase buy --side up --size 2.00 --live\n"
            "  python -m tests.live_staircase run-staircase --auto\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", parents=[common], help="Find current BTC 5m market and prices")
    sub.add_parser(
        "account", parents=[common],
        help="USDC balance, allowances, funder/signer, open orders",
    )
    sub.add_parser("status", parents=[common], help="Balance, orders, positions")
    sub.add_parser("buy", parents=[common], help="Place buy order")

    sell_p = sub.add_parser("sell", parents=[common], help="Place sell to close position")
    sell_p.add_argument("--urgent", action="store_true", help="Market sell immediately")

    sub.add_parser("exit", parents=[common], help="Urgent market sell (alias for sell --urgent)")
    sub.add_parser("take-profit", parents=[common], help="Place take-profit limit sell")
    sub.add_parser("stop-loss", parents=[common], help="Place stop-loss or market sell if breached")
    sub.add_parser("cancel", parents=[common], help="Cancel open order(s)")
    sub.add_parser("last-minute", parents=[common], help="Snipe entry near window close")
    sub.add_parser("run-staircase", parents=[common], help="Run stairs in sequence with prompts")

    return parser


def ctx_from_args(args: argparse.Namespace) -> RunContext:
    return RunContext(
        live=args.live,
        yes=args.yes,
        auto=args.auto,
        size=args.size if args.size is not None else STAIRCASE_DEFAULT_SIZE,
        side=args.side,
        shares=args.shares,
        entry_price=args.entry_price,
        tp_pct=args.tp_pct,
        sl_pct=args.sl_pct,
        order_id=args.order_id,
        min_secs=args.min_secs or 15.0,
        max_secs=args.max_secs or 60.0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging("DEBUG" if args.verbose else "INFO")
    ctx = ctx_from_args(args)

    handlers = {
        "discover": cmd_discover,
        "account": cmd_account,
        "status": cmd_status,
        "buy": cmd_buy,
        "sell": lambda c: cmd_sell(c, urgent=getattr(args, "urgent", False)),
        "exit": lambda c: cmd_sell(c, urgent=True),
        "take-profit": cmd_take_profit,
        "stop-loss": cmd_stop_loss,
        "cancel": cmd_cancel,
        "last-minute": cmd_last_minute,
        "run-staircase": cmd_run_staircase,
    }

    handler = handlers.get(args.command)
    if not handler:
        parser.print_help()
        return 2

    return handler(ctx)


if __name__ == "__main__":
    sys.exit(main())
