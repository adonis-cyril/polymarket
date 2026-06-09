"""Run live staircase and operational checks from the TUI."""

from __future__ import annotations

import asyncio
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Callable

from loguru import logger

from tests.live_staircase.cli import main as staircase_main


STAIRCASE_COMMANDS: dict[str, str] = {
    "discover": "Find current BTC 5m market (dry-run)",
    "account": "USDC balance, allowances, funder (needs --live)",
    "status": "Balance, orders, positions",
    "buy": "Place buy order",
    "sell": "Place sell to close",
    "exit": "Urgent market sell",
    "take-profit": "Take-profit limit sell",
    "stop-loss": "Stop-loss sell",
    "cancel": "Cancel open orders",
    "last-minute": "Snipe entry near window close",
    "run-staircase": "Full guided staircase flow",
}


@dataclass
class TestRunResult:
    command: str
    exit_code: int
    output: str
    success: bool


@dataclass
class TestRunnerService:
    """Execute staircase tests and preflight checks."""

    _history: list[TestRunResult] = field(default_factory=list)

    def list_staircase_commands(self) -> dict[str, str]:
        return dict(STAIRCASE_COMMANDS)

    async def run_staircase(
        self,
        command: str,
        *,
        live: bool = False,
        yes: bool = True,
        side: str = "up",
        size: float | None = None,
    ) -> TestRunResult:
        """Run a live_staircase subcommand and capture output."""
        command = command.lower().replace("_", "-")
        if command not in STAIRCASE_COMMANDS:
            return TestRunResult(command, 2, f"Unknown staircase command: {command}", False)

        argv = [command]
        if live:
            argv.append("--live")
        if yes:
            argv.append("--yes")
        argv.extend(["--side", side])
        if size is not None:
            argv.extend(["--size", str(size)])

        return await self._run_capture(f"staircase:{command}", lambda: staircase_main(argv))

    async def run_preflight(self, *, live: bool = False) -> TestRunResult:
        return await self._run_capture(
            "preflight",
            lambda: self._preflight_sync(live),
        )

    async def run_check_status(self, *, quick: bool = False) -> TestRunResult:
        return await self._run_capture(
            "check_status",
            lambda: self._check_status_sync(quick=quick),
        )

    @staticmethod
    def _preflight_sync(live: bool) -> int:
        import asyncio

        from preflight import run_preflight

        ok = asyncio.run(run_preflight(live))
        return 0 if ok else 1

    @staticmethod
    def _check_status_sync(*, quick: bool = False) -> int:
        import asyncio

        from scripts.check_status import run

        return asyncio.run(run(quick=quick, dns_only=False))

    async def _run_capture(self, label: str, fn: Callable[[], int]) -> TestRunResult:
        buf = io.StringIO()

        def _invoke() -> int:
            try:
                with redirect_stdout(buf), redirect_stderr(buf):
                    return fn()
            except SystemExit as exc:
                return int(exc.code) if exc.code is not None else 1
            except Exception as exc:
                buf.write(f"ERROR: {exc}\n")
                logger.exception("{} failed", label)
                return 1

        code = await asyncio.to_thread(_invoke)
        output = buf.getvalue().strip() or "(no output)"
        result = TestRunResult(label, code, output, code == 0)
        self._history.append(result)
        if len(self._history) > 50:
            self._history = self._history[-50:]
        return result

    def recent_results(self, limit: int = 10) -> list[TestRunResult]:
        return self._history[-limit:]
