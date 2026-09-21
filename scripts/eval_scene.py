#!/usr/bin/env python3
"""Evaluates the 80/10 contention scene across >= 30 seeds/injection times.

Measures:
1. Near-done run (Candidate-A, ~87% completed):
   - Finish rate with vs without SunkGuard
   - Sunk tokens lost
2. Heavy new runs (Burst runs B1..B6 demanding 13 units of Flash):
   - Finish rate with vs without SunkGuard
   - Mean wait time with vs without SunkGuard
   - Starvation / failure rate
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.sim import SimulationConfig, SimulationEngine


def evaluate_contention_scene(seeds: list[int], injection_tick: int = 10, ticks_after: int = 30):
    results_base = []
    results_sg = []

    for s in seeds:
        # 1. Baseline
        e_b = SimulationEngine(SimulationConfig(seed=s, total_ticks=100, is_sunkguard=False))
        e_b.run(ticks=injection_tick)
        wf_a_b, burst_b = e_b.inject_demo_scene()
        e_b.run(ticks=ticks_after)

        burst_b_done = sum(1 for w in burst_b if w.state == "done")
        burst_b_waits = [w.wait_time for w in burst_b]

        results_base.append({
            "seed": s,
            "wf_a_state": wf_a_b.state,
            "wf_a_lost_tokens": wf_a_b.spent_tokens if wf_a_b.state == "failed" else 0,
            "burst_done_count": burst_b_done,
            "burst_total": len(burst_b),
            "burst_mean_wait": sum(burst_b_waits) / len(burst_b),
        })

        # 2. SunkGuard
        e_s = SimulationEngine(SimulationConfig(seed=s, total_ticks=100, is_sunkguard=True, policy="medium"))
        e_s.run(ticks=injection_tick)
        wf_a_s, burst_s = e_s.inject_demo_scene()
        e_s.run(ticks=ticks_after)

        burst_s_done = sum(1 for w in burst_s if w.state == "done")
        burst_s_waits = [w.wait_time for w in burst_s]

        results_sg.append({
            "seed": s,
            "wf_a_state": wf_a_s.state,
            "wf_a_lost_tokens": wf_a_s.spent_tokens if wf_a_s.state == "failed" else 0,
            "burst_done_count": burst_s_done,
            "burst_total": len(burst_s),
            "burst_mean_wait": sum(burst_s_waits) / len(burst_s),
        })

    n = len(seeds)
    a_done_base = sum(1 for r in results_base if r["wf_a_state"] == "done")
    a_done_sg = sum(1 for r in results_sg if r["wf_a_state"] == "done")

    a_lost_base = sum(r["wf_a_lost_tokens"] for r in results_base) / n
    a_lost_sg = sum(r["wf_a_lost_tokens"] for r in results_sg) / n

    burst_done_base = sum(r["burst_done_count"] for r in results_base) / (n * 6)
    burst_done_sg = sum(r["burst_done_count"] for r in results_sg) / (n * 6)

    burst_wait_base = sum(r["burst_mean_wait"] for r in results_base) / n
    burst_wait_sg = sum(r["burst_mean_wait"] for r in results_sg) / n

    return {
        "seeds_tested": n,
        "near_done_run": {
            "baseline_finish_rate": a_done_base / n,
            "sunkguard_finish_rate": a_done_sg / n,
            "baseline_mean_lost_tokens": a_lost_base,
            "sunkguard_mean_lost_tokens": a_lost_sg,
        },
        "heavy_new_runs": {
            "baseline_finish_rate": burst_done_base,
            "sunkguard_finish_rate": burst_done_sg,
            "baseline_mean_wait_ticks": burst_wait_base,
            "sunkguard_mean_wait_ticks": burst_wait_sg,
        },
    }


if __name__ == "__main__":
    test_seeds = list(range(1, 36))  # 35 seeds
    print(f"Evaluating 80/10 scene across {len(test_seeds)} seeds...")
    stats = evaluate_contention_scene(test_seeds)

    print("\n### 80/10 Contention Scene Evaluation (35 Seeds)")
    print(f"- **Near-Done Run (Candidate-A, 87% work done):**")
    print(f"  * Baseline Finish Rate: {stats['near_done_run']['baseline_finish_rate']*100:.1f}%")
    print(f"  * SunkGuard Finish Rate: {stats['near_done_run']['sunkguard_finish_rate']*100:.1f}%")
    print(f"  * Baseline Mean Tokens Lost: {stats['near_done_run']['baseline_mean_lost_tokens']:,.0f} tokens")
    print(f"  * SunkGuard Mean Tokens Lost: {stats['near_done_run']['sunkguard_mean_lost_tokens']:,.0f} tokens")
    print(f"- **Cost to Heavy New Runs (6 burst runs demanding Flash):**")
    print(f"  * Baseline Finish Rate: {stats['heavy_new_runs']['baseline_finish_rate']*100:.1f}%")
    print(f"  * SunkGuard Finish Rate: {stats['heavy_new_runs']['sunkguard_finish_rate']*100:.1f}%")
    print(f"  * Baseline Mean Wait Time: {stats['heavy_new_runs']['baseline_mean_wait_ticks']:.2f} ticks")
    print(f"  * SunkGuard Mean Wait Time: {stats['heavy_new_runs']['sunkguard_mean_wait_ticks']:.2f} ticks")
