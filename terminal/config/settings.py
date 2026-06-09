"""Pydantic settings for the terminal workstation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TUISettings(BaseSettings):
    """Terminal UI configuration — extends project .env with TUI-specific options."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Inherited from project .env
    database_url: str = Field(default="", alias="DATABASE_URL")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    tui_admin_password: str = Field(default="", alias="TUI_ADMIN_PASSWORD")
    bot_mode: Literal["standard", "hft"] = Field(default="standard", alias="BOT_MODE")
    starting_bankroll: float = Field(default=20.0, alias="STARTING_BANKROLL")
    initial_bankroll: float = Field(default=10.0, alias="INITIAL_BANKROLL")

    # TUI-specific
    tui_theme: str = Field(default="polyadonis", alias="TUI_THEME")
    tui_refresh_interval: float = Field(default=2.0, alias="TUI_REFRESH_INTERVAL")
    tui_log_level: str = Field(default="INFO", alias="TUI_LOG_LEVEL")
    tui_log_file: str = Field(default="logs/tui.log", alias="TUI_LOG_FILE")
    tui_chart_history: int = Field(default=60, alias="TUI_CHART_HISTORY")
    tui_markets_limit: int = Field(default=50, alias="TUI_MARKETS_LIMIT")
    tui_trades_limit: int = Field(default=100, alias="TUI_TRADES_LIMIT")

    @property
    def log_path(self) -> Path:
        return Path(self.tui_log_file)


@lru_cache
def get_settings() -> TUISettings:
    return TUISettings()
