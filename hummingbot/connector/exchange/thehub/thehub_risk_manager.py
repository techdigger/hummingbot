"""
TheHub risk manager / kill switch.

Aggregates signals the connector cannot recover from on its own and maps them
to a discrete risk state that the strategy layer observes. The state machine is
intentionally conservative:

  RUNNING  — normal operation.
  PAUSED   — transient fault (API errors, stale stream). New orders should be
             suppressed; in-flight orders are left alone. Auto-recovers when
             the underlying condition clears.
  HALTED   — non-recoverable fault (settlement rollback, balance mismatch).
             Requires explicit human reset. The connector should cancel open
             orders and refuse new ones.

Rationale: TheHub's 2-phase settlement means a backend "match" can be reverted
by an on-chain rollback. If Hummingbot already treated the match as a fill, the
strategy's view of inventory is wrong — only a human can reconcile. Likewise, a
balance mismatch against on-chain reality is never safe to auto-resume.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RiskState(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    HALTED = "halted"


class RiskEvent(Enum):
    API_ERROR = "api_error"
    API_OK = "api_ok"
    STREAM_STALE = "stream_stale"
    STREAM_OK = "stream_ok"
    SETTLEMENT_ROLLED_BACK = "settlement_rolled_back"
    BALANCE_MISMATCH = "balance_mismatch"
    MANUAL_RESET = "manual_reset"


@dataclass
class RiskStatus:
    state: RiskState = RiskState.RUNNING
    reason: Optional[str] = None
    halted_at_ms: Optional[int] = None
    active_faults: set[RiskEvent] = field(default_factory=set)

    @property
    def can_place_orders(self) -> bool:
        return self.state is RiskState.RUNNING

    @property
    def should_cancel_all(self) -> bool:
        return self.state is RiskState.HALTED


# Faults that auto-clear when their matching OK signal arrives. HALT faults
# are sticky and require MANUAL_RESET.
_TRANSIENT_CLEAR = {
    RiskEvent.API_ERROR: RiskEvent.API_OK,
    RiskEvent.STREAM_STALE: RiskEvent.STREAM_OK,
}

_HALT_EVENTS = {
    RiskEvent.SETTLEMENT_ROLLED_BACK,
    RiskEvent.BALANCE_MISMATCH,
}


class TheHubRiskManager:
    """Event-driven kill switch. Callers push events; state transitions follow."""

    def __init__(self) -> None:
        self._status = RiskStatus()

    @property
    def status(self) -> RiskStatus:
        return self._status

    @property
    def state(self) -> RiskState:
        return self._status.state

    def on_event(
        self,
        event: RiskEvent,
        reason: Optional[str] = None,
        timestamp_ms: Optional[int] = None,
    ) -> RiskStatus:
        if event in _HALT_EVENTS:
            self._status.state = RiskState.HALTED
            self._status.reason = reason or event.value
            self._status.halted_at_ms = timestamp_ms
            self._status.active_faults.add(event)
            return self._status

        if event is RiskEvent.MANUAL_RESET:
            self._status = RiskStatus()
            return self._status

        # OK signals clear their matching fault.
        for fault, ok in _TRANSIENT_CLEAR.items():
            if event is ok:
                self._status.active_faults.discard(fault)
                break

        # New transient fault → PAUSED (unless already HALTED, which is sticky).
        if event in _TRANSIENT_CLEAR and self._status.state is not RiskState.HALTED:
            self._status.active_faults.add(event)
            self._status.state = RiskState.PAUSED
            self._status.reason = reason or event.value
            return self._status

        # Auto-recover PAUSED → RUNNING once all transient faults cleared.
        if self._status.state is RiskState.PAUSED and not self._status.active_faults:
            self._status.state = RiskState.RUNNING
            self._status.reason = None

        return self._status
