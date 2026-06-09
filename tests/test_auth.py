"""Tests for TUI password gate."""

from __future__ import annotations

import os

import pytest

from terminal.auth.password import get_admin_password, validate_password


def test_validate_password_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    monkeypatch.delenv("TUI_ADMIN_PASSWORD", raising=False)
    assert validate_password("secret123") is True
    assert validate_password("wrong") is False


def test_validate_password_tui_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "dashboard-pass")
    monkeypatch.setenv("TUI_ADMIN_PASSWORD", "tui-pass")
    assert get_admin_password() == "tui-pass"
    assert validate_password("tui-pass") is True
    assert validate_password("dashboard-pass") is False


def test_validate_password_empty_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("TUI_ADMIN_PASSWORD", raising=False)
    assert validate_password("anything") is True
