"""Bottom status bar with connectivity and clock."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from terminal.core.models import BotStateSnapshot, ConnectivityStatus, ConnectionState


class StatusBar(Static):
    """Live status strip — mode, connections, balance, time."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        width: 100%;
    }
    """

    bot_status: reactive[str] = reactive("OFFLINE")
    balance: reactive[float] = reactive(0.0)
    gamma: reactive[str] = reactive("—")
    clob: reactive[str] = reactive("—")
    database: reactive[str] = reactive("—")
    loading: reactive[bool] = reactive(False)

    def render(self) -> str:
        spin = "⟳ " if self.loading else ""
        now = datetime.now().strftime("%H:%M:%S")
        return (
            f"{spin}BOT:{self.bot_status} | "
            f"BAL:${self.balance:,.2f} | "
            f"γ:{self._dot(self.gamma)} CLOB:{self._dot(self.clob)} DB:{self._dot(self.database)} | "
            f"{now}"
        )

    @staticmethod
    def _dot(state: str) -> str:
        icons = {"ok": "●", "fail": "○", "warn": "◐", "unknown": "·"}
        return icons.get(state, "·")

    def update_from_state(
        self,
        bot: BotStateSnapshot,
        conn: ConnectivityStatus,
        loading: bool = False,
    ) -> None:
        self.bot_status = bot.status
        self.balance = bot.balance
        self.gamma = conn.gamma_api.value
        self.clob = conn.clob_api.value
        self.database = conn.database.value
        self.loading = loading
