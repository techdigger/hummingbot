from decimal import Decimal
from unittest import TestCase

from hummingbot.connector.exchange.thehub.thehub_utils import (
    CENTRALIZED,
    DEFAULT_FEES,
    EXAMPLE_PAIR,
    KEYS,
    USE_ETHEREUM_WALLET,
    TheHubConfigMap,
    validate_evm_address,
)


class TheHubUtilsTests(TestCase):
    def test_default_connector_metadata(self):
        self.assertEqual("HMND-USDC", EXAMPLE_PAIR)
        self.assertEqual("thehub", KEYS.connector)
        self.assertFalse(CENTRALIZED)
        self.assertTrue(USE_ETHEREUM_WALLET)

    def test_fee_schema_is_three_bps(self):
        self.assertEqual(Decimal("0.0003"), DEFAULT_FEES.maker_percent_fee_decimal)
        self.assertEqual(Decimal("0.0003"), DEFAULT_FEES.taker_percent_fee_decimal)
        self.assertTrue(DEFAULT_FEES.buy_percent_fee_deducted_from_returns)

    def test_validate_evm_address_accepts_mixed_case_address(self):
        address = "0x000000000000000000000000000000000000dEaD"
        self.assertEqual(address, validate_evm_address(address))

    def test_validate_evm_address_rejects_invalid_address(self):
        with self.assertRaises(ValueError) as context:
            validate_evm_address("not-an-address")

        self.assertIn("Invalid EVM address", str(context.exception))

    def test_config_map_validates_wallet_and_protocol_addresses(self):
        config = TheHubConfigMap(
            thehub_wallet_address="0x000000000000000000000000000000000000dEaD",
            thehub_private_key="0x" + "1" * 64,
            thehub_lop_address="0x0000000000000000000000000000000000000001",
        )

        self.assertEqual("thehub", config.connector)
        self.assertEqual("0x000000000000000000000000000000000000dEaD", config.thehub_wallet_address.get_secret_value())
