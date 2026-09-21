"""Unit tests for Phase 2 Non-Oracle Predictor."""

import unittest

from core.predictor import NonOraclePredictor, train_predictor_on_dev_seeds
from core.seeds import DEV_SEEDS


class TestNonOraclePredictor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Train once on first 5 dev seeds for speed
        cls.predictor = train_predictor_on_dev_seeds(dev_seeds=DEV_SEEDS[:5], ticks=100)

    def test_predictor_trained_successfully(self):
        self.assertTrue(self.predictor.is_trained)
        self.assertGreater(len(self.predictor.transitions), 0)
        self.assertGreater(len(self.predictor.step_stats), 0)

    def test_non_oracle_prediction_structure(self):
        # Pass only observed history and template_id
        history = [
            {"resource_id": "search", "units": 2, "duration": 3, "work": 800, "tokens": 0}
        ]
        pred_steps, conf, est_work = self.predictor.predict_remaining(
            template_id="research",
            observed_history=history,
            current_step_idx=1,
            horizon=2,
            elapsed_ticks=5,
        )

        self.assertGreater(len(pred_steps), 0)
        self.assertLessEqual(len(pred_steps), 2)
        self.assertGreaterEqual(conf, 0.10)
        self.assertLessEqual(conf, 0.95)
        self.assertGreater(est_work, 800)

        # Ensure returned steps have valid attributes
        for s in pred_steps:
            self.assertIn("resource_id", s)
            self.assertIn("units", s)
            self.assertIn("duration", s)
            self.assertIn("work", s)
            self.assertGreater(s["units"], 0)

    def test_drift_penalty_over_elapsed_ticks(self):
        history = [
            {"resource_id": "vdb", "units": 2, "duration": 2, "work": 600, "tokens": 0}
        ]
        _, conf_fresh, _ = self.predictor.predict_remaining(
            template_id="codefix",
            observed_history=history,
            current_step_idx=1,
            horizon=2,
            elapsed_ticks=0,
        )
        _, conf_aged, _ = self.predictor.predict_remaining(
            template_id="codefix",
            observed_history=history,
            current_step_idx=1,
            horizon=2,
            elapsed_ticks=60,
        )
        self.assertGreater(conf_fresh, conf_aged)


if __name__ == "__main__":
    unittest.main()
