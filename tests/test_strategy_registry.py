"""Tests for strategy registry and run command arg parsing."""

from __future__ import annotations

from terminal.commands.run import _parse_run_args
from terminal.strategies.registry import get_strategy_registry


def test_registry_loads_kelly_and_hft() -> None:
    registry = get_strategy_registry()
    names = registry.list_names()
    assert "kelly" in names
    assert "hft" in names


def test_registry_resolves_aliases() -> None:
    registry = get_strategy_registry()
    assert registry.get("staircase_kelly") is not None
    assert registry.get("staircase_kelly").name == "kelly"


def test_build_argv_kelly_paper() -> None:
    registry = get_strategy_registry()
    entry = registry.get("kelly")
    assert entry is not None
    argv, bot_mode = registry.build_argv(entry, mode="paper")
    assert bot_mode == "standard"
    assert "--live" not in argv
    assert "--hft" not in argv


def test_build_argv_hft_live() -> None:
    registry = get_strategy_registry()
    entry = registry.get("hft")
    assert entry is not None
    argv, bot_mode = registry.build_argv(entry, mode="live")
    assert bot_mode == "hft"
    assert "--live" in argv
    assert "--hft" in argv


def test_parse_run_args_list() -> None:
    assert _parse_run_args([])[3] is True
    assert _parse_run_args(["--strategy"])[3] is True


def test_parse_run_args_named() -> None:
    name, live, hft, list_only = _parse_run_args(["--strategy", "kelly", "--live"])
    assert name == "kelly"
    assert live is True
    assert hft is False
    assert list_only is False
