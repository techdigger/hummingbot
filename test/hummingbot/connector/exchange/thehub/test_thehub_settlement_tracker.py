from decimal import Decimal
from unittest import TestCase

from hummingbot.connector.exchange.thehub.thehub_settlement_tracker import (
    InvalidSettlementTransition,
    SettlementState,
    TheHubSettlementTracker,
)


def _event(
    match_id: str = "m1",
    status: str = "matched",
    order_hash: str = "0xorder",
    base: str = "1000000000000000000",
    quote: str = "1000000",
    tx_hash: str | None = None,
    updated_at: int = 1710000000000,
):
    ev = {
        "matchId": match_id,
        "status": status,
        "orderHash": order_hash,
        "baseAmount": base,
        "quoteAmount": quote,
        "updatedAt": updated_at,
    }
    if tx_hash is not None:
        ev["txHash"] = tx_hash
    return ev


class TheHubSettlementTrackerTests(TestCase):
    def setUp(self):
        self.tracker = TheHubSettlementTracker()

    def test_new_match_creates_settlement(self):
        s = self.tracker.update(_event())
        self.assertEqual(SettlementState.MATCHED, s.state)
        self.assertEqual("m1", s.match_id)
        self.assertEqual(Decimal("1000000000000000000"), s.base_amount)

    def test_history_tracks_transitions(self):
        self.tracker.update(_event(status="matched"))
        self.tracker.update(_event(status="submitted", tx_hash="0xabc"))
        s = self.tracker.update(_event(status="settled", tx_hash="0xabc"))
        self.assertEqual(
            [SettlementState.MATCHED, SettlementState.SUBMITTED, SettlementState.SETTLED],
            s.history,
        )

    def test_tx_hash_captured_on_submit(self):
        self.tracker.update(_event(status="matched"))
        s = self.tracker.update(_event(status="submitted", tx_hash="0xabc"))
        self.assertEqual("0xabc", s.tx_hash)

    def test_terminal_settled_blocks_further_transitions(self):
        self.tracker.update(_event(status="matched"))
        self.tracker.update(_event(status="settled"))
        with self.assertRaises(InvalidSettlementTransition):
            self.tracker.update(_event(status="failed"))

    def test_terminal_rolled_back_blocks_further_transitions(self):
        self.tracker.update(_event(status="matched"))
        self.tracker.update(_event(status="rolled_back"))
        with self.assertRaises(InvalidSettlementTransition):
            self.tracker.update(_event(status="settled"))

    def test_rollback_alias_maps_to_rolled_back(self):
        self.tracker.update(_event(status="matched"))
        s = self.tracker.update(_event(status="rollback"))
        self.assertEqual(SettlementState.ROLLED_BACK, s.state)
        self.assertTrue(s.is_invalidated)
        self.assertTrue(s.is_terminal)

    def test_failed_can_retry_to_submitted(self):
        self.tracker.update(_event(status="matched"))
        self.tracker.update(_event(status="submitted", tx_hash="0xabc"))
        self.tracker.update(_event(status="failed"))
        s = self.tracker.update(_event(status="submitted", tx_hash="0xdef"))
        self.assertEqual(SettlementState.SUBMITTED, s.state)
        self.assertEqual("0xdef", s.tx_hash)

    def test_unknown_status_raises(self):
        with self.assertRaises(ValueError):
            self.tracker.update(_event(status="bogus"))

    def test_invalidated_returns_only_rolled_back(self):
        self.tracker.update(_event(match_id="m1", status="matched"))
        self.tracker.update(_event(match_id="m2", status="matched"))
        self.tracker.update(_event(match_id="m2", status="rolled_back"))
        invalidated = self.tracker.invalidated()
        self.assertEqual(1, len(invalidated))
        self.assertEqual("m2", invalidated[0].match_id)

    def test_pending_excludes_terminal(self):
        self.tracker.update(_event(match_id="m1", status="matched"))
        self.tracker.update(_event(match_id="m2", status="matched"))
        self.tracker.update(_event(match_id="m2", status="settled"))
        pending = self.tracker.pending()
        self.assertEqual(1, len(pending))
        self.assertEqual("m1", pending[0].match_id)

    def test_by_order_hash_groups_matches(self):
        self.tracker.update(_event(match_id="m1", order_hash="0xA", status="matched"))
        self.tracker.update(_event(match_id="m2", order_hash="0xA", status="matched"))
        self.tracker.update(_event(match_id="m3", order_hash="0xB", status="matched"))
        self.assertEqual(2, len(self.tracker.by_order_hash("0xA")))
        self.assertEqual(1, len(self.tracker.by_order_hash("0xB")))

    def test_get_returns_none_for_unknown(self):
        self.assertIsNone(self.tracker.get("missing"))

    def test_direct_settled_from_none_allowed(self):
        s = self.tracker.update(_event(status="settled"))
        self.assertEqual(SettlementState.SETTLED, s.state)

    def test_mixed_case_status_accepted(self):
        s = self.tracker.update(_event(status="MATCHED"))
        self.assertEqual(SettlementState.MATCHED, s.state)
        s2 = self.tracker.update(_event(status="Settled"))
        self.assertEqual(SettlementState.SETTLED, s2.state)

    def test_accessors_return_copies_not_live_refs(self):
        self.tracker.update(_event(status="matched"))
        snapshot = self.tracker.get("m1")
        snapshot.history.append(SettlementState.SETTLED)
        snapshot.state = SettlementState.SETTLED
        # Internal state must be untouched by mutation of the returned copy.
        live = self.tracker.get("m1")
        self.assertEqual(SettlementState.MATCHED, live.state)
        self.assertEqual([SettlementState.MATCHED], live.history)

    def test_update_return_is_copy(self):
        returned = self.tracker.update(_event(status="matched"))
        returned.state = SettlementState.ROLLED_BACK
        live = self.tracker.get("m1")
        self.assertEqual(SettlementState.MATCHED, live.state)

    def test_updated_at_zero_is_preserved(self):
        s = self.tracker.update(_event(status="matched", updated_at=0))
        self.assertEqual(0, s.last_updated_ms)

    def test_missing_updated_at_leaves_none(self):
        ev = _event(status="matched")
        del ev["updatedAt"]
        s = self.tracker.update(ev)
        self.assertIsNone(s.last_updated_ms)

    def test_direct_settled_without_order_hash(self):
        ev = _event(status="settled")
        del ev["orderHash"]
        s = self.tracker.update(ev)
        self.assertEqual(SettlementState.SETTLED, s.state)
        self.assertEqual("", s.order_hash)
