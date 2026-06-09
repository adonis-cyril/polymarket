"""Extended command handlers — bot control, config, tests."""

from __future__ import annotations

from terminal.commands.registry import CommandContext, CommandRegistry
from terminal.commands.run import register_run_commands
from terminal.core.interfaces import CommandResult
from terminal.events import EventType
from terminal.services.bot_control import BotControlService
from terminal.services.config_manager import ConfigManager
from terminal.services.test_runner import TestRunnerService

_bot_control = BotControlService()
_config = ConfigManager()
_test_runner = TestRunnerService()


def get_bot_control() -> BotControlService:
    return _bot_control


def get_config_manager() -> ConfigManager:
    return _config


def get_test_runner() -> TestRunnerService:
    return _test_runner


def register_extended_commands(registry: CommandRegistry) -> None:
    """Wire bot control, config, and test commands into the registry."""

    register_run_commands(registry, _bot_control)

    registry.register("pause", "Pause the trading bot", _cmd_pause)
    registry.register("resume", "Resume the trading bot", _cmd_resume)
    registry.register("force-skip", "Force skip next window", _cmd_force_skip)
    registry.register("bot", "Bot control: start|stop|status", _cmd_bot)
    registry.register("config", "Show bets and bot config (config set KEY=VAL)", _cmd_config)
    registry.register("preflight", "Run preflight checks", _cmd_preflight)
    registry.register("check", "Connection status (check status)", _cmd_check)
    registry.register("staircase", "Run live staircase test", _cmd_staircase)
    registry.register("backtest", "Run 7-day backtest validation", _cmd_backtest)
    registry.register("mode", "Set bot mode: paper|live standard|hft", _cmd_mode)
    registry.register("screen", "Open screen: bot|tests|settings", _cmd_screen)


async def _cmd_pause(ctx: CommandContext) -> CommandResult:
    msg = await _bot_control.send_admin_command("PAUSE")
    await ctx.bus.emit(EventType.NOTIFICATION, {"message": msg})
    return CommandResult(True, msg)


async def _cmd_resume(ctx: CommandContext) -> CommandResult:
    msg = await _bot_control.send_admin_command("RESUME")
    await ctx.bus.emit(EventType.NOTIFICATION, {"message": msg})
    return CommandResult(True, msg)


async def _cmd_force_skip(ctx: CommandContext) -> CommandResult:
    msg = await _bot_control.send_admin_command("FORCE_SKIP")
    await ctx.bus.emit(EventType.NOTIFICATION, {"message": msg})
    return CommandResult(True, msg)


async def _cmd_bot(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        info = _bot_control.process_info
        lines = [
            f"Process: {'RUNNING' if info.running else 'STOPPED'}",
            f"PID: {info.pid or '—'}",
            f"Mode: {info.mode} | Strategy: {info.strategy}",
        ]
        if info.started_at:
            lines.append(f"Started: {info.started_at.strftime('%H:%M:%S')}")
        b = ctx.store.state.bot
        lines.append(f"DB status: {b.status} | Balance: ${b.balance:.2f}")
        return CommandResult(True, " | ".join(lines))

    action = ctx.args[0].lower()
    if action == "start":
        mode = "paper"
        strategy = "standard"
        for arg in ctx.args[1:]:
            a = arg.lower()
            if a in ("paper", "live"):
                mode = a
            elif a in ("standard", "hft"):
                strategy = a
            elif a == "--live":
                mode = "live"
            elif a == "--hft":
                strategy = "hft"
        msg = await _bot_control.start_bot(mode=mode, strategy=strategy)
        info = _bot_control.process_info
        ctx.store.set_mode(info.mode, info.strategy or strategy)
        await ctx.bus.emit(EventType.NOTIFICATION, {"message": msg})
        await ctx.bus.emit(EventType.STATE_UPDATED, {})
        return CommandResult(True, msg)

    if action == "stop":
        from terminal.commands.run import stop_all_bots

        return await stop_all_bots(_bot_control, ctx)

    if action == "status":
        return await _cmd_bot(CommandContext(store=ctx.store, bus=ctx.bus, args=[]))

    if action == "output":
        lines = _bot_control.recent_output(50)
        return CommandResult(
            True,
            "\n".join(lines) if lines else "(no bot output)",
            {"route": "activity"},
        )

    return CommandResult(
        False,
        "Usage: run --strategy <name> | stop | bot start [paper|live] [standard|hft] | bot status",
    )


async def _cmd_config(ctx: CommandContext) -> CommandResult:
    if not ctx.args or ctx.args[0].lower() in ("show", "list"):
        entries = _config.all_entries()
        lines = ["═══ Bot configuration ═══", "", _config.summary(), ""]
        current_group = ""
        for e in entries:
            if e.group != current_group:
                current_group = e.group
                lines.append(f"[{e.group}]")
            lines.append(f"  {e.key}={e.value}")
        return CommandResult(True, "\n".join(lines))

    if ctx.args[0].lower() == "set":
        if len(ctx.args) < 2 or "=" not in ctx.args[1]:
            return CommandResult(False, "Usage: config set KEY=VALUE")
        key, _, value = ctx.args[1].partition("=")
        msg = _config.set(key, value)
        ok = not msg.startswith("Invalid") and not msg.startswith("Key not")
        return CommandResult(ok, msg)

    if ctx.args[0].lower() == "summary":
        return CommandResult(True, _config.summary())

    return CommandResult(False, "Usage: config | config set KEY=VAL | config summary")


async def _cmd_preflight(ctx: CommandContext) -> CommandResult:
    live = "--live" in [a.lower() for a in ctx.args]
    result = await _test_runner.run_preflight(live=live)
    preview = result.output[:2000]
    if len(result.output) > 2000:
        preview += "\n… (truncated)"
    return CommandResult(result.success, preview)


async def _cmd_check(ctx: CommandContext) -> CommandResult:
    if not ctx.args or ctx.args[0].lower() != "status":
        return CommandResult(False, "Usage: check status [--quick]")
    quick = "--quick" in ctx.args
    result = await _test_runner.run_check_status(quick=quick)
    preview = result.output[:2000]
    if len(result.output) > 2000:
        preview += "\n… (truncated)"
    return CommandResult(result.success, preview)


async def _cmd_staircase(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        cmds = _test_runner.list_staircase_commands()
        lines = ["Staircase commands:"]
        for name, desc in cmds.items():
            lines.append(f"  {name:<14} {desc}")
        lines.append("\nUsage: staircase <cmd> [--live] [--side up|down]")
        return CommandResult(True, "\n".join(lines))

    cmd = ctx.args[0].lower()
    live = "--live" in [a.lower() for a in ctx.args]
    side = "up"
    size = None
    for i, arg in enumerate(ctx.args):
        if arg.lower() == "--side" and i + 1 < len(ctx.args):
            side = ctx.args[i + 1].lower()
        if arg.lower() == "--size" and i + 1 < len(ctx.args):
            try:
                size = float(ctx.args[i + 1])
            except ValueError:
                pass

    result = await _test_runner.run_staircase(cmd, live=live, yes=True, side=side, size=size)
    preview = result.output[:1500]
    if len(result.output) > 1500:
        preview += "\n… (truncated)"
    return CommandResult(result.success, preview or f"Exit code {result.exit_code}")


async def _cmd_backtest(ctx: CommandContext) -> CommandResult:
    import asyncio
    import io
    from contextlib import redirect_stdout

    days = 7
    for arg in ctx.args:
        if arg.isdigit():
            days = int(arg)

    def _run() -> tuple[int, str]:
        from backtest.runner import BacktestConfig, run_backtest
        from data.historical import fetch_all_assets

        candles = fetch_all_assets(days=days)
        result = run_backtest(candles, BacktestConfig())
        lines = [
            f"Backtest {days}d: {result.total_trades} trades",
            f"Win rate: {result.win_rate:.1%}",
            f"Final balance: ${result.final_balance:.2f}",
            f"P&L: ${result.total_pnl:+.2f}",
        ]
        out = io.StringIO()
        with redirect_stdout(out):
            result.print_summary()
        lines.append(out.getvalue())
        return 0, "\n".join(lines)

    code, output = await asyncio.to_thread(_run)
    return CommandResult(code == 0, output[:2000])


async def _cmd_mode(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        info = _bot_control.process_info
        return CommandResult(
            True,
            f"Bot process: {info.mode} / {info.strategy} | "
            f"env BOT_MODE={_config.get('BOT_MODE')}",
        )

    val = ctx.args[0].lower()
    if val in ("paper", "live"):
        return CommandResult(
            True,
            f"Use 'bot start {val}' to launch. Current process: "
            f"{'running' if _bot_control.process_info.running else 'stopped'}",
        )
    if val in ("standard", "hft"):
        msg = _config.set("BOT_MODE", val)
        return CommandResult(True, msg)
    return CommandResult(False, "Usage: mode paper|live|standard|hft")


async def _cmd_screen(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        return CommandResult(
            False,
            "Usage: screen bot|tests|settings|config",
            {"action": "noop"},
        )
    name = ctx.args[0].lower()
    return CommandResult(True, f"Opening {name} screen", {"action": "screen", "screen": name})
