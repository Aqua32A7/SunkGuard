"""Unit tests for metric mathematics in SunkGuard core."""

import unittest

from core.metrics import jain_fairness_index, percentile


class TestMetricsMath(unittest.TestCase):
    """SPEC.md Section 5: Metrics math verification."""

    def test_percentiles(self):
        data = list(range(1, 101))  # 1 to 100
        self.assertEqual(percentile(data, 0.50), 50.0)
        self.assertEqual(percentile(data, 0.95), 95.0)
        self.assertEqual(percentile(data, 0.99), 99.0)

    def test_empty_percentile(self):
        self.assertEqual(percentile([], 0.95), 0.0)

    def test_jain_fairness_equal_waits(self):
        # All jobs have identical wait -> J = 1.0 (perfect fairness)
        waits = [5, 5, 5, 5, 5]
        j = jain_fairness_index(waits)
        self.assertAlmostEqual(j, 1.0, places=4)

    def test_jain_fairness_bounded(self):
        # Jain index must always lie in [1/n, 1.0]
        waits = [0, 100, 2, 50, 0, 12]
        j = jain_fairness_index(waits)
        self.assertGreaterEqual(j, 1.0 / len(waits))
        self.assertLessEqual(j, 1.0)

    def test_jain_fairness_empty(self):
        self.assertEqual(jain_fairness_index([]), 1.0)


if __name__ == "__main__":
    unittest.main()
