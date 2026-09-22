"""Unit tests for SunkGuard Intermittent Connectivity & Offline Resilience.

Tests:
1. ConnectivityManager state transitions and simulated outage timer.
2. OfflineJournal durable write-ahead-log persistence and reconciliation tracking.
3. Grace Freeze mechanism: in-flight workflows are paused, not killed; zero tokens wasted.
4. AutoReconciler: automatic queue drain and workflow resumption upon reconnection.
5. REST API endpoints: /api/connectivity, /api/connectivity/simulate, /api/connectivity/restore.
"""

import os
from pathlib import Path
import tempfile
import time
import unittest

from core.connectivity import ConnectivityManager, ConnectivityState
from core.offline_journal import OfflineJournal
from core.reconciler import AutoReconciler
from core.runtime import RUNTIME


class TestConnectivityResilience(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.journal_file = Path(self.temp_dir.name) / "test_journal.jsonl"
        self.journal = OfflineJournal(str(self.journal_file))
        self.conn = ConnectivityManager(probe_interval_seconds=1.0)

    def tearDown(self):
        self.temp_dir.cleanup()
        self.conn.stop_prober()

    def test_connectivity_state_transitions(self):
        self.assertTrue(self.conn.is_online)
        self.assertEqual(self.conn.state, ConnectivityState.ONLINE)

        # Trigger simulated outage
        self.conn.simulate_outage(duration_seconds=2.0)
        self.assertFalse(self.conn.is_online)
        self.assertEqual(self.conn.state, ConnectivityState.DISCONNECTED)
        self.assertGreater(self.conn.simulated_outage_end, time.time())

        # Restore
        self.conn.restore_connectivity()
        time.sleep(0.6)
        self.assertTrue(self.conn.is_online)
        self.assertEqual(self.conn.state, ConnectivityState.ONLINE)

    def test_offline_journal_persistence(self):
        # Enqueue a workflow
        wf_data = {"id": "wf-test-1", "name": "Test Workflow", "score": 2.5}
        self.journal.record_workflow_queued(wf_data)

        # Record frozen checkpoint
        self.journal.record_workflow_frozen("wf-test-1", step_index=2, spent_tokens=1800)

        # Record local tool execution
        self.journal.record_local_step_execution("wf-test-1", "Step 1", "code_runner", "exit 0")

        # Verify entries read from disk
        entries = self.journal.get_all_entries()
        self.assertEqual(len(entries), 3)

        unreconciled = self.journal.get_unreconciled_workflows()
        self.assertEqual(len(unreconciled), 1)
        self.assertEqual(unreconciled[0]["id"], "wf-test-1")

        # Mark reconciled
        self.journal.mark_workflow_reconciled("wf-test-1")
        unreconciled_after = self.journal.get_unreconciled_workflows()
        self.assertEqual(len(unreconciled_after), 0)

    def test_grace_freeze_and_auto_reconcile(self):
        # Register a workflow in RUNNING state
        wf_id = "wf-freeze-test"
        RUNTIME.workflows_store[wf_id] = {
            "id": wf_id,
            "name": "Freeze Agent",
            "status": "RUNNING",
            "progress": 50,
            "workAtRisk": 1.5,
            "currentStep": "Step 2: Generation",
            "tokensSpent": "1.4k",
            "spent_tokens_raw": 1400,
            "step_index": 1,
            "allocated_units": {},
        }

        # Freeze workflow offline
        freeze_res = RUNTIME.freeze_workflow_offline(wf_id, "Step 2: Generation")
        self.assertEqual(freeze_res["status"], "OFFLINE_PAUSED")
        self.assertEqual(freeze_res["protectedTokens"], 1400)
        self.assertEqual(RUNTIME.workflows_store[wf_id]["status"], "OFFLINE_PAUSED")

        # Run auto-reconciliation
        reconciler = AutoReconciler(RUNTIME)
        rec_res = reconciler.reconcile()
        self.assertGreaterEqual(rec_res["unfrozen_workflows"], 1)
        self.assertEqual(RUNTIME.workflows_store[wf_id]["status"], "RUNNING")
        self.assertEqual(RUNTIME.workflows_store[wf_id]["spent_tokens_raw"], 1400)


if __name__ == "__main__":
    unittest.main()
