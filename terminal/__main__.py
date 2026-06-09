"""Entry point: python -m terminal (delegates to start.py with auth gate)."""

from __future__ import annotations

import sys


def main() -> None:
    """Launch via start.py so password gate is always applied."""
    from start import main as start_main

    sys.exit(start_main())


if __name__ == "__main__":
    main()
