"""TUI command dispatch — ensures Enter on >>> reaches handlers."""

from __future__ import annotations

import asyncio

from terminal.commands import CommandContext
from terminal.commands.connection import register_connection_commands, set_orchestrator
from terminal.commands.registry import CommandRegistry
from terminal.core.interfaces import CommandResult
from terminal.ui.app import PolymarketTUI
from terminal.ui.widgets.command_bar import CommandSubmitted


def test_command_submitted_handler_name():
    assert CommandSubmitted.handler_name == "on_command_submitted"


def test_enter_dispatches_command():
    async def run() -> None:
        app = PolymarketTUI()
        executed: list[str] = []

        async def track(line: str) -> None:
            executed.append(line.strip())

        app._execute_command = track  # type: ignore[method-assign]

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#cmd-input")
            await pilot.press(*"help")
            await pilot.press("enter")
            await pilot.pause(0.5)

        assert executed == ["help"]

    asyncio.run(run())


def test_connect_handler_returns_output(monkeypatch):
    from terminal.services.test_runner import TestRunResult

    registry = CommandRegistry()
    register_connection_commands(registry)

    class FakeRunner:
        async def run_preflight(self, *, live: bool = False):
            return TestRunResult(
                command="preflight",
                exit_code=1,
                output="DATABASE_URL not set — configure .env and retry",
                success=False,
            )

    class FakeOrch:
        async def start(self) -> None:
            pass

        async def refresh_all(self) -> None:
            pass

    monkeypatch.setattr(
        "terminal.commands.connection.get_test_runner",
        lambda: FakeRunner(),
    )
    set_orchestrator(FakeOrch())

    async def run() -> None:
        from terminal.events import EventBus
        from terminal.state import StateStore

        ctx = CommandContext(store=StateStore(), bus=EventBus())
        result = await registry.execute("connect", ctx)
        assert result.success is False
        assert "Preflight failed" in result.message

    asyncio.run(run())


def test_execute_command_echoes_and_routes(monkeypatch):
    async def run() -> None:
        app = PolymarketTUI()
        activity: list[str] = []
        app._append_activity = lambda msg, level="INFO", source="tui": activity.append(msg)  # type: ignore[method-assign]

        async def fake_execute(line: str, ctx: CommandContext) -> CommandResult:
            return CommandResult(True, "ok from status")

        monkeypatch.setattr(app.registry, "execute", fake_execute)

        async with app.run_test(size=(80, 30)):
            await app._execute_command("status")

        assert any(">>> status" in line for line in activity)

    asyncio.run(run())
