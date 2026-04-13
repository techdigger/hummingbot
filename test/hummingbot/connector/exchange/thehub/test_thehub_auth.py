import json
import os
from unittest import TestCase

from eth_account import Account
from eth_account.messages import encode_typed_data

from hummingbot.connector.exchange.thehub.thehub_auth import (
    CANCEL_INTENT_TYPES,
    ONE_INCH_ORDER_TYPES,
    PRIVATE_SESSION_INTENT_TYPES,
    TheHubAuth,
)

_FIXTURES_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "thehub_typed_data_fixtures.json")

with open(_FIXTURES_PATH) as f:
    _F = json.load(f)

PRIVATE_KEY = _F["meta"]["private_key"]
ADDRESS = _F["meta"]["address"]
VERIFYING_CONTRACT = _F["meta"]["verifying_contract"]
CHAIN_ID = _F["meta"]["chain_id"]
DOMAIN_NAME = _F["meta"]["domain_name"]
DOMAIN_VERSION = _F["meta"]["domain_version"]


def _make_auth() -> TheHubAuth:
    return TheHubAuth(
        private_key=PRIVATE_KEY,
        verifying_contract=VERIFYING_CONTRACT,
        chain_id=CHAIN_ID,
        domain_name=DOMAIN_NAME,
        domain_version=DOMAIN_VERSION,
    )


class TheHubAuthAddressTests(TestCase):
    def test_address_derived_from_private_key(self):
        auth = _make_auth()
        self.assertEqual(ADDRESS, auth.address)


class TheHubAuthOrderSigningTests(TestCase):
    def setUp(self):
        self.auth = _make_auth()
        self.sell = _F["sell_order"]
        self.buy = _F["buy_order"]

    def test_sell_order_hash_matches_fixture(self):
        result = self.auth.sign_limit_order(self.sell["order"])
        self.assertEqual(self.sell["expected_order_hash"], result["orderHash"])

    def test_sell_order_signature_matches_fixture(self):
        result = self.auth.sign_limit_order(self.sell["order"])
        self.assertEqual(self.sell["expected_signature"], result["signature"])

    def test_sell_order_signature_recovers_maker_address(self):
        result = self.auth.sign_limit_order(self.sell["order"])
        signable = encode_typed_data(full_message={
            "types": ONE_INCH_ORDER_TYPES,
            "domain": self.auth._domain(),
            "primaryType": "Order",
            "message": self.sell["order"],
        })
        recovered = Account.recover_message(signable, signature=result["signature"])
        self.assertEqual(ADDRESS, recovered)

    def test_buy_order_hash_matches_fixture(self):
        result = self.auth.sign_limit_order(self.buy["order"])
        self.assertEqual(self.buy["expected_order_hash"], result["orderHash"])

    def test_buy_order_signature_recovers_maker_address(self):
        result = self.auth.sign_limit_order(self.buy["order"])
        signable = encode_typed_data(full_message={
            "types": ONE_INCH_ORDER_TYPES,
            "domain": self.auth._domain(),
            "primaryType": "Order",
            "message": self.buy["order"],
        })
        recovered = Account.recover_message(signable, signature=result["signature"])
        self.assertEqual(ADDRESS, recovered)

    def test_hash_limit_order_equals_sign_limit_order_hash(self):
        self.assertEqual(
            self.auth.hash_limit_order(self.sell["order"]),
            self.auth.sign_limit_order(self.sell["order"])["orderHash"],
        )

    def test_sell_and_buy_order_hashes_differ(self):
        sell_hash = self.auth.hash_limit_order(self.sell["order"])
        buy_hash = self.auth.hash_limit_order(self.buy["order"])
        self.assertNotEqual(sell_hash, buy_hash)


class TheHubAuthCancelIntentTests(TestCase):
    def setUp(self):
        self.auth = _make_auth()
        self.fix = _F["cancel_intent"]

    def test_cancel_intent_hash_matches_fixture(self):
        result = self.auth.sign_cancel_intent(self.fix["intent"])
        self.assertEqual(self.fix["expected_hash"], result["hash"])

    def test_cancel_intent_signature_matches_fixture(self):
        result = self.auth.sign_cancel_intent(self.fix["intent"])
        self.assertEqual(self.fix["expected_signature"], result["signature"])

    def test_cancel_intent_signature_recovers_owner_address(self):
        result = self.auth.sign_cancel_intent(self.fix["intent"])
        order_hash_bytes = bytes.fromhex(self.fix["intent"]["orderHash"][2:])
        signable = encode_typed_data(full_message={
            "types": CANCEL_INTENT_TYPES,
            "domain": self.auth._domain(),
            "primaryType": "CancelIntent",
            "message": {**self.fix["intent"], "orderHash": order_hash_bytes},
        })
        recovered = Account.recover_message(signable, signature=result["signature"])
        self.assertEqual(ADDRESS, recovered)

    def test_create_cancel_request_shape(self):
        market = "HMND/USDC"
        order_hash = self.fix["intent"]["orderHash"]
        deadline = self.fix["intent"]["deadline"]
        req = self.auth.create_cancel_request(market, order_hash, deadline)
        self.assertEqual(market, req["market"])
        self.assertEqual(order_hash, req["orderHash"])
        self.assertEqual(deadline, req["deadline"])
        self.assertTrue(req["signature"].startswith("0x"))


class TheHubAuthPrivateSessionTests(TestCase):
    def setUp(self):
        self.auth = _make_auth()
        self.fix = _F["private_session_intent"]

    def test_private_session_hash_matches_fixture(self):
        result = self.auth.sign_private_session_intent(self.fix["intent"])
        self.assertEqual(self.fix["expected_hash"], result["hash"])

    def test_private_session_signature_matches_fixture(self):
        result = self.auth.sign_private_session_intent(self.fix["intent"])
        self.assertEqual(self.fix["expected_signature"], result["signature"])

    def test_private_session_signature_recovers_owner_address(self):
        result = self.auth.sign_private_session_intent(self.fix["intent"])
        signable = encode_typed_data(full_message={
            "types": PRIVATE_SESSION_INTENT_TYPES,
            "domain": self.auth._domain(),
            "primaryType": "PrivateSessionIntent",
            "message": self.fix["intent"],
        })
        recovered = Account.recover_message(signable, signature=result["signature"])
        self.assertEqual(ADDRESS, recovered)

    def test_create_private_session_request_shape(self):
        req = self.auth.create_private_session_request(ttl_seconds=3600)
        self.assertEqual(ADDRESS, req["owner"])
        self.assertIn("issuedAt", req)
        self.assertIn("expiry", req)
        self.assertEqual(req["expiry"] - req["issuedAt"], 3600)
        self.assertTrue(req["signature"].startswith("0x"))


class TheHubAuthPassThroughTests(TestCase):
    def setUp(self):
        self.auth = _make_auth()

    def test_rest_authenticate_is_passthrough(self):
        import asyncio
        from unittest.mock import MagicMock
        request = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(
            self.auth.rest_authenticate(request)
        )
        self.assertIs(request, result)
