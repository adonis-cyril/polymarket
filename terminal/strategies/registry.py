"""Load strategy manifests from the strategies/ folder."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
MANIFEST_PATH = STRATEGIES_DIR / "manifest.json"

_DEFAULT_MANIFEST: dict[str, Any] = {
    "strategies": [
        {
            "name": "kelly",
            "aliases": ["staircase_kelly", "standard"],
            "description": "Quarter-Kelly sizing with active mid-window exits",
            "bot_mode": "standard",
            "default_mode": "paper",
            "extra_args": [],
        },
        {
            "name": "hft",
            "aliases": [],
            "description": "HFT scalp mode — 2% TP / 1.5% SL, max 30s hold",
            "bot_mode": "hft",
            "default_mode": "paper",
            "extra_args": ["--hft"],
        },
    ]
}


@dataclass(frozen=True)
class StrategyEntry:
    name: str
    description: str
    bot_mode: str
    default_mode: str
    extra_args: tuple[str, ...] = ()


class StrategyRegistry:
    """Registry of runnable bot strategies from strategies/manifest.json."""

    def __init__(self) -> None:
        self._by_name: dict[str, StrategyEntry] = {}
        self._load()

    def _load(self) -> None:
        STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
        data = self._read_manifest()
        self._by_name.clear()
        for raw in data.get("strategies", []):
            entry = self._parse_entry(raw)
            self._by_name[entry.name] = entry
            for alias in raw.get("aliases", []):
                if alias and alias not in self._by_name:
                    self._by_name[alias] = entry

    @staticmethod
    def _read_manifest() -> dict[str, Any]:
        if not MANIFEST_PATH.exists():
            MANIFEST_PATH.write_text(
                json.dumps(_DEFAULT_MANIFEST, indent=2) + "\n",
                encoding="utf-8",
            )
            return _DEFAULT_MANIFEST
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return _DEFAULT_MANIFEST

    @staticmethod
    def _parse_entry(raw: dict[str, Any]) -> StrategyEntry:
        name = str(raw.get("name", "")).strip().lower()
        if not name:
            raise ValueError("Strategy entry missing name")
        bot_mode = str(raw.get("bot_mode", "standard")).strip().lower()
        default_mode = str(raw.get("default_mode", "paper")).strip().lower()
        extra = tuple(str(a) for a in raw.get("extra_args", []) if a)
        return StrategyEntry(
            name=name,
            description=str(raw.get("description", "")).strip(),
            bot_mode=bot_mode if bot_mode in ("standard", "hft") else "standard",
            default_mode=default_mode if default_mode in ("paper", "live") else "paper",
            extra_args=extra,
        )

    def list_entries(self) -> list[StrategyEntry]:
        seen: set[str] = set()
        entries: list[StrategyEntry] = []
        for entry in self._by_name.values():
            if entry.name not in seen:
                seen.add(entry.name)
                entries.append(entry)
        return sorted(entries, key=lambda e: e.name)

    def list_names(self) -> list[str]:
        return [e.name for e in self.list_entries()]

    def get(self, name: str) -> StrategyEntry | None:
        return self._by_name.get(name.strip().lower())

    def format_list(self) -> str:
        lines = ["Available strategies:", ""]
        for entry in self.list_entries():
            lines.append(f"  {entry.name:<16} {entry.description}")
            lines.append(
                f"    mode: {entry.default_mode} | bot_mode: {entry.bot_mode}"
                + (f" | args: {' '.join(entry.extra_args)}" if entry.extra_args else "")
            )
        lines.extend(
            [
                "",
                "Usage: run --strategy <name> [--live] [--hft]",
                "       run                  (list strategies)",
            ]
        )
        return "\n".join(lines)

    def build_argv(
        self,
        entry: StrategyEntry,
        *,
        mode: str,
        hft_override: bool = False,
    ) -> tuple[list[str], str]:
        import sys

        argv = [sys.executable, str(PROJECT_ROOT / "bot.py")]
        bot_mode = "hft" if hft_override else entry.bot_mode

        if mode == "live":
            argv.append("--live")
        if bot_mode == "hft" and "--hft" not in entry.extra_args:
            argv.append("--hft")
        for arg in entry.extra_args:
            if arg not in argv:
                argv.append(arg)
        return argv, bot_mode


@lru_cache(maxsize=1)
def get_strategy_registry() -> StrategyRegistry:
    return StrategyRegistry()
