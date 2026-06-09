"""Runtime config view/edit backed by .env and config.py."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

# Keys exposed in TUI config editor (grouped for UX)
CONFIG_GROUPS: dict[str, list[str]] = {
    "Trading": [
        "STARTING_BANKROLL",
        "INITIAL_BANKROLL",
        "MIN_BET",
        "BET_SIZE",
        "MAX_SESSION_SPEND",
        "BOT_MODE",
    ],
    "Risk": [
        "DAILY_LOSS_LIMIT",
        "DRAWDOWN_CAP",
        "CONSECUTIVE_LOSS_PAUSE",
    ],
    "HFT": [
        "HFT_TAKE_PROFIT_PCT",
        "HFT_STOP_LOSS_PCT",
        "HFT_MAX_HOLD_SECONDS",
        "HFT_MIN_SIGNAL_SCORE",
        "HFT_BET_FRACTION",
        "HFT_POLL_INTERVAL",
    ],
    "Markets": [
        "ACTIVE_MARKETS_CACHE_ENABLED",
        "ACTIVE_MARKETS_DB_PERSIST",
        "ACTIVE_MARKETS_CACHE_TTL",
        "ACTIVE_MARKETS_SYNC_ON_STARTUP",
    ],
    "Realtime": [
        "REALTIME_THINKING",
        "REALTIME_LOGGING",
        "REALTIME_LOG_LEVEL",
    ],
    "Staircase": [
        "STAIRCASE_DEFAULT_SIZE",
        "STAIRCASE_TP_PCT",
        "STAIRCASE_SL_PCT",
    ],
}


@dataclass
class ConfigEntry:
    key: str
    value: str
    group: str = ""


class ConfigManager:
    """Read and persist bot configuration to .env."""

    def __init__(self, env_path: Path | None = None) -> None:
        self.env_path = env_path or ENV_PATH
        load_dotenv(self.env_path, override=True)

    def all_entries(self) -> list[ConfigEntry]:
        """Return grouped config entries with current values."""
        file_vals = dotenv_values(self.env_path) if self.env_path.exists() else {}
        entries: list[ConfigEntry] = []
        for group, keys in CONFIG_GROUPS.items():
            for key in keys:
                val = os.getenv(key, file_vals.get(key, ""))
                entries.append(ConfigEntry(key=key, value=str(val or ""), group=group))
        return entries

    def get(self, key: str) -> str:
        return os.getenv(key, dotenv_values(self.env_path).get(key, "") or "")

    def set(self, key: str, value: str) -> str:
        """Update a single key in .env and reload into os.environ."""
        key = key.upper().strip()
        if not re.match(r"^[A-Z][A-Z0-9_]*$", key):
            return f"Invalid key: {key}"

        allowed = {k for keys in CONFIG_GROUPS.values() for k in keys}
        if key not in allowed:
            return f"Key not editable via TUI: {key}"

        self._write_env_key(key, value)
        os.environ[key] = value
        load_dotenv(self.env_path, override=True)
        logger.info("Config updated: {}={}", key, value)
        return f"Set {key}={value}"

    def summary(self) -> str:
        """One-line config summary from live config module."""
        try:
            import config as cfg

            lines = [
                f"BOT_MODE={cfg.BOT_MODE}",
                f"STARTING_BANKROLL=${float(cfg.STARTING_BANKROLL):.2f}",
                f"MIN_BET=${float(cfg.MIN_BET):.2f}",
                f"BET_SIZE=${float(cfg.BET_SIZE):.2f}",
                f"MAX_SESSION_SPEND=${float(cfg.MAX_SESSION_SPEND):.2f}",
                f"DAILY_LOSS_LIMIT={cfg.DAILY_LOSS_LIMIT:.0%}",
                f"DRAWDOWN_CAP={cfg.DRAWDOWN_CAP:.0%}",
            ]
            return " | ".join(lines)
        except Exception as exc:
            return f"Config load error: {exc}"

    def _write_env_key(self, key: str, value: str) -> None:
        if not self.env_path.exists():
            self.env_path.write_text(f"{key}={value}\n", encoding="utf-8")
            return

        text = self.env_path.read_text(encoding="utf-8")
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        line = f"{key}={value}"
        if pattern.search(text):
            text = pattern.sub(line, text)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{line}\n"
        self.env_path.write_text(text, encoding="utf-8")
