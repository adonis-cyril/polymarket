"""Structured console + file logging for staircase tests."""

import logging
import sys
from pathlib import Path

from tests.live_staircase.config import STAIRCASE_LOG_FILE

LOG = logging.getLogger("staircase")


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure staircase logger with stdout and file handlers."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    log_path = Path(STAIRCASE_LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    LOG.setLevel(log_level)
    LOG.handlers.clear()
    LOG.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    LOG.addHandler(console)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOG.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return LOG
