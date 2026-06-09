"""Loguru configuration with TUI sink."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from terminal.config import get_settings
from terminal.core.models import LogEntry


def setup_logging(on_log: Optional[Callable[[LogEntry], None]] = None) -> None:
    """Configure loguru — stderr, file, and optional TUI callback."""
    settings = get_settings()
    logger.remove()

    log_path = settings.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        sys.stderr,
        level=settings.tui_log_level,
        format="<dim>{time:HH:mm:ss}</dim> | <level>{level: <8}</level> | {message}",
        colorize=True,
    )
    logger.add(
        str(log_path),
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )

    if on_log:

        def tui_sink(message):
            record = message.record
            entry = LogEntry(
                timestamp=record["time"],
                level=record["level"].name,
                message=record["message"],
                source=record.get("name", "app"),
            )
            on_log(entry)

        logger.add(tui_sink, level="INFO", format="{message}")
