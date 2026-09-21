"""Unit tests for Phase 2 controller ablation variants and contention gating."""

import unittest

from core.controller import SunkGuardController
from core.resources import ResourceManager
from core.rng import SeededRNG
from core.workflow import Step, Workflow


class TestAblations(unittest.TestCase):

    def setUp(self):
        self.rng = SeededRNG(42)
        self.rm = ResourceManager()

    def _create_wf(self, base: float = 1.0, wait: int = 5, spent_work: int = 2000) -> Workflow:
        step = Step.create("pro", 2, 3)
        wf = Workflow(
            id=1,
            template_id="research",
            template_name="Research",
            name="Research Run #1",
            steps=[step],
            pred_steps=[step.copy()],
            step_index=0,
            base_priority=base,
            wait_time=wait,
            spent_work=spent_work,
            total_planned_work=step.work + spent_work,
        )
        return wf

    def test_admission_only_variant_allocates_zero_reservations(self):
        ctrl = SunkGuardController(self.rng, variant="admission_only")
        wf = self._create_wf()
        ctrl.plan(tick=1, active_workflows=[wf], rm=self.rm)
        self.assertEqual(len(ctrl.reservations), 0)

    def test_prediction_reservation_progress_off(self):
        # Progress weighting OFF: score = base + wait * aging (sunk work contribution is 0)
        ctrl = SunkGuardController(self.rng, variant="prediction_reservation")
        wf = self._create_wf(base=1.0, wait=6, spent_work=5000)
        ctrl.schedule(tick=1, candidates=[wf], rm=self.rm)
        expected_score = 1.0 + 6 * ctrl.policy_config.aging
        self.assertAlmostEqual(wf.score, expected_score)

    def test_prediction_reservation_progress_no_aging(self):
        # Wait aging OFF: score = base + weight * (work / 1000) (wait contribution is 0)
        ctrl = SunkGuardController(self.rng, variant="prediction_reservation_progress")
        wf = self._create_wf(base=1.0, wait=10, spent_work=2000)
        ctrl.schedule(tick=1, candidates=[wf], rm=self.rm)
        expected_score = 1.0 + ctrl.policy_config.weight * (2000 / 1000.0)
        self.assertAlmostEqual(wf.score, expected_score)

    def test_full_sunkguard_both_progress_and_aging(self):
        ctrl = SunkGuardController(self.rng, variant="full_sunkguard")
        wf = self._create_wf(base=1.0, wait=4, spent_work=2000)
        ctrl.schedule(tick=1, candidates=[wf], rm=self.rm)
        expected_score = 1.0 + 4 * ctrl.policy_config.aging + ctrl.policy_config.weight * (2000 / 1000.0)
        self.assertAlmostEqual(wf.score, expected_score)

    def test_contention_gating_at_low_load(self):
        # When resource utilization is low (rho <= 0.40), reservations are kept soft
        ctrl = SunkGuardController(self.rng, variant="full_sunkguard")
        wf = self._create_wf(spent_work=4000)
        wf.observed_history.append({"resource_id": "search", "units": 2, "duration": 3, "work": 800, "tokens": 0})
        # pro has 0 in_use and 0 hard_reserved -> rho = 0 <= 0.40
        ctrl.plan(tick=1, active_workflows=[wf], rm=self.rm)
        for rsv in ctrl.reservations:
            self.assertEqual(rsv.kind, "soft")


if __name__ == "__main__":
    unittest.main()
