"""Tests for command output routing."""

from __future__ import annotations

from terminal.core.interfaces import CommandResult
from terminal.ui.output_router import OutputRouter


def test_short_command_routes_below_input():
    short: list[tuple[str, str]] = []
    activity: list[tuple[str, str, str]] = []

    router = OutputRouter(
        on_short=lambda msg, lvl: short.append((msg, lvl)),
        on_activity=lambda msg, lvl, src: activity.append((msg, lvl, src)),
    )
    router.route_command("status", CommandResult(True, "line1\nline2"))

    assert short
    assert not activity


def test_long_command_routes_to_activity():
    short: list[tuple[str, str]] = []
    activity: list[tuple[str, str, str]] = []

    router = OutputRouter(
        on_short=lambda msg, lvl: short.append((msg, lvl)),
        on_activity=lambda msg, lvl, src: activity.append((msg, lvl, src)),
    )
    lines = "\n".join(f"line{i}" for i in range(20))
    router.route_command("preflight", CommandResult(True, lines))

    assert not short
    assert len(activity) == 20


def test_stream_always_activity():
    short: list[tuple[str, str]] = []
    activity: list[tuple[str, str, str]] = []

    router = OutputRouter(
        on_short=lambda msg, lvl: short.append((msg, lvl)),
        on_activity=lambda msg, lvl, src: activity.append((msg, lvl, src)),
    )
    router.route_stream("bot heartbeat", source="bot")

    assert not short
    assert activity == [("bot heartbeat", "INFO", "bot")]
