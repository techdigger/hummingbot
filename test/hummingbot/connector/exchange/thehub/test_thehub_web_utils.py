from unittest import TestCase

from hummingbot.connector.exchange.thehub import thehub_constants as CONSTANTS
from hummingbot.connector.exchange.thehub import thehub_web_utils as web_utils


class TheHubWebUtilsTests(TestCase):
    def test_public_rest_url_trims_base_url(self):
        self.assertEqual(
            "https://api.example.com/api/orderbook/health",
            web_utils.public_rest_url("/api/orderbook/health", "https://api.example.com/"),
        )

    def test_chain_rest_path(self):
        self.assertEqual(
            "/api/orderbook/5234/orderbook",
            web_utils.chain_path(CONSTANTS.ORDERBOOK_SNAPSHOT_PATH),
        )

    def test_chain_rest_path_keeps_absolute_orderbook_paths(self):
        self.assertEqual(
            "/api/orderbook/private-session",
            web_utils.chain_path(CONSTANTS.PRIVATE_SESSION_PATH),
        )

    def test_private_session_header(self):
        self.assertEqual("x-orderbook-private-token", CONSTANTS.PRIVATE_SESSION_HEADER)

    def test_rest_url_preserves_query_string(self):
        self.assertEqual(
            "http://127.0.0.1:7303/api/orderbook/stream?market=HMND%2FUSDC",
            web_utils.public_rest_url(
                "/api/orderbook/stream?market=HMND%2FUSDC",
                "http://127.0.0.1:7303/",
            ),
        )
