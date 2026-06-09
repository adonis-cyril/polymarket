"""Bot process management and admin command dispatch."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger

from terminal.strategies.registry import StrategyEntry, get_strategy_registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class BotProcessInfo:
    running: bool = False
    pid: int | None = None
    mode: str = "paper"
    strategy: str = ""
    bot_mode: str = "standard"
    started_at: datetime | None = None
    command_line: str = ""


@dataclass
class BotControlService:
    """Start/stop bot.py and send admin commands via PostgreSQL."""

    _process: subprocess.Popen[Any] | None = field(default=None, repr=False)
    _mode: str = "paper"
    _strategy: str = ""
    _bot_mode: str = "standard"
    _started_at: datetime | None = None
    _log_lines: list[str] = field(default_factory=list)
    _on_output_line: Optional[Callable[[str], None]] = field(default=None, repr=False)

    def set_output_handler(self, handler: Optional[Callable[[str], None]]) -> None:
        """Register callback for live bot stdout/stderr lines."""
        self._on_output_line = handler

    @property
    def process_info(self) -> BotProcessInfo:
        alive = self._process is not None and self._process.poll() is None
        return BotProcessInfo(
            running=alive,
            pid=self._process.pid if alive and self._process else None,
            mode=self._mode,
            strategy=self._strategy,
            bot_mode=self._bot_mode,
            started_at=self._started_at,
            command_line=self._command_line(),
        )

    def _command_line(self) -> str:
        if self._strategy:
            entry = get_strategy_registry().get(self._strategy)
            if entry:
                argv, _ = get_strategy_registry().build_argv(
                    entry, mode=self._mode, hft_override=self._bot_mode == "hft" and entry.bot_mode != "hft"
                )
                return " ".join(argv)
        return self._legacy_command_line(self._mode, self._bot_mode)

    @staticmethod
    def _legacy_command_line(mode: str, bot_mode: str) -> str:
        parts = [sys.executable, str(PROJECT_ROOT / "bot.py")]
        if mode == "live":
            parts.append("--live")
        if bot_mode == "hft":
            parts.append("--hft")
        return " ".join(parts)

    async def start_strategy(
        self,
        entry: StrategyEntry,
        *,
        mode: str | None = None,
        hft_override: bool = False,
    ) -> str:
        """Launch bot.py for a registered strategy."""
        if self._process is not None and self._process.poll() is None:
            return f"Bot already running (pid {self._process.pid}) — strategy: {self._strategy}"

        resolved_mode = (mode or entry.default_mode).lower()
        if resolved_mode not in ("paper", "live"):
            return f"Unknown mode: {resolved_mode} (use paper or live)"

        registry = get_strategy_registry()
        argv, bot_mode = registry.build_argv(entry, mode=resolved_mode, hft_override=hft_override)

        env = os.environ.copy()
        env["BOT_MODE"] = bot_mode

        self._process = subprocess.Popen(
            argv,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._mode = resolved_mode
        self._strategy = entry.name
        self._bot_mode = bot_mode
        self._started_at = datetime.now()
        asyncio.create_task(self._drain_output())
        logger.info(
            "Started bot pid={} strategy={} mode={} bot_mode={}",
            self._process.pid,
            entry.name,
            resolved_mode,
            bot_mode,
        )
        return (
            f"Started strategy '{entry.name}' (pid {self._process.pid}) — "
            f"{resolved_mode} / {bot_mode}"
        )

    async def start_bot(self, *, mode: str = "paper", strategy: str = "standard") -> str:
        """Legacy launcher — maps standard/hft to registry strategies."""
        registry = get_strategy_registry()
        strategy_name = "hft" if strategy.lower() == "hft" else "kelly"
        entry = registry.get(strategy_name)
        if entry is None:
            return f"Unknown strategy: {strategy}"
        hft_override = strategy.lower() == "hft" and entry.bot_mode != "hft"
        return await self.start_strategy(entry, mode=mode, hft_override=hft_override)

    async def stop_bot(self) -> str:
        """Terminate the bot subprocess gracefully."""
        if self._process is None or self._process.poll() is not None:
            self._process = None
            self._strategy = ""
            return "Bot is not running"

        pid = self._process.pid
        strategy = self._strategy
        try:
            self._process.send_signal(signal.SIGINT)
            await asyncio.to_thread(self._process.wait, timeout=15)
        except subprocess.TimeoutExpired:
            self._process.kill()
            await asyncio.to_thread(self._process.wait)
        except Exception as exc:
            logger.warning("Stop bot error: {}", exc)
            self._process.kill()

        self._process = None
        self._strategy = ""
        label = f" strategy '{strategy}'" if strategy else ""
        return f"Stopped{label} (was pid {pid})"

    async def _drain_output(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            while proc.poll() is None:
                line = await asyncio.to_thread(proc.stdout.readline)
                if not line:
                    break
                text = line.rstrip()
                self._log_lines.append(text)
                if len(self._log_lines) > 500:
                    self._log_lines = self._log_lines[-500:]
                if text and self._on_output_line:
                    try:
                        self._on_output_line(text)
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Bot output drain ended: {}", exc)

    def recent_output(self, limit: int = 30) -> list[str]:
        return self._log_lines[-limit:]

    async def send_admin_command(self, command: str, payload: dict | None = None) -> str:
        """Insert PAUSE / RESUME / FORCE_SKIP into the commands table."""
        command = command.upper()
        allowed = {"PAUSE", "RESUME", "FORCE_SKIP", "PING"}
        if command not in allowed:
            return f"Unknown admin command: {command}"

        if command == "PING":
            return "PING ok"

        try:
            await asyncio.to_thread(self._insert_command_sync, command, payload)
            return f"Admin command queued: {command}"
        except Exception as exc:
            logger.exception("Failed to queue command {}", command)
            return f"Failed to queue {command}: {exc}"

    @staticmethod
    def _insert_command_sync(command: str, payload: dict | None) -> None:
        from data.pg import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO commands (command, payload, executed) VALUES (%s, %s, FALSE)",
                (command, payload),
            )

    async def get_recent_commands(self, limit: int = 10) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_commands_sync, limit)

    @staticmethod
    def _fetch_commands_sync(limit: int) -> list[dict[str, Any]]:
        from data.pg import dict_cursor, get_connection

        with get_connection() as conn:
            cur = dict_cursor(conn)
            cur.execute(
                """
                SELECT id, command, payload, executed, created_at
                FROM commands ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]
