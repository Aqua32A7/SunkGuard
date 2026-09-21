"""Unit tests for bit-identical reproducibility in SunkGuard core."""

import hashlib
import json
import unittest

from core.metrics import collect_metrics
from core.sim import SimulationConfig, SimulationEngine


class TestBitIdenticalReproducibility(unittest.TestCase):
    """Verifies that runs with the same seed yield 100% bit-identical traces and metrics."""

    def _run_and_hash(self, seed: int, ticks: int = 150, is_sunkguard: bool = True) -> tuple[str, dict]:
        engine = SimulationEngine(SimulationConfig(seed=seed, total_ticks=ticks, is_sunkguard=is_sunkguard))
        engine.run()
        metrics = collect_metrics(engine).to_dict()

        trace = []
        for l in engine.controller.log:
            trace.append(f"{l.tick}:{l.kind}:{l.message}")
        for snap in engine.history_series:
            trace.append(f"{snap.tick}:{snap.used_capacity}:{snap.hard_reserved_capacity}:{snap.cumulative_tokens}")

        payload = ("\n".join(trace) + json.dumps(metrics, sort_keys=True)).encode("utf-8")
        sha = hashlib.sha256(payload).hexdigest()
        return sha, metrics

    def test_sunkguard_deterministic_seed_42(self):
        sha1, m1 = self._run_and_hash(42, ticks=150, is_sunkguard=True)
        sha2, m2 = self._run_and_hash(42, ticks=150, is_sunkguard=True)
        self.assertEqual(sha1, sha2)
        self.assertEqual(m1, m2)

    def test_sunkguard_deterministic_seed_7(self):
        sha1, m1 = self._run_and_hash(7, ticks=150, is_sunkguard=True)
        sha2, m2 = self._run_and_hash(7, ticks=150, is_sunkguard=True)
        self.assertEqual(sha1, sha2)
        self.assertEqual(m1, m2)

    def test_baseline_deterministic_seed_99(self):
        sha1, m1 = self._run_and_hash(99, ticks=150, is_sunkguard=False)
        sha2, m2 = self._run_and_hash(99, ticks=150, is_sunkguard=False)
        self.assertEqual(sha1, sha2)
        self.assertEqual(m1, m2)

    def test_different_seeds_produce_different_traces(self):
        sha1, _ = self._run_and_hash(101, ticks=100, is_sunkguard=True)
        sha2, _ = self._run_and_hash(102, ticks=100, is_sunkguard=True)
        self.assertNotEqual(sha1, sha2)


if __name__ == "__main__":
    unittest.main()
