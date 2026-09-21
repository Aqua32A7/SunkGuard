#!/usr/bin/env python3
"""Automated script to evaluate seeds 21-50 across multiple load levels.

Computes:
- Wasted-token ratio (Baseline vs SunkGuard vs relative reduction)
- Overall failure rate (Baseline vs SunkGuard)
- Completed runs (Baseline vs SunkGuard)
- Late failures (Baseline vs SunkGuard)
- p95 completion latency (Baseline vs SunkGuard)
- Resource utilization (Baseline vs SunkGuard)
- Reservation waste (Baseline vs SunkGuard)
- New-work wait in absolute ticks (Baseline vs SunkGuard) and the wait ratio.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.metrics import collect_metrics, compare_runs
from core.seeds import THESIS_EVAL_SEEDS
from core.sim import SimulationConfig, SimulationEngine


def run_load_evaluation(
    loads: List[float],
    seeds: List[int],
    ticks: int = 150,
    policy: str = "medium",
) -> List[Dict[str, Any]]:
    results = []

    for load in loads:
        b_wasted_tok = []
        s_wasted_tok = []

        b_fail_rate = []
        s_fail_rate = []

        b_completed = []
        s_completed = []

        b_late_fail = []
        s_late_fail = []

        b_p95 = []
        s_p95 = []

        b_util = []
        s_util = []

        b_rsv_waste = []
        s_rsv_waste = []

        b_wait_ticks = []
        s_wait_ticks = []
        wait_ratios = []

        for s in seeds:
            # Baseline run
            cfg_b = SimulationConfig(seed=s, total_ticks=ticks, load_factor=load, is_sunkguard=False)
            e_b = SimulationEngine(cfg_b)
            e_b.run()
            m_b = collect_metrics(e_b)

            # SunkGuard run
            cfg_s = SimulationConfig(seed=s, total_ticks=ticks, load_factor=load, is_sunkguard=True, policy=policy)  # type: ignore
            e_s = SimulationEngine(cfg_s)
            e_s.run()
            m_s = collect_metrics(e_s)

            b_wasted_tok.append(m_b.wasted_token_ratio)
            s_wasted_tok.append(m_s.wasted_token_ratio)

            b_fail_rate.append(m_b.failure_rate)
            s_fail_rate.append(m_s.failure_rate)

            b_completed.append(m_b.done_count)
            s_completed.append(m_s.done_count)

            b_late_fail.append(m_b.late_failed_count)
            s_late_fail.append(m_s.late_failed_count)

            b_p95.append(m_b.p95_duration)
            s_p95.append(m_s.p95_duration)

            b_util.append(m_b.resource_utilization)
            s_util.append(m_s.resource_utilization)

            b_rsv_waste.append(m_b.reservation_waste)
            s_rsv_waste.append(m_s.reservation_waste)

            b_wait_ticks.append(m_b.mean_new_work_wait)
            s_wait_ticks.append(m_s.mean_new_work_wait)

            w_ratio = (m_s.mean_new_work_wait / m_b.mean_new_work_wait) if m_b.mean_new_work_wait > 0 else 1.0
            wait_ratios.append(w_ratio)

        n = len(seeds)
        avg_b_wasted = sum(b_wasted_tok) / n
        avg_s_wasted = sum(s_wasted_tok) / n
        tok_rel_red = (avg_b_wasted - avg_s_wasted) / avg_b_wasted if avg_b_wasted > 0 else 0.0

        avg_b_wait = sum(b_wait_ticks) / n
        avg_s_wait = sum(s_wait_ticks) / n
        avg_wait_ratio = sum(wait_ratios) / n

        row = {
            "load": load,
            "seeds_count": n,
            "wasted_token_ratio": {
                "baseline": avg_b_wasted,
                "sunkguard": avg_s_wasted,
                "relative_reduction": tok_rel_red,
            },
            "overall_failure_rate": {
                "baseline": sum(b_fail_rate) / n,
                "sunkguard": sum(s_fail_rate) / n,
            },
            "completed_runs": {
                "baseline": sum(b_completed) / n,
                "sunkguard": sum(s_completed) / n,
            },
            "late_failures": {
                "baseline": sum(b_late_fail) / n,
                "sunkguard": sum(s_late_fail) / n,
            },
            "p95_duration": {
                "baseline": sum(b_p95) / n,
                "sunkguard": sum(s_p95) / n,
            },
            "utilization": {
                "baseline": sum(b_util) / n,
                "sunkguard": sum(s_util) / n,
            },
            "reservation_waste": {
                "baseline": sum(b_rsv_waste) / n,
                "sunkguard": sum(s_rsv_waste) / n,
            },
            "new_work_wait_ticks": {
                "baseline": avg_b_wait,
                "sunkguard": avg_s_wait,
                "ratio": avg_wait_ratio,
            },
        }
        results.append(row)

    return results


def main():
    parser = argparse.ArgumentParser(description="Multi-load evaluation on seeds 21-50")
    parser.add_argument("--ticks", type=int, default=150, help="Ticks per run")
    parser.add_argument("--policy", type=str, default="medium", help="SunkGuard policy")
    parser.add_argument("--json-out", type=str, default=None, help="JSON output file")
    args = parser.parse_args()

    loads = [0.25, 0.40, 0.50, 0.55, 0.70, 0.85]
    seeds = THESIS_EVAL_SEEDS

    print(f"Running multi-load evaluation on {len(seeds)} seeds ({seeds[0]}..{seeds[-1]})...")
    data = run_load_evaluation(loads, seeds, ticks=args.ticks, policy=args.policy)

    # Print formatted markdown table
    print("\n### Seeds 21-50 Multi-Load Comprehensive Evaluation Table\n")
    headers = [
        "Load",
        "Wasted Tok (Base)",
        "Wasted Tok (SG)",
        "Tok Red%",
        "FailRate (Base)",
        "FailRate (SG)",
        "Done (Base)",
        "Done (SG)",
        "LateFail (Base)",
        "LateFail (SG)",
        "p95 (Base)",
        "p95 (SG)",
        "Util (Base)",
        "Util (SG)",
        "RsvWaste (SG)",
        "Wait Base (t)",
        "Wait SG (t)",
        "Wait Ratio",
    ]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")

    for d in data:
        row = [
            f"{d['load']:.2f}",
            f"{d['wasted_token_ratio']['baseline']*100:.2f}%",
            f"{d['wasted_token_ratio']['sunkguard']*100:.2f}%",
            f"{d['wasted_token_ratio']['relative_reduction']*100:+.1f}%",
            f"{d['overall_failure_rate']['baseline']*100:.1f}%",
            f"{d['overall_failure_rate']['sunkguard']*100:.1f}%",
            f"{d['completed_runs']['baseline']:.1f}",
            f"{d['completed_runs']['sunkguard']:.1f}",
            f"{d['late_failures']['baseline']:.2f}",
            f"{d['late_failures']['sunkguard']:.2f}",
            f"{d['p95_duration']['baseline']:.1f}t",
            f"{d['p95_duration']['sunkguard']:.1f}t",
            f"{d['utilization']['baseline']*100:.1f}%",
            f"{d['utilization']['sunkguard']*100:.1f}%",
            f"{d['reservation_waste']['sunkguard']*100:.2f}%",
            f"{d['new_work_wait_ticks']['baseline']:.2f}t",
            f"{d['new_work_wait_ticks']['sunkguard']:.2f}t",
            f"{d['new_work_wait_ticks']['ratio']:.2f}x",
        ]
        print("| " + " | ".join(row) + " |")

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nWrote full metrics to {args.json_out}")


if __name__ == "__main__":
    main()
