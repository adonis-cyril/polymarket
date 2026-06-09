"""Unit tests for bot bet-size resolution and session cap."""

import sys
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

# bot.py pulls in PostgreSQL; avoid requiring psycopg2 for pure sizing tests
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

from bot import TradingBot  # noqa: E402


class FinalizeBetSizeTests(unittest.TestCase):
    def setUp(self):
        self.bot = TradingBot(paper_mode=True)
        self.bot.balance = 10.0
        self.bot.session_spend = 0.0

    @patch("bot.BET_SIZE", Decimal("0"))
    @patch("bot.MAX_SESSION_SPEND", Decimal("0"))
    def test_kelly_sized_when_bet_size_unset(self):
        bet = self.bot._finalize_bet_size(3.50, 8.0)
        self.assertEqual(bet, 3.50)

    @patch("bot.BET_SIZE", Decimal("1.00"))
    @patch("bot.MAX_SESSION_SPEND", Decimal("0"))
    def test_fixed_bet_size_overrides_kelly(self):
        bet = self.bot._finalize_bet_size(3.50, 8.0)
        self.assertEqual(bet, 1.0)

    @patch("bot.BET_SIZE", Decimal("1.00"))
    @patch("bot.MAX_SESSION_SPEND", Decimal("5.00"))
    def test_session_cap_limits_remaining_budget(self):
        self.bot.session_spend = 4.0
        bet = self.bot._finalize_bet_size(2.0, 10.0)
        self.assertEqual(bet, 1.0)

    @patch("bot.BET_SIZE", Decimal("1.00"))
    @patch("bot.MAX_SESSION_SPEND", Decimal("5.00"))
    def test_session_cap_exhausted(self):
        self.bot.session_spend = 5.0
        self.assertEqual(self.bot._session_budget_remaining(), 0.0)
        bet = self.bot._finalize_bet_size(2.0, 10.0)
        self.assertEqual(bet, 0.0)


if __name__ == "__main__":
    unittest.main()
