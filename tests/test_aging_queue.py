"""Unit tests for aging queue starvation prevention in SunkGuard."""

import unittest

from core.controller import SunkGuardController
from core.resources import ResourceManager
from core.rng import SeededRNG
from core.workflow import Step, Workflow


class TestAgingQueue(unittest.TestCase):
    """SPEC.md Section 6.1: Aging priority guarantees no unbounded starvation."""

    def setUp(self):
        self.rng = SeededRNG(42)
        self.controller = SunkGuardController(self.rng, policy="medium")
        self.rm = ResourceManager()

    def _create_wf(self, wf_id: int, base: float, spent_work: int, wait: int) -> Workflow:
        step = Step.create("pro", 2, 3)
        wf = Workflow(
            id=wf_id,
            template_id="test",
            template_name="Test",
            name=f"Workflow #{wf_id}",
            steps=[step],
            pred_steps=[step.copy()],
            base_priority=base,
            spent_work=spent_work,
            wait_time=wait,
            total_planned_work=step.work,
        )
        return wf

    def test_aging_increases_priority_score(self):
        wf = self._create_wf(wf_id=1, base=1.0, spent_work=0, wait=0)
        # Score = base + wait * 0.35 + 1.2 * (work / 1000)
        # For wait=0: score = 1.0
        self.controller.schedule(tick=1, candidates=[wf], rm=self.rm)
        self.assertEqual(wf.score, 1.0)

        # For wait=10: score = 1.0 + 10 * 0.35 = 4.5
        wf.wait_time = 10
        self.controller.schedule(tick=11, candidates=[wf], rm=self.rm)
        self.assertEqual(wf.score, 1.0 + 10 * 0.35)

    def test_waiting_early_job_eventually_overtakes_high_sunk_job(self):
        # wf_sunk: arrived recently (wait=0), high work (3,000 SWU), base=1.0
        # Score_sunk = 1.0 + 0 + 1.2 * (3000 / 1000) = 4.6
        wf_sunk = self._create_wf(wf_id=1, base=1.0, spent_work=3000, wait=0)

        # wf_early: arrived earlier (wait=15), 0 work, base=1.0
        # Score_early = 1.0 + 15 * 0.35 + 0 = 6.25
        wf_early = self._create_wf(wf_id=2, base=1.0, spent_work=0, wait=15)

        candidates = [wf_sunk, wf_early]
        # Saturate Pro capacity so only 1 job can be scheduled
        self.rm.get("pro").in_use = self.rm.get("pro").cap - 2

        self.controller.schedule(tick=20, candidates=candidates, rm=self.rm)

        # The aged job (wf_early) should have higher score and be scheduled first!
        self.assertGreater(wf_early.score, wf_sunk.score)
        self.assertEqual(wf_early.state, "running")
        self.assertIn(wf_sunk.state, ("waiting", "queued"))


if __name__ == "__main__":
    unittest.main()
