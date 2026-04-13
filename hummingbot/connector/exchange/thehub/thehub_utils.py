from decimal import Decimal
from typing import Optional

from eth_utils import is_address
from pydantic import ConfigDict, Field, SecretStr, field_validator

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap
from hummingbot.core.data_type.trade_fee import TradeFeeSchema


DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.0003"),
    taker_percent_fee_decimal=Decimal("0.0003"),
    buy_percent_fee_deducted_from_returns=True,
)

CENTRALIZED = False
USE_ETHEREUM_WALLET = True
EXAMPLE_PAIR = "HMND-USDC"


def validate_evm_address(value: str) -> Optional[str]:
    if isinstance(value, str) and is_address(value):
        return value
    raise ValueError(f"Invalid EVM address: {value}")


class TheHubConfigMap(BaseConnectorConfigMap):
    connector: str = "thehub"
    thehub_api_url: str = Field(
        default="http://127.0.0.1:7303",
        json_schema_extra={
            "prompt": "Enter TheHub orderbook API URL",
            "is_secure": False,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    thehub_chain_id: int = Field(
        default=5234,
        json_schema_extra={
            "prompt": "Enter TheHub chain ID",
            "is_secure": False,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    thehub_wallet_address: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your TheHub wallet address",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    thehub_private_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your TheHub wallet private key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    thehub_lop_address: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter TheHub 1inch Limit Order Protocol address",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    thehub_rpc_url: SecretStr = Field(
        default="",
        json_schema_extra={
            "prompt": "Enter Humanode RPC URL",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": False,
        },
    )
    model_config = ConfigDict(title="thehub")

    @field_validator("thehub_wallet_address", "thehub_lop_address", mode="before")
    @classmethod
    def validate_address(cls, value: str) -> str:
        return validate_evm_address(value)

    @field_validator("thehub_private_key", mode="before")
    @classmethod
    def validate_private_key(cls, value: str) -> str:
        if isinstance(value, str):
            hex_val = value.removeprefix("0x")
            if len(hex_val) != 64 or not all(c in "0123456789abcdefABCDEF" for c in hex_val):
                raise ValueError(
                    "thehub_private_key must be a 32-byte hex string (64 hex chars, optionally prefixed with 0x)"
                )
        return value


KEYS = TheHubConfigMap.model_construct()
