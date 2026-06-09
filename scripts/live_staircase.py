#!/usr/bin/env python3
"""Thin wrapper: python scripts/live_staircase.py <command> [options]"""

import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.live_staircase.cli import main

if __name__ == "__main__":
    sys.exit(main())
