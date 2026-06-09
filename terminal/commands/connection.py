"""Connection commands — connect, status, balance."""

from __future__ import annotations

import re

from terminal.commands.extended import get_bot_control, get_test_runner
from terminal.commands.registry import CommandContext, CommandRegistry
from terminal.core.interfaces import CommandResult
from terminal.core.models import ConnectionState
from terminal.events import EventType

_ANSI = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

_orchestrator = None


def set_orchestrator(orchestrator) -> None:
    global _orchestrator
    _orchestrator = orchestrator


def register_connection_commands(registry: CommandRegistry) -> None:
    registry.register("connect", "Connect services, preflight, start data sync", _cmd_connect)
    registry.register("status", "Health check — Gamma, CLOB, DB, bot", _cmd_status)
    registry.register("balance", "Fetch USDC balance from CLOB", _cmd_balance)


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


async def _emit_lines(ctx: CommandContext, text: str, *, level: str = "INFO") -> None:
    for line in _strip_ansi(text).splitlines():
        stripped = line.rstrip()
        if stripped:
            await ctx.bus.emit(
                EventType.ACTIVITY_EVENT,
                {"message": stripped, "level": level, "source": "connect"},
            )


async def _cmd_connect(ctx: CommandContext) -> CommandResult:
    live = "--live" in [a.lower() for a in ctx.args]
    orch = _orchestrator

    await _emit_lines(ctx, "═══ Connection flow ═══")
    await _emit_lines(ctx, "Step 1/3: Running preflight checks…")
    runner = get_test_runner()
    result = await runner.run_preflight(live=live)
    await _emit_lines(ctx, result.output, level="INFO" if result.success else "WARNING")
    if not result.success:
        return CommandResult(
            False,
            "Preflight failed — fix issues above and retry connect",
            {"suppress_output": True},
        )

    await _emit_lines(ctx, "Step 2/3: Starting data sync…")
    if orch is not None:
        await orch.start()
        await orch.refresh_all()
    ctx.store.set_connected(True)
    await ctx.bus.emit(EventType.REFRESH_REQUESTED)

    await _emit_lines(ctx, "Step 3/3: Verifying connectivity…")
    conn = ctx.store.state.connectivity
    bot = ctx.store.state.bot
    info = get_bot_control().process_info
    await _emit_lines(ctx, _format_connectivity(conn, bot.status, info.running))

    return CommandResult(
        True,
        "Connected — data sync active. Use status, balance, or run --strategy kelly.",
    )


async def _cmd_status(ctx: CommandContext) -> CommandResult:
    orch = _orchestrator
    if orch is not None:
        await orch.refresh_all()

    conn = ctx.store.state.connectivity
    bot = ctx.store.state.bot
    info = get_bot_control().process_info
    lines = [
        "═══ System status ═══",
        "",
        _format_connectivity(conn, bot.status, info.running),
        "",
        "Bot state (PostgreSQL):",
        f"  Status:     {bot.status}",
        f"  Balance:    ${bot.balance:,.2f}",
        f"  Trades:     {bot.total_trades} ({bot.total_wins} wins, {bot.win_rate:.1f}%)",
        f"  Level:      {bot.level} → ${bot.level_target:,.0f}",
        f"  Regime:     {bot.regime}",
        f"  Phase:      {bot.current_phase}",
        "",
        "Bot process:",
        f"  Running:    {'yes' if info.running else 'no'}",
        f"  PID:        {info.pid or '—'}",
        f"  Mode:       {info.mode} / {info.strategy}",
        "",
        f"Data sync:    {'active' if ctx.store.state.connected else 'idle (run connect)'}",
        f"Markets:      {len(ctx.store.state.markets)} loaded",
        f"Positions:    {len(ctx.store.state.positions)} open",
    ]
    if conn.message:
        lines.append(f"Notes:        {conn.message}")

    text = "\n".join(lines)
    ok = conn.gamma_api == ConnectionState.OK and conn.clob_api == ConnectionState.OK
    return CommandResult(ok, text)


async def _cmd_balance(ctx: CommandContext) -> CommandResult:
    live = "--live" in [a.lower() for a in ctx.args]

    def _fetch() -> tuple[float, str]:
        try:
            from execution.balance import get_position_value_usd, get_usdc_balance

            usdc = get_usdc_balance()
            pos_val = get_position_value_usd()
            detail = f"USDC (CLOB): ${usdc:,.2f}"
            if pos_val is not None:
                detail += f" | Positions (mark): ${pos_val:,.2f} | Total: ${usdc + pos_val:,.2f}"
            return usdc, detail
        except Exception as exc:
            return 0.0, f"Balance fetch failed: {exc}"

    import asyncio

    usdc, detail = await asyncio.to_thread(_fetch)
    db_bal = ctx.store.state.bot.balance
    lines = [
        "═══ Account balance ═══",
        detail,
        f"DB tracked:  ${db_bal:,.2f}",
    ]
    if usdc == 0.0 and not live and "failed" not in detail.lower():
        lines.append("(Tip: use balance --live for CLOB auth)")

    text = "\n".join(lines)
    ok = "failed" not in detail.lower()
    return CommandResult(ok, text)


def _format_connectivity(conn, bot_status: str, bot_running: bool) -> str:
    def _icon(state: ConnectionState) -> str:
        return {"ok": "OK", "fail": "FAIL", "warn": "WARN"}.get(state.value, "?")

    gamma_lat = f" ({conn.gamma_latency_ms:.0f}ms)" if conn.gamma_latency_ms else ""
    clob_lat = f" ({conn.clob_latency_ms:.0f}ms)" if conn.clob_latency_ms else ""
    return "\n".join(
        [
            f"  Gamma API:  {_icon(conn.gamma_api)}{gamma_lat}",
            f"  CLOB API:   {_icon(conn.clob_api)}{clob_lat}",
            f"  PostgreSQL: {_icon(conn.database)}",
            f"  Bot DB:     {bot_status}",
            f"  Bot proc:   {'RUNNING' if bot_running else 'STOPPED'}",
        ]
    )
