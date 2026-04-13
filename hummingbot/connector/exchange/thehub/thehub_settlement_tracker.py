"""
TheHub settlement state tracker.

TheHub's settlement model is 2-phase and not atomic:
  1. Backend matches an order and emits a fill signal.
  2. A resolver submits the matched trade on-chain.
  3. The on-chain tx either settles, fails (recoverable), or rolls back
     (non-recoverable — the backend-observed match is invalidated).

This tracker separates strategy-level fill state (which Hummingbot consumes
as the fill signal) from settlement-level finality. A rollback invalidates a
previously observed match and must trigger a high-severity event so the risk
manager can halt the bot.

NOTE: the event shape is inferred from the plan. When Phase 1 API ships, verify
field names against TheHub's `/api/orderbook/private-state` response for
`ownerSettlements`.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


class SettlementState(Enum):
    MATCHED = "matched"          # Backend observed the match — Hummingbot fill signal
    SUBMITTED = "submitted"      # Resolver submitted the tx on-chain
    SETTLED = "settled"          # On-chain confirmation — terminal good
    FAILED = "failed"            # Tx failed but backend match still valid (retry)
    ROLLED_BACK = "rolled_back"  # Backend reverted the match — terminal bad


# TheHub status string → SettlementState (inferred, TODO verify against API)
_STATUS_MAP = {
    "matched": SettlementState.MATCHED,
    "submitted": SettlementState.SUBMITTED,
    "settled": SettlementState.SETTLED,
    "failed": SettlementState.FAILED,
    "rolled_back": SettlementState.ROLLED_BACK,
    "rollback": SettlementState.ROLLED_BACK,
}


# Allowed transitions. Terminal states (SETTLED, ROLLED_BACK) cannot leave.
_ALLOWED_TRANSITIONS = {
    None: {SettlementState.MATCHED, SettlementState.SUBMITTED, SettlementState.SETTLED,
           SettlementState.FAILED, SettlementState.ROLLED_BACK},
    SettlementState.MATCHED: {SettlementState.SUBMITTED, SettlementState.SETTLED,
                              SettlementState.FAILED, SettlementState.ROLLED_BACK},
    SettlementState.SUBMITTED: {SettlementState.SETTLED, SettlementState.FAILED,
                                SettlementState.ROLLED_BACK},
    SettlementState.FAILED: {SettlementState.SUBMITTED, SettlementState.SETTLED,
                             SettlementState.ROLLED_BACK},
    SettlementState.SETTLED: set(),
    SettlementState.ROLLED_BACK: set(),
}


@dataclass
class Settlement:
    match_id: str
    order_hash: str
    state: SettlementState
    base_amount: Decimal
    quote_amount: Decimal
    tx_hash: Optional[str] = None
    last_updated_ms: int = 0
    history: list[SettlementState] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.state in (SettlementState.SETTLED, SettlementState.ROLLED_BACK)

    @property
    def is_invalidated(self) -> bool:
        return self.state is SettlementState.ROLLED_BACK


class InvalidSettlementTransition(Exception):
    pass


class TheHubSettlementTracker:
    """Tracks 2-phase settlement lifecycle for each matched fill."""

    def __init__(self) -> None:
        self._settlements: dict[str, Settlement] = {}

    def update(self, event: dict[str, Any]) -> Settlement:
        """Apply a settlement event. Returns the updated Settlement."""
        match_id = event["matchId"]
        status_str = event["status"]
        if status_str not in _STATUS_MAP:
            raise ValueError(f"Unknown settlement status: {status_str}")
        new_state = _STATUS_MAP[status_str]

        existing = self._settlements.get(match_id)
        prev_state = existing.state if existing else None

        if new_state not in _ALLOWED_TRANSITIONS[prev_state]:
            raise InvalidSettlementTransition(
                f"Invalid transition for match {match_id}: {prev_state} → {new_state}"
            )

        if existing is None:
            settlement = Settlement(
                match_id=match_id,
                order_hash=event["orderHash"],
                state=new_state,
                base_amount=Decimal(str(event.get("baseAmount", "0"))),
                quote_amount=Decimal(str(event.get("quoteAmount", "0"))),
                tx_hash=event.get("txHash"),
                last_updated_ms=int(event.get("updatedAt", 0)),
                history=[new_state],
            )
            self._settlements[match_id] = settlement
            return settlement

        existing.state = new_state
        existing.history.append(new_state)
        if event.get("txHash"):
            existing.tx_hash = event["txHash"]
        if event.get("updatedAt"):
            existing.last_updated_ms = int(event["updatedAt"])
        return existing

    def get(self, match_id: str) -> Optional[Settlement]:
        return self._settlements.get(match_id)

    def all(self) -> list[Settlement]:
        return list(self._settlements.values())

    def invalidated(self) -> list[Settlement]:
        """Return all settlements that were rolled back — these invalidate
        previously observed fills and must be reconciled."""
        return [s for s in self._settlements.values() if s.is_invalidated]

    def pending(self) -> list[Settlement]:
        """Return non-terminal settlements still awaiting finality."""
        return [s for s in self._settlements.values() if not s.is_terminal]

    def by_order_hash(self, order_hash: str) -> list[Settlement]:
        return [s for s in self._settlements.values() if s.order_hash == order_hash]
