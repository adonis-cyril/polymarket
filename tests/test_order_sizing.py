"""Unit tests for buy order sizing / budget enforcement."""

import unittest

from execution.order import MIN_SHARES, compute_buy_shares


class ComputeBuySharesTests(unittest.TestCase):
    def test_one_dollar_at_twenty_cent_ask(self):
        shares = compute_buy_shares(1.0, 0.20)
        self.assertEqual(shares, MIN_SHARES)
        self.assertEqual(round(shares * 0.20, 2), 1.0)

    def test_one_dollar_at_fifty_three_cent_ask_aborts(self):
        with self.assertRaises(ValueError) as ctx:
            compute_buy_shares(1.0, 0.53)
        self.assertIn("minimum is 5 shares", str(ctx.exception))
        self.assertIn("2.65", str(ctx.exception))

    def test_wrong_low_ask_passes_notional_but_real_fill_would_exceed(self):
        # If ask were misread as 17c, sizing yields ~5.88 shares for $1 at that price.
        # A fill at the real ask (53c) would cost ~$3 — prevented by correct min(asks).
        shares = compute_buy_shares(1.0, 0.17)
        self.assertAlmostEqual(shares, 5.88, places=2)
        self.assertGreater(round(shares * 0.53, 2), 1.0)

    def test_five_point_eight_shares_at_fifty_three_cents_exceeds_budget(self):
        notional = round(5.8 * 0.53, 2)
        self.assertGreater(notional, 1.0)
        with self.assertRaises(ValueError):
            compute_buy_shares(1.0, 0.53)

    def test_invalid_ask(self):
        with self.assertRaises(ValueError):
            compute_buy_shares(1.0, 0.0)


if __name__ == "__main__":
    unittest.main()
