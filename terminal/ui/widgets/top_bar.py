"""Top status bar — connection, account, strategy/mode."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from terminal.core.models import BotStateSnapshot, ConnectivityStatus, ConnectionState


class TopBar(Static):
    """Hummingbot-style top navigation strip."""

    DEFAULT_CSS = """
    TopBar {
        dock: top;
        height: 1;
        width: 100%;
        background: $surface;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    """

    version: reactive[str] = reactive("v0.1.0")
    mode: reactive[str] = reactive("paper")
    strategy: reactive[str] = reactive("standard")
    status: reactive[str] = reactive("OFFLINE")
    balance: reactive[float] = reactive(0.0)
    gamma: reactive[str] = reactive("unknown")
    clob: reactive[str] = reactive("unknown")
    database: reactive[str] = reactive("unknown")
    loading: reactive[bool] = reactive(False)

    def render(self) -> str:
        spin = "⟳ " if self.loading else ""
        conn = (
            f"γ{self._dot(self.gamma)} "
            f"CLOB{self._dot(self.clob)} "
            f"DB{self._dot(self.database)}"
        )
        return (
            f"{spin}POLYMARKET {self.version} │ "
            f"{self.mode}/{self.strategy} │ "
            f"ACCT ${self.balance:,.2f} │ "
            f"BOT {self.status} │ {conn}"
        )

    @staticmethod
    def _dot(state: str) -> str:
        icons = {"ok": "●", "fail": "○", "warn": "◐", "unknown": "·"}
        return icons.get(state, "·")

    def update_from_state(
        self,
        bot: BotStateSnapshot,
        conn: ConnectivityStatus,
        *,
        mode: str = "paper",
        strategy: str = "standard",
        loading: bool = False,
        version: str = "v0.1.0",
    ) -> None:
        self.version = version
        self.mode = mode
        self.strategy = strategy
        self.status = bot.status
        self.balance = bot.balance
        self.gamma = conn.gamma_api.value
        self.clob = conn.clob_api.value
        self.database = conn.database.value
        self.loading = loading
