"""Unit tests for DeltaP_failure estimator in SunkGuard core."""

import unittest

from core.controller import SunkGuardController
from core.resources import ResourceManager
from core.rng import SeededRNG
from core.workflow import Step, Workflow


class TestDeltaPFailureEstimator(unittest.TestCase):
    """SPEC.md Section 4: DeltaP_failure mathematical estimator properties."""

    def setUp(self):
        self.rng = SeededRNG(42)
        self.controller = SunkGuardController(self.rng, policy="medium")
        self.rm = ResourceManager()

    def _create_workflow(self, confidence: float = 0.85) -> Workflow:
        steps = [
            Step.create("search", 2, 3),
            Step.create("pro", 4, 4),
            Step.create("flash", 2, 3),
        ]
        return Workflow(
            id=1,
            template_id="research",
            template_name="Research",
            name="Research #1",
            steps=steps,
            pred_steps=[s.copy() for s in steps],
            step_index=0,
            predictor_confidence=confidence,
            total_planned_work=sum(s.work for s in steps),
        )

    def test_zero_contention_yields_zero_delta_p(self):
        # Under zero utilization, load ratio is 0 -> hazard is 0 -> delta_p is 0
        wf = self._create_workflow(confidence=0.9)
        delta_p, s_no_rsv, s_rsv = self.controller.estimate_delta_p_failure(wf, self.rm, horizon=2)
        self.assertAlmostEqual(delta_p, 0.0, places=4)
        self.assertAlmostEqual(s_no_rsv, 1.0, places=4)
        self.assertAlmostEqual(s_rsv, 1.0, places=4)

    def test_high_contention_yields_positive_delta_p(self):
        wf = self._create_workflow(confidence=0.85)
        # Saturate downstream resources: Search (cap 4) and Pro (cap 7)
        self.rm.get("search").in_use = 4
        self.rm.get("pro").in_use = 7

        delta_p, s_no_rsv, s_rsv = self.controller.estimate_delta_p_failure(wf, self.rm, horizon=2)
        self.assertGreater(delta_p, 0.0)
        self.assertGreater(s_rsv, s_no_rsv)
        self.assertLessEqual(delta_p, 1.0)

    def test_confidence_monotonicity(self):
        # Higher predictor confidence produces higher DeltaP_failure
        self.rm.get("search").in_use = 4
        self.rm.get("pro").in_use = 7

        wf = self._create_workflow()

        delta_p_low, _, _ = self.controller.estimate_delta_p_failure(
            wf, self.rm, horizon=2, confidence_override=0.50
        )
        delta_p_high, _, _ = self.controller.estimate_delta_p_failure(
            wf, self.rm, horizon=2, confidence_override=0.95
        )

        self.assertGreater(delta_p_high, delta_p_low)

    def test_zero_confidence_yields_zero_delta_p(self):
        self.rm.get("search").in_use = 4
        wf_zero = self._create_workflow()
        delta_p, s_no_rsv, s_rsv = self.controller.estimate_delta_p_failure(
            wf_zero, self.rm, horizon=2, confidence_override=0.0
        )
        self.assertAlmostEqual(delta_p, 0.0, places=4)
        self.assertAlmostEqual(s_rsv, s_no_rsv, places=4)


if __name__ == "__main__":
    unittest.main()
