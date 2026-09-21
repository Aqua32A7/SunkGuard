"""Unit tests for SunkGuard runtime manager, canonical concepts, and FastAPI REST API.

Tests:
1. Canonical data models and EWMA tracking formula.
2. Decision records and Protection Value calculation.
3. Scene A (80/10 protection demo) progression across phases 1..7.
4. Scene B (prediction mismatch & recovery) event generation.
5. Scene C (policy mode switching between Light, Medium, Aggressive).
6. Gemini provider adapter fallback behavior.
7. FastAPI HTTP endpoints (/api/overview, /api/workflows, /api/policy, etc.).
"""

import unittest
from fastapi.testclient import TestClient

from core.canonical import (
    CANONICAL_POLICIES,
    CanonicalEventType,
    CanonicalWorkflowState,
    DecisionRecord,
    EWMATracker,
    PolicyMode,
    ReservationKind,
)
from core.gemini_adapter import GeminiProviderAdapter
from core.runtime import SunkGuardRuntimeManager
from server import app


class TestCanonicalAndRuntime(unittest.TestCase):

    def setUp(self):
        self.runtime = SunkGuardRuntimeManager(seed=42)
        self.client = TestClient(app)

    def test_canonical_states_and_events(self):
        """Verify canonical enum values exist according to the spec."""
        self.assertEqual(CanonicalWorkflowState.CREATED.value, "CREATED")
        self.assertEqual(CanonicalWorkflowState.RUNNING.value, "RUNNING")
        self.assertEqual(CanonicalWorkflowState.WAITING.value, "WAITING")
        self.assertEqual(CanonicalWorkflowState.COMPLETED.value, "COMPLETED")
        self.assertEqual(CanonicalWorkflowState.FAILED.value, "FAILED")

        self.assertIn("PREDICTION_MISMATCH", [e.value for e in CanonicalEventType])
        self.assertIn("RESOURCE_RESERVED", [e.value for e in CanonicalEventType])
        self.assertIn("RESOURCE_RELEASED", [e.value for e in CanonicalEventType])

    def test_ewma_formula(self):
        """Correction 7: Verify EWMA_t = alpha * observed_t + (1 - alpha) * EWMA_(t-1)."""
        tracker = EWMATracker(alpha=0.30)
        # First observation sets baseline
        val1 = tracker.update("tokens", 100.0)
        self.assertEqual(val1, 100.0)

        # Second observation: 0.3 * 200 + 0.7 * 100 = 60 + 70 = 130
        val2 = tracker.update("tokens", 200.0)
        self.assertAlmostEqual(val2, 130.0, places=4)

        # Third observation: 0.3 * 100 + 0.7 * 130 = 30 + 91 = 121
        val3 = tracker.update("tokens", 100.0)
        self.assertAlmostEqual(val3, 121.0, places=4)

    def test_protection_value_formula(self):
        """Correction 8: Verify PV = work_at_risk * Delta_P_fail / normalized_capacity_cost."""
        work_at_risk = 42.80
        delta_p = 0.32
        norm_cost = 2.83
        pv = self.runtime.compute_protection_value(work_at_risk, delta_p, norm_cost)
        self.assertAlmostEqual(pv, 4.84, delta=0.01)

    def test_scene_a_demo_step_progression(self):
        """Correction 18 (Scene A): Verify 7-step sequence of 80/10 protection demo."""
        # Step through all 7 phases
        for expected_phase in range(1, 8):
            res = self.runtime.execute_demo_step()
            self.assertEqual(res["phase"], expected_phase)
            self.assertTrue(len(res["notice"]) > 0)

        # In phase 5, wf-092 completes
        # In phase 6, reservation releases
        # In phase 7, wf-104 is admitted
        self.assertEqual(self.runtime.workflows_store["wf-092"]["status"], "COMPLETED")
        self.assertEqual(self.runtime.reservations_store["res-441"]["status"], "RELEASED")
        self.assertEqual(self.runtime.workflows_store["wf-104"]["status"], "RUNNING")

    def test_scene_b_force_mismatch(self):
        """Correction 18 (Scene B): Verify prediction mismatch triggers stale reservation release and re-planning."""
        res = self.runtime.force_mismatch()
        self.assertTrue(res["success"])
        # Check event log contains PREDICTION_MISMATCH
        event_types = [e.event_type for e in self.runtime.events]
        self.assertIn(CanonicalEventType.PREDICTION_MISMATCH, event_types)
        self.assertIn(CanonicalEventType.RESOURCE_RELEASED, event_types)
        self.assertIn(CanonicalEventType.RESOURCE_RESERVED, event_types)

    def test_scene_c_policy_mode_change(self):
        """Correction 12: Verify policy mode switching between Light, Medium, Aggressive."""
        self.runtime.set_policy_mode(PolicyMode.LIGHT)
        self.assertEqual(self.runtime.policy_mode, PolicyMode.LIGHT)
        self.assertEqual(self.runtime.policy_def.prediction_horizon, 2)

        self.runtime.set_policy_mode(PolicyMode.AGGRESSIVE)
        self.assertEqual(self.runtime.policy_mode, PolicyMode.AGGRESSIVE)
        self.assertEqual(self.runtime.policy_def.prediction_horizon, 6)
        self.assertEqual(self.runtime.policy_def.reservation_ceiling, 80)

    def test_gemini_adapter_simulated_fallback(self):
        """Correction 19: Verify Gemini adapter operates cleanly without credentials."""
        adapter = GeminiProviderAdapter(api_key="")
        res = adapter.execute_prompt("Test prompt for SunkGuard")
        self.assertTrue(res.success)
        self.assertFalse(res.is_live)
        self.assertGreater(res.total_tokens, 0)
        self.assertIn("Simulated response", res.response_text)

    def test_api_overview_endpoint(self):
        """Correction 13: Verify GET /api/overview returns complete schema required by React."""
        response = self.client.get("/api/overview")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("workflows", data)
        self.assertIn("resources", data)
        self.assertIn("reservations", data)
        self.assertIn("metrics", data)
        self.assertIn("events", data)
        self.assertIn("policy", data)
        self.assertIn("prediction", data)
        self.assertIn("experiment", data)

    def test_api_workflows_and_policy(self):
        """Verify workflow listing and policy update endpoints."""
        wf_resp = self.client.get("/api/workflows")
        self.assertEqual(wf_resp.status_code, 200)
        self.assertIsInstance(wf_resp.json(), list)

        pol_resp = self.client.post("/api/policy", json={"mode": "Light"})
        self.assertEqual(pol_resp.status_code, 200)
        self.assertEqual(pol_resp.json()["mode"], "Light")

    def test_api_demo_endpoints(self):
        """Verify demo control endpoints."""
        step_resp = self.client.post("/api/demo/step")
        self.assertEqual(step_resp.status_code, 200)
        self.assertIn("phase", step_resp.json())

        mismatch_resp = self.client.post("/api/demo/mismatch")
        self.assertEqual(mismatch_resp.status_code, 200)
        self.assertTrue(mismatch_resp.json()["success"])


if __name__ == "__main__":
    unittest.main()
