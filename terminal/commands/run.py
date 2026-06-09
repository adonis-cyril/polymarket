"""Run and stop strategy commands."""

from __future__ import annotations

from terminal.commands.registry import CommandContext, CommandRegistry
from terminal.core.interfaces import CommandResult
from terminal.events import EventType
from terminal.services.bot_control import BotControlService
from terminal.strategies.registry import get_strategy_registry


def register_run_commands(registry: CommandRegistry, bot_control: BotControlService) -> None:
    registry.register("run", "Start a strategy: run --strategy <name> [--live] [--hft]", _make_run(bot_control))
    registry.register("stop", "Stop all running bots/strategies", _make_stop(bot_control))


def _make_run(bot_control: BotControlService):
    async def _cmd_run(ctx: CommandContext) -> CommandResult:
        strategy_name, live, hft, list_only = _parse_run_args(ctx.args)

        if list_only or strategy_name is None:
            msg = get_strategy_registry().format_list()
            info = bot_control.process_info
            if info.running:
                msg += f"\n\nCurrently running: {info.strategy} ({info.mode}, pid {info.pid})"
            return CommandResult(True, msg)

        entry = get_strategy_registry().get(strategy_name)
        if entry is None:
            names = ", ".join(get_strategy_registry().list_names())
            return CommandResult(
                False,
                f"Unknown strategy: {strategy_name}\nAvailable: {names}",
            )

        mode = "live" if live else entry.default_mode
        msg = await bot_control.start_strategy(
            entry,
            mode=mode,
            hft_override=hft,
        )
        ctx.store.set_mode(mode, entry.name)
        await ctx.bus.emit(EventType.NOTIFICATION, {"message": msg})
        await ctx.bus.emit(EventType.STATE_UPDATED, {})
        return CommandResult(True, msg)

    return _cmd_run


async def stop_all_bots(bot_control: BotControlService, ctx: CommandContext) -> CommandResult:
    """Stop running bot subprocesses and queue PAUSE when possible."""
    lines: list[str] = []

    try:
        pause_msg = await bot_control.send_admin_command("PAUSE")
        if not pause_msg.startswith("Failed"):
            lines.append(pause_msg)
    except Exception:
        pass

    msg = await bot_control.stop_bot()
    lines.append(msg)
    ctx.store.set_mode("paper", "")
    await ctx.bus.emit(EventType.NOTIFICATION, {"message": msg})
    await ctx.bus.emit(EventType.STATE_UPDATED, {})
    return CommandResult(True, "\n".join(lines))


def _make_stop(bot_control: BotControlService):
    async def _cmd_stop(ctx: CommandContext) -> CommandResult:
        return await stop_all_bots(bot_control, ctx)

    return _cmd_stop


def _parse_run_args(args: list[str]) -> tuple[str | None, bool, bool, bool]:
    """Return (strategy_name, live, hft, list_only). strategy_name None means list."""
    strategy_name: str | None = None
    live = False
    hft = False
    list_only = False
    saw_strategy_flag = False

    i = 0
    while i < len(args):
        arg = args[i].lower()
        if arg in ("--strategy", "-s"):
            saw_strategy_flag = True
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                strategy_name = args[i + 1]
                i += 2
            else:
                list_only = True
                i += 1
        elif arg.startswith("--strategy="):
            saw_strategy_flag = True
            _, _, val = args[i].partition("=")
            if val:
                strategy_name = val
            else:
                list_only = True
            i += 1
        elif arg == "--live":
            live = True
            i += 1
        elif arg == "--hft":
            hft = True
            i += 1
        else:
            i += 1

    if not args or (saw_strategy_flag and list_only):
        return None, live, hft, True
    if not saw_strategy_flag and not strategy_name:
        return None, live, hft, True
    return strategy_name, live, hft, False
