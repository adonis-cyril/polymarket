"""Staircase-specific configuration from environment."""

import os

STAIRCASE_DEFAULT_SIZE = float(os.getenv("STAIRCASE_DEFAULT_SIZE", "2.00"))
STAIRCASE_TP_PCT = float(os.getenv("STAIRCASE_TP_PCT", "0.02"))
STAIRCASE_SL_PCT = float(os.getenv("STAIRCASE_SL_PCT", "0.015"))
STAIRCASE_LOG_FILE = os.getenv("STAIRCASE_LOG_FILE", "logs/staircase.log")
STAIRCASE_LAST_MINUTE_MIN_SECS = float(os.getenv("STAIRCASE_LAST_MINUTE_MIN_SECS", "15"))
STAIRCASE_LAST_MINUTE_MAX_SECS = float(os.getenv("STAIRCASE_LAST_MINUTE_MAX_SECS", "60"))
STAIRCASE_STATE_FILE = os.getenv("STAIRCASE_STATE_FILE", "logs/staircase_state.json")
