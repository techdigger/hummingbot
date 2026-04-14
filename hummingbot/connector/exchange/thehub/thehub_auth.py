"""
TheHub EIP-712 signing.

Verified against typedData.ts (vtabunov/TheHub):
  - ONE_INCH_DOMAIN_NAME / VERSION  → buildOneInchOrderDomain
  - BACKEND_DOMAIN_NAME / VERSION   → BACKEND_INTENT_DOMAIN
  - ORDER_TYPES                     → ONE_INCH_ORDER_TYPES
  - CANCEL_INTENT_TYPES             → CANCEL_INTENT_TYPES
  - PRIVATE_SESSION_INTENT_TYPES    → PRIVATE_SESSION_TYPES

Key distinctions from an earlier placeholder version:
  - Limit orders use the 1inch LOP domain (with verifyingContract).
  - CancelIntent / PrivateSessionIntent use the backend domain (NO verifyingContract).
  - CancelIntent includes `market`, `owner`, `cancelNonce` (not just `maker`).
  - PrivateSessionIntent includes `nonce`.
"""

import random
import time
from typing import Any, Optional

from eth_account import Account
from eth_account.messages import encode_typed_data

from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest

# ---------------------------------------------------------------------------
# EIP-712 — 1inch v4 LOP (limit orders, signed against the LOP contract)
# ---------------------------------------------------------------------------
ONE_INCH_DOMAIN_NAME = "1inch Limit Order Protocol"
ONE_INCH_DOMAIN_VERSION = "4"

EIP712_DOMAIN_WITH_CONTRACT = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]

ONE_INCH_ORDER_TYPES = {
    "Order": [
        {"name": "salt", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "receiver", "type": "address"},
        {"name": "makerAsset", "type": "address"},
        {"name": "takerAsset", "type": "address"},
        {"name": "makingAmount", "type": "uint256"},
        {"name": "takingAmount", "type": "uint256"},
        {"name": "makerTraits", "type": "uint256"},
    ]
}

# ---------------------------------------------------------------------------
# EIP-712 — TheHub backend intents (cancel + private session, no verifyingContract)
# ---------------------------------------------------------------------------
BACKEND_DOMAIN_NAME = "The Hub Exchange Backend"
BACKEND_DOMAIN_VERSION = "1"

EIP712_DOMAIN_WITHOUT_CONTRACT = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
]

CANCEL_INTENT_TYPES = {
    "CancelIntent": [
        {"name": "market", "type": "string"},
        {"name": "owner", "type": "address"},
        {"name": "orderHash", "type": "bytes32"},
        {"name": "cancelNonce", "type": "uint256"},
        {"name": "deadline", "type": "uint256"},
    ]
}

PRIVATE_SESSION_INTENT_TYPES = {
    "PrivateSessionIntent": [
        {"name": "owner", "type": "address"},
        {"name": "issuedAt", "type": "uint256"},
        {"name": "expiry", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
    ]
}

# ---------------------------------------------------------------------------
# MakerTraits bit-field constants (mirrors typedData.ts)
# ---------------------------------------------------------------------------
UINT40_MAX = (1 << 40) - 1
ALLOW_MULTIPLE_FILLS_FLAG = 1 << 254
EXPIRATION_OFFSET = 80
NONCE_OFFSET = 120


class TheHubAuth(AuthBase):
    """
    Signs 1inch v4 orders and TheHub backend intents.

    :param private_key:       Hex-encoded private key (with or without 0x).
    :param verifying_contract: 1inch LOP contract address on Humanode.
    :param chain_id:          Humanode chain ID (default 5234).
    """

    def __init__(
        self,
        private_key: str,
        verifying_contract: str,
        chain_id: int = 5234,
    ) -> None:
        self._account = Account.from_key(private_key)
        self._verifying_contract = verifying_contract
        self._chain_id = chain_id

    @property
    def address(self) -> str:
        return self._account.address

    # ------------------------------------------------------------------
    # Domain helpers
    # ------------------------------------------------------------------

    def _lop_domain(self) -> dict:
        """1inch LOP domain — includes verifyingContract."""
        return {
            "name": ONE_INCH_DOMAIN_NAME,
            "version": ONE_INCH_DOMAIN_VERSION,
            "chainId": self._chain_id,
            "verifyingContract": self._verifying_contract,
        }

    def _backend_domain(self) -> dict:
        """TheHub backend domain — NO verifyingContract."""
        return {
            "name": BACKEND_DOMAIN_NAME,
            "version": BACKEND_DOMAIN_VERSION,
            "chainId": self._chain_id,
        }

    # ------------------------------------------------------------------
    # Low-level EIP-712 signer
    # ------------------------------------------------------------------

    def _sign_eip712(
        self,
        domain: dict,
        domain_type: list,
        types: dict,
        primary_type: str,
        message: dict,
    ) -> dict[str, str]:
        signable = encode_typed_data(full_message={
            "types": {"EIP712Domain": domain_type, **types},
            "domain": domain,
            "primaryType": primary_type,
            "message": message,
        })
        signed = self._account.sign_message(signable)
        return {
            "hash": "0x" + signed.message_hash.hex(),
            "signature": "0x" + signed.signature.hex(),
        }

    # ------------------------------------------------------------------
    # MakerTraits helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _random_nonce() -> int:
        left = (int(time.time() * 1000) & 0xFFFFFFFFFFFFFF) << 16
        right = random.randint(0, 0xFFFF)
        return (left | right) & UINT40_MAX

    @staticmethod
    def build_maker_traits(expires_at: int) -> int:
        """Encode the makerTraits uint256 bit-field. expires_at=0 means no expiry."""
        nonce = TheHubAuth._random_nonce()
        return (
            ALLOW_MULTIPLE_FILLS_FLAG
            | (expires_at << EXPIRATION_OFFSET)
            | (nonce << NONCE_OFFSET)
        )

    # ------------------------------------------------------------------
    # 1inch v4 LOP order signing
    # ------------------------------------------------------------------

    def sign_limit_order(self, order: dict[str, Any]) -> dict[str, str]:
        """
        Sign a 1inch v4 LOP order dict.

        :returns: {"orderHash": "0x...", "signature": "0x..."}
        """
        result = self._sign_eip712(
            domain=self._lop_domain(),
            domain_type=EIP712_DOMAIN_WITH_CONTRACT,
            types=ONE_INCH_ORDER_TYPES,
            primary_type="Order",
            message={
                "salt": int(order["salt"]),
                "maker": order["maker"],
                "receiver": order["receiver"],
                "makerAsset": order["makerAsset"],
                "takerAsset": order["takerAsset"],
                "makingAmount": int(order["makingAmount"]),
                "takingAmount": int(order["takingAmount"]),
                "makerTraits": int(order["makerTraits"]),
            },
        )
        return {"orderHash": result["hash"], "signature": result["signature"]}

    def hash_limit_order(self, order: dict[str, Any]) -> str:
        """EIP-712 hash of a limit order (without signing)."""
        return self.sign_limit_order(order)["orderHash"]

    def build_limit_order_data(
        self,
        side: str,
        price_e6: int,
        base_amount: int,
        expires_at: int,
        maker: Optional[str] = None,
        maker_asset: Optional[str] = None,
        taker_asset: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Build a LimitOrderV4Data dict from exchange units.

        Fee logic (mirrors fees.ts):
          quote_amount = base_amount * price_e6 / 10^18
          fee          = quote_amount * 3 / 10000
          buy  → making=quote+fee (USDC), taking=base (WEHMND)
          sell → making=base (WEHMND),    taking=quote-fee (USDC)

        :param maker_asset: override makerAsset (defaults to USDC for buy, WEHMND for sell)
        :param taker_asset: override takerAsset (defaults to WEHMND for buy, USDC for sell)
        """
        from hummingbot.connector.exchange.thehub import thehub_constants as C
        _maker = maker or self.address
        _ma = maker_asset or (C.USDC_ADDRESS if side == "buy" else C.WEHMND_ADDRESS)
        _ta = taker_asset or (C.WEHMND_ADDRESS if side == "buy" else C.USDC_ADDRESS)

        base_units = 10 ** 18
        quote_amount = base_amount * price_e6 // base_units
        fee_amount = quote_amount * C.FEE_BPS // C.BPS_DENOMINATOR

        if side == "buy":
            settlement_quote = quote_amount + fee_amount
            making_amount = str(settlement_quote)
            taking_amount = str(base_amount)
        else:
            settlement_quote = quote_amount - fee_amount
            making_amount = str(base_amount)
            taking_amount = str(settlement_quote)

        salt = str(int(time.time() * 1000)) + str(random.randint(0, 9_999))

        return {
            "salt": salt,
            "maker": _maker,
            "receiver": _maker,
            "makerAsset": _ma,
            "takerAsset": _ta,
            "makingAmount": making_amount,
            "takingAmount": taking_amount,
            "makerTraits": str(self.build_maker_traits(expires_at)),
        }

    # ------------------------------------------------------------------
    # TheHub backend cancel intent
    # ------------------------------------------------------------------

    def sign_cancel_intent(self, cancel: dict[str, Any]) -> dict[str, str]:
        """
        Sign a CancelIntent.

        cancel must contain: market, owner, orderHash (hex str or bytes32), cancelNonce, deadline
        :returns: {"hash": "0x...", "signature": "0x..."}
        """
        cancel = dict(cancel)
        if isinstance(cancel.get("orderHash"), str):
            order_hash_bytes = bytes.fromhex(cancel["orderHash"].removeprefix("0x"))
            if len(order_hash_bytes) != 32:
                raise ValueError(f"orderHash must be 32 bytes, got {len(order_hash_bytes)}")
            cancel["orderHash"] = order_hash_bytes
        return self._sign_eip712(
            domain=self._backend_domain(),
            domain_type=EIP712_DOMAIN_WITHOUT_CONTRACT,
            types=CANCEL_INTENT_TYPES,
            primary_type="CancelIntent",
            message=cancel,
        )

    def create_cancel_request(
        self,
        market: str,
        order_hash: str,
        deadline: Optional[int] = None,
    ) -> dict[str, Any]:
        """Build and sign cancel payload for POST /api/orderbook/cancel."""
        if deadline is None:
            deadline = int(time.time()) + 300
        cancel_nonce = int(time.time() * 1000)
        signed = self.sign_cancel_intent({
            "market": market,
            "owner": self.address,
            "orderHash": order_hash,
            "cancelNonce": cancel_nonce,
            "deadline": deadline,
        })
        return {
            "cancel": {
                "market": market,
                "owner": self.address,
                "orderHash": order_hash,
                "cancelNonce": cancel_nonce,
                "deadline": deadline,
            },
            "signature": signed["signature"],
        }

    # ------------------------------------------------------------------
    # TheHub backend private session intent
    # ------------------------------------------------------------------

    def sign_private_session_intent(self, intent: dict[str, Any]) -> dict[str, str]:
        """
        Sign a PrivateSessionIntent.

        intent must contain: owner, issuedAt, expiry, nonce
        :returns: {"hash": "0x...", "signature": "0x..."}
        """
        return self._sign_eip712(
            domain=self._backend_domain(),
            domain_type=EIP712_DOMAIN_WITHOUT_CONTRACT,
            types=PRIVATE_SESSION_INTENT_TYPES,
            primary_type="PrivateSessionIntent",
            message=intent,
        )

    def create_private_session_request(self, ttl_seconds: int = 900) -> dict[str, Any]:
        """Build and sign payload for POST /api/orderbook/private-session."""
        now = int(time.time())
        nonce = int(time.time() * 1000) & UINT40_MAX
        intent: dict[str, Any] = {
            "owner": self.address,
            "issuedAt": now,
            "expiry": now + ttl_seconds,
            "nonce": nonce,
        }
        signed = self.sign_private_session_intent(intent)
        return {
            "intent": intent,
            "signature": signed["signature"],
        }

    # ------------------------------------------------------------------
    # Hummingbot AuthBase protocol
    # ------------------------------------------------------------------

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """Pass-through: auth is embedded in request bodies."""
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        return request
