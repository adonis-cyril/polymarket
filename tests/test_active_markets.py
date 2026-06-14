"""Unit tests for data.active_markets (mocked HTTP — no live API calls)."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from data.active_markets import (
    ActiveMarketsResult,
    fetch_active_markets_page,
    fetch_all_active_markets,
    load_cached_markets,
    markets_to_dicts,
    parse_market,
    save_markets_cache,
)

SAMPLE_RAW = {
    "id": "123",
    "question": "Will it rain?",
    "conditionId": "0xabc",
    "slug": "will-it-rain",
    "active": True,
    "closed": False,
    "archived": False,
    "clobTokenIds": '["111", "222"]',
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.6", "0.4"]',
    "volume": "1000.5",
    "volume24hr": 50.25,
    "liquidity": "200",
    "endDate": "2026-12-31T00:00:00Z",
    "events": [{"id": "99", "slug": "weather", "title": "Weather"}],
}


class ParseMarketTests(unittest.TestCase):
    def test_parse_market_json_string_fields(self):
        market = parse_market(SAMPLE_RAW)
        self.assertIsNotNone(market)
        assert market is not None
        self.assertEqual(market.market_id, "123")
        self.assertEqual(market.condition_id, "0xabc")
        self.assertEqual(market.clob_token_ids, ("111", "222"))
        self.assertEqual(market.outcomes, ("Yes", "No"))
        self.assertAlmostEqual(market.outcome_prices[0], 0.6)
        self.assertAlmostEqual(market.volume, 1000.5)
        self.assertEqual(market.event_title, "Weather")

    def test_parse_market_missing_condition_id(self):
        raw = dict(SAMPLE_RAW)
        raw.pop("conditionId")
        self.assertIsNone(parse_market(raw))


class FetchPageTests(unittest.TestCase):
    @patch("data.active_markets.gamma_get")
    def test_fetch_page_keyset_response(self, mock_gamma_get: MagicMock):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "markets": [SAMPLE_RAW],
            "next_cursor": "cursor-abc",
        }
        mock_gamma_get.return_value = mock_resp

        markets, cursor = fetch_active_markets_page()
        self.assertEqual(len(markets), 1)
        self.assertEqual(cursor, "cursor-abc")
        mock_gamma_get.assert_called_once()
        params = mock_gamma_get.call_args.kwargs["params"]
        self.assertEqual(params["active"], "true")
        self.assertEqual(params["closed"], "false")
        self.assertEqual(params["archived"], "false")

    @patch("data.active_markets.gamma_get")
    def test_fetch_page_passes_cursor(self, mock_gamma_get: MagicMock):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"markets": [], "next_cursor": None}
        mock_gamma_get.return_value = mock_resp

        fetch_active_markets_page(after_cursor="prev-cursor")
        params = mock_gamma_get.call_args.kwargs["params"]
        self.assertEqual(params["after_cursor"], "prev-cursor")


class FetchAllTests(unittest.TestCase):
    @patch("data.active_markets.fetch_active_markets_page")
    @patch("data.active_markets.time.sleep")
    def test_paginates_until_no_cursor(
        self, mock_sleep: MagicMock, mock_page: MagicMock,
    ):
        page1 = parse_market(SAMPLE_RAW)
        assert page1 is not None
        raw2 = dict(SAMPLE_RAW, id="456", conditionId="0xdef", slug="other")
        page2 = parse_market(raw2)
        assert page2 is not None

        mock_page.side_effect = [
            ([page1], "cursor-1"),
            ([page2], None),
        ]

        result = fetch_all_active_markets(page_delay=0)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.pages_fetched, 2)
        self.assertFalse(result.truncated)
        self.assertEqual(mock_page.call_count, 2)

    @patch("data.active_markets.fetch_active_markets_page")
    def test_max_pages_truncates(self, mock_page: MagicMock):
        page = parse_market(SAMPLE_RAW)
        assert page is not None
        mock_page.return_value = ([page], "more")

        result = fetch_all_active_markets(max_pages=1, page_delay=0)
        self.assertEqual(result.total, 1)
        self.assertTrue(result.truncated)


class CacheTests(unittest.TestCase):
    def test_cache_round_trip(self):
        market = parse_market(SAMPLE_RAW)
        assert market is not None
        result = ActiveMarketsResult(
            markets=[market],
            pages_fetched=1,
            fetched_at=time.time(),
            duration_seconds=1.5,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            save_markets_cache(path, result)
            loaded = load_cached_markets(path, ttl_seconds=999_999)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.total, 1)
            self.assertEqual(loaded.markets[0].slug, "will-it-rain")

    def test_markets_to_dicts_serializable(self):
        market = parse_market(SAMPLE_RAW)
        assert market is not None
        data = markets_to_dicts([market])
        json.dumps(data)


if __name__ == "__main__":
    unittest.main()
