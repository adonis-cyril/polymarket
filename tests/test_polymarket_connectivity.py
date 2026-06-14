"""Unit tests for utils.polymarket_connectivity."""

import inspect
import unittest

import websockets

from utils.polymarket_connectivity import get_ws_headers, ws_connect_header_kwargs


class WsConnectHeaderKwargsTests(unittest.TestCase):
    def test_uses_signature_compatible_header_param(self):
        headers = get_ws_headers()
        kwargs = ws_connect_header_kwargs(headers)

        self.assertEqual(len(kwargs), 1)
        param = next(iter(kwargs))
        self.assertIn(param, inspect.signature(websockets.connect).parameters)
        self.assertEqual(kwargs[param], headers)

    def test_additional_headers_on_websockets_12_plus(self):
        params = inspect.signature(websockets.connect).parameters
        if "additional_headers" not in params:
            self.skipTest("websockets < 12")

        kwargs = ws_connect_header_kwargs({"User-Agent": "test"})
        self.assertIn("additional_headers", kwargs)
        self.assertNotIn("extra_headers", kwargs)
