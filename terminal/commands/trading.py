"""Trading command handlers — buy, sell, cancel, positions."""

from __future__ import annotations

from terminal.commands.registry import CommandContext, CommandRegistry
from terminal.core.interfaces import CommandResult
from terminal.engine.trading import OrderRequest, TradingEngine
from terminal.events import EventType
from terminal.state import LeftView

_engine = TradingEngine()


def get_trading_engine() -> TradingEngine:
    return _engine


def register_trading_commands(registry: CommandRegistry) -> None:
    registry.register("buy", "Buy flow: buy [--live] [--side up|down] [--size N]", _cmd_buy)
    registry.register("sell", "Sell flow: sell [--live] [--side up|down] [--shares N] [--urgent]", _cmd_sell)
    registry.register("cancel", "Cancel orders: cancel [--live] [--order-id ID]", _cmd_cancel)
    registry.register("positions", "Show/focus positions in left pane", _cmd_positions)


def _parse_flags(args: list[str]) -> dict:
    flags: dict = {"live": False, "urgent": False, "side": "up", "size": 2.0, "shares": None, "order_id": None}
    i = 0
    while i < len(args):
        a = args[i].lower()
        if a in ("--live", "-live"):
            flags["live"] = True
        elif a == "--urgent":
            flags["urgent"] = True
        elif a == "--side" and i + 1 < len(args):
            flags["side"] = args[i + 1]
            i += 1
        elif a == "--size" and i + 1 < len(args):
            try:
                flags["size"] = float(args[i + 1])
            except ValueError:
                pass
            i += 1
        elif a == "--shares" and i + 1 < len(args):
            try:
                flags["shares"] = float(args[i + 1])
            except ValueError:
                pass
            i += 1
        elif a == "--order-id" and i + 1 < len(args):
            flags["order_id"] = args[i + 1]
            i += 1
        elif a.replace(".", "", 1).isdigit():
            flags["size"] = float(a)
        i += 1
    return flags


async def _emit_activity(ctx: CommandContext, message: str, level: str = "INFO") -> None:
    await ctx.bus.emit(
        EventType.ACTIVITY_EVENT,
        {"message": message, "level": level, "source": "trade"},
    )


async def _cmd_buy(ctx: CommandContext) -> CommandResult:
    flags = _parse_flags(ctx.args)
    req = OrderRequest(side=flags["side"], size_usdc=flags["size"], live=flags["live"])
    result = await _engine.buy(req)
    await _emit_activity(ctx, result.message, "INFO" if result.success else "WARNING")
    return result


async def _cmd_sell(ctx: CommandContext) -> CommandResult:
    flags = _parse_flags(ctx.args)
    req = OrderRequest(
        side=flags["side"],
        shares=flags["shares"],
        urgent=flags["urgent"],
        live=flags["live"],
    )
    result = await _engine.sell(req)
    await _emit_activity(ctx, result.message, "INFO" if result.success else "WARNING")
    return result


async def _cmd_cancel(ctx: CommandContext) -> CommandResult:
    flags = _parse_flags(ctx.args)
    req = OrderRequest(live=flags["live"], order_id=flags["order_id"])
    result = await _engine.cancel(req)
    await _emit_activity(ctx, result.message, "INFO" if result.success else "WARNING")
    return result


async def _cmd_positions(ctx: CommandContext) -> CommandResult:
    ctx.store.set_left_view(LeftView.POSITIONS)
    await ctx.bus.emit(EventType.LEFT_VIEW_CHANGED, {"view": LeftView.POSITIONS.value})
    count = len(ctx.store.state.positions)
    if count:
        lines = [f"Open positions ({count}):"]
        for p in ctx.store.state.positions[:8]:
            lines.append(
                f"  {p.outcome} {p.size:.1f} @ {p.avg_price:.3f} "
                f"val=${p.current_value:.2f} pnl=${p.pnl:+.2f}"
            )
        return CommandResult(True, "\n".join(lines))
    return CommandResult(True, "No open positions — showing recent trades in left pane")
