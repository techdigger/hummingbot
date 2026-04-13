from unittest import TestCase

from hummingbot.connector.exchange.thehub.thehub_risk_manager import (
    RiskEvent,
    RiskState,
    TheHubRiskManager,
)


class TheHubRiskManagerTests(TestCase):
    def setUp(self):
        self.rm = TheHubRiskManager()

    def test_initial_state_is_running(self):
        self.assertEqual(RiskState.RUNNING, self.rm.state)
        self.assertTrue(self.rm.status.can_place_orders)
        self.assertFalse(self.rm.status.should_cancel_all)

    def test_api_error_pauses(self):
        self.rm.on_event(RiskEvent.API_ERROR, reason="503")
        self.assertEqual(RiskState.PAUSED, self.rm.state)
        self.assertFalse(self.rm.status.can_place_orders)
        self.assertEqual("503", self.rm.status.reason)

    def test_api_ok_resumes_from_api_error(self):
        self.rm.on_event(RiskEvent.API_ERROR)
        self.rm.on_event(RiskEvent.API_OK)
        self.assertEqual(RiskState.RUNNING, self.rm.state)

    def test_stream_stale_pauses(self):
        self.rm.on_event(RiskEvent.STREAM_STALE)
        self.assertEqual(RiskState.PAUSED, self.rm.state)

    def test_multiple_faults_require_all_to_clear(self):
        self.rm.on_event(RiskEvent.API_ERROR)
        self.rm.on_event(RiskEvent.STREAM_STALE)
        self.rm.on_event(RiskEvent.API_OK)
        self.assertEqual(RiskState.PAUSED, self.rm.state)
        self.rm.on_event(RiskEvent.STREAM_OK)
        self.assertEqual(RiskState.RUNNING, self.rm.state)

    def test_settlement_rollback_halts(self):
        self.rm.on_event(RiskEvent.SETTLEMENT_ROLLED_BACK, reason="match m1", timestamp_ms=1710000000000)
        self.assertEqual(RiskState.HALTED, self.rm.state)
        self.assertTrue(self.rm.status.should_cancel_all)
        self.assertFalse(self.rm.status.can_place_orders)
        self.assertEqual(1710000000000, self.rm.status.halted_at_ms)

    def test_balance_mismatch_halts(self):
        self.rm.on_event(RiskEvent.BALANCE_MISMATCH, reason="USDC drift")
        self.assertEqual(RiskState.HALTED, self.rm.state)

    def test_halt_is_sticky_across_ok_signals(self):
        self.rm.on_event(RiskEvent.SETTLEMENT_ROLLED_BACK)
        self.rm.on_event(RiskEvent.API_OK)
        self.rm.on_event(RiskEvent.STREAM_OK)
        self.assertEqual(RiskState.HALTED, self.rm.state)

    def test_manual_reset_clears_halt(self):
        self.rm.on_event(RiskEvent.SETTLEMENT_ROLLED_BACK)
        self.rm.on_event(RiskEvent.MANUAL_RESET)
        self.assertEqual(RiskState.RUNNING, self.rm.state)
        self.assertIsNone(self.rm.status.reason)
        self.assertEqual(set(), self.rm.status.active_faults)

    def test_halt_overrides_existing_pause(self):
        self.rm.on_event(RiskEvent.API_ERROR)
        self.assertEqual(RiskState.PAUSED, self.rm.state)
        self.rm.on_event(RiskEvent.BALANCE_MISMATCH)
        self.assertEqual(RiskState.HALTED, self.rm.state)

    def test_redundant_ok_is_noop(self):
        self.rm.on_event(RiskEvent.API_OK)
        self.assertEqual(RiskState.RUNNING, self.rm.state)

    def test_status_is_defensive_copy(self):
        self.rm.on_event(RiskEvent.API_ERROR)
        snapshot = self.rm.status
        snapshot.state = RiskState.RUNNING
        snapshot.active_faults.clear()
        self.assertEqual(RiskState.PAUSED, self.rm.state)
        self.assertIn(RiskEvent.API_ERROR, self.rm.status.active_faults)

    def test_halt_records_fault_in_active_faults(self):
        self.rm.on_event(RiskEvent.SETTLEMENT_ROLLED_BACK)
        self.assertIn(RiskEvent.SETTLEMENT_ROLLED_BACK, self.rm.status.active_faults)

    def test_manual_reset_from_running_is_noop(self):
        self.rm.on_event(RiskEvent.MANUAL_RESET)
        self.assertEqual(RiskState.RUNNING, self.rm.state)
        self.assertEqual(set(), self.rm.status.active_faults)

    def test_reentry_after_manual_reset(self):
        self.rm.on_event(RiskEvent.SETTLEMENT_ROLLED_BACK)
        self.rm.on_event(RiskEvent.MANUAL_RESET)
        self.rm.on_event(RiskEvent.API_ERROR)
        self.assertEqual(RiskState.PAUSED, self.rm.state)
        self.rm.on_event(RiskEvent.API_OK)
        self.assertEqual(RiskState.RUNNING, self.rm.state)
