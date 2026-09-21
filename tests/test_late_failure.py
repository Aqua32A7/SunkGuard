"""Unit tests for late failure classification in SunkGuard."""

import unittest

from core.workflow import Step, Workflow


class TestLateFailureDefinition(unittest.TestCase):
    """SPEC.md Section 3: Late failure = failed with >= 50% work done."""

    def _create_workflow(self, step_configs, spent_steps: int, state: str = "failed") -> Workflow:
        steps = [Step.create(r, u, d) for r, u, d in step_configs]
        total_work = sum(s.work for s in steps)
        total_tokens = sum(s.tokens for s in steps)

        spent_work = sum(steps[i].work for i in range(spent_steps))
        spent_tokens = sum(steps[i].tokens for i in range(spent_steps))

        return Workflow(
            id=1,
            template_id="test",
            template_name="Test Template",
            name="Test Run #1",
            steps=steps,
            pred_steps=[s.copy() for s in steps],
            step_index=spent_steps,
            state=state,  # type: ignore
            total_planned_work=total_work,
            total_planned_tokens=total_tokens,
            spent_work=spent_work,
            spent_tokens=spent_tokens,
        )

    def test_exact_50_percent_is_late_failure(self):
        # 2 identical steps: step 0 finishes, step 1 fails -> 50% work done
        configs = [("pro", 2, 3), ("pro", 2, 3)]
        wf = self._create_workflow(configs, spent_steps=1, state="failed")
        self.assertAlmostEqual(wf.work_fraction_done, 0.50)
        self.assertTrue(wf.is_late_failure)
        self.assertFalse(wf.is_early_failure)
        self.assertFalse(wf.is_starved)

    def test_over_50_percent_is_late_failure(self):
        # 4 steps: steps 0, 1, 2 finish (75% work done)
        configs = [("flash", 2, 2), ("flash", 2, 2), ("flash", 2, 2), ("flash", 2, 2)]
        wf = self._create_workflow(configs, spent_steps=3, state="failed")
        self.assertAlmostEqual(wf.work_fraction_done, 0.75)
        self.assertTrue(wf.is_late_failure)
        self.assertFalse(wf.is_early_failure)

    def test_under_50_percent_is_early_failure(self):
        # 4 steps: step 0 finishes (25% work done)
        configs = [("flash", 2, 2), ("flash", 2, 2), ("flash", 2, 2), ("flash", 2, 2)]
        wf = self._create_workflow(configs, spent_steps=1, state="failed")
        self.assertAlmostEqual(wf.work_fraction_done, 0.25)
        self.assertFalse(wf.is_late_failure)
        self.assertTrue(wf.is_early_failure)

    def test_zero_work_starved(self):
        configs = [("pro", 2, 3), ("pro", 2, 3)]
        wf = self._create_workflow(configs, spent_steps=0, state="starved")
        self.assertEqual(wf.work_fraction_done, 0.0)
        self.assertFalse(wf.is_late_failure)
        self.assertFalse(wf.is_early_failure)
        self.assertTrue(wf.is_starved)

    def test_successful_run_is_not_failure(self):
        configs = [("pro", 2, 3), ("pro", 2, 3)]
        wf = self._create_workflow(configs, spent_steps=2, state="done")
        self.assertEqual(wf.work_fraction_done, 1.0)
        self.assertFalse(wf.is_late_failure)
        self.assertFalse(wf.is_early_failure)


if __name__ == "__main__":
    unittest.main()
