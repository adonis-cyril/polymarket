"""Realtime thinking and verbose logging during active trading."""

import logging
import sys
from pathlib import Path
from typing import Any, Optional

from config import (
    BOT_MODE,
    REALTIME_LOG_FILE,
    REALTIME_LOG_LEVEL,
    REALTIME_LOGGING,
    REALTIME_THINKING,
)

_rt_logger = logging.getLogger("polymarket.realtime")
_initialized = False


class _FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def init_realtime_logging() -> None:
    """Attach console (and optional file) handlers for realtime output."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    if not REALTIME_LOGGING and not REALTIME_THINKING:
        return

    level = getattr(logging, REALTIME_LOG_LEVEL.upper(), logging.DEBUG)
    _rt_logger.setLevel(level)
    _rt_logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    console = _FlushingStreamHandler(sys.stdout)
    console.setFormatter(formatter)
    _rt_logger.addHandler(console)

    if REALTIME_LOGGING:
        log_path = Path(REALTIME_LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        _rt_logger.addHandler(file_handler)


def _prefix(
    asset: Optional[str] = None,
    window: Optional[int] = None,
    hft: bool = False,
    **fields: Any,
) -> str:
    tag = "[HFT]" if hft else "[THINK]"
    parts = [tag]
    if asset:
        parts.append(asset.upper())
    if window is not None:
        parts.append(f"w={window}")
    for key, value in fields.items():
        if value is not None:
            parts.append(f"{key}={value}")
    return " ".join(parts)


def think(
    msg: str,
    *,
    asset: Optional[str] = None,
    window: Optional[int] = None,
    hft: Optional[bool] = None,
    **fields: Any,
) -> None:
    """Log decision reasoning when REALTIME_THINKING is enabled."""
    if not REALTIME_THINKING:
        return
    if not _initialized:
        init_realtime_logging()
    use_hft = hft if hft is not None else BOT_MODE == "hft"
    _rt_logger.info("%s | %s", _prefix(asset=asset, window=window, hft=use_hft, **fields), msg)


def rt_log(msg: str, level: str = "DEBUG") -> None:
    """Structured verbose log when REALTIME_LOGGING is enabled."""
    if not REALTIME_LOGGING:
        return
    if not _initialized:
        init_realtime_logging()
    log_level = getattr(logging, level.upper(), logging.DEBUG)
    _rt_logger.log(log_level, "[RT] %s", msg)
