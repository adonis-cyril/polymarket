"""Re-export data providers from legacy location."""

from terminal.providers.polymarket import PolymarketProvider
from terminal.providers.postgres import PostgresProvider

__all__ = ["PolymarketProvider", "PostgresProvider"]
