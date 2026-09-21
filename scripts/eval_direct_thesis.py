#!/usr/bin/env python3
"""Direct Thesis Test: FIFO vs Progress-Only vs Admission-Only on Fresh Seeds 151-250.

Headline Comparator: FIFO (disciplined queueing without progress weighting or reservations).
Stampede Comparator: Baseline (uncoordinated random dispatch).
Ablation Variants: Progress-Only, Admission-Only.
Loads: 0.25, 0.50, 0.70, 0.85.
Reports: Wasted-token ratio, failure rate, completed runs, late failures, added wait,
with paired 95% Confidence Intervals against FIFO.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.controller import POLICIES
from core.metrics import collect_metrics, percentile
from core.predictor import train_predictor_on_dev_seeds
from core.seeds import DEV_SEEDS, PHASE3_FRESH_SEEDS
from core.sim import SimulationConfig, SimulationEngine


def compute_ci(data: List[float], confidence: float = 0.95) -> Tuple[float, float, float]:
    n = len(data)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean = sum(data) / n
    if n == 1:
        return mean, mean, mean
    variance = sum((x - mean) ** 2 for x in data) / (n - 1)
    std_dev = math.sqrt(max(0.0, variance))
    std_err = std_dev / math.sqrt(n)
    t_val = 1.984 if n >= 100 else 2.045
    return mean, mean - t_val * std_err, mean + t_val * std_err


def compute_paired_ci(a: List[float], b: List[float]) -> Tuple[float, float, float, bool]:
    """Computes paired difference (a - b), its 95% CI, and whether it excludes 0."""
    diffs = [x - y for x, y in zip(a, b)]
    mean, lower, upper = compute_ci(diffs)
    excludes_zero = (lower > 0.0 and upper > 0.0) or (lower < 0.0 and upper < 0.0)
    return mean, lower, upper, excludes_zero


def run_direct_thesis_eval(
    seeds: List[int] = PHASE3_FRESH_SEEDS,
    loads: List[float] = [0.25, 0.50, 0.70, 0.85],
    ticks: int = 150,
) -> Dict[str, Any]:
    print(f"\n================================================================================")
    print(f" DIRECT THESIS TEST: FIFO vs PROGRESS-ONLY vs ADMISSION-ONLY (SEEDS {seeds[0]}..{seeds[-1]}) ")
    print(f"================================================================================")

    predictor = train_predictor_on_dev_seeds(dev_seeds=DEV_SEEDS, ticks=ticks)

    variants: List[Tuple[str, str, bool, bool]] = [
        ("Baseline (Stampede)", "uncoordinated", False, False),
        ("FIFO (Headline Comparator)", "fifo", True, False),
        ("Progress-Only", "progress_only", True, False),
        ("Admission-Only", "admission_only", True, False),
    ]

    results: Dict[str, Any] = {
        "title": "Direct Thesis Test: FIFO vs Progress-Only vs Admission-Only",
        "seeds": f"{seeds[0]}..{seeds[-1]}",
        "seed_count": len(seeds),
        "loads": loads,
        "headline_comparator": "FIFO (Headline Comparator)",
        "stampede_case": "Baseline (Stampede)",
        "load_data": {},
    }

    for load in loads:
        print(f"\n>>> Running evaluation at load: {load} ...")
        raw_metrics: Dict[str, Dict[str, List[float]]] = {
            v[0]: {
                "wasted_tok_ratio": [],
                "fail_rate": [],
                "late_fail_rate": [],
                "late_fail_count": [],
                "done_count": [],
                "wait_ticks": [],
                "utilization": [],
                "jain": [],
                "p95_dur": [],
            }
            for v in variants
        }
        raw_waits: Dict[str, List[int]] = {v[0]: [] for v in variants}

        for label, variant_key, is_sg, _ in variants:
            for s in seeds:
                cfg = SimulationConfig(
                    seed=s,
                    total_ticks=ticks,
                    load_factor=load,
                    is_sunkguard=is_sg,
                    variant=variant_key if is_sg else "full_sunkguard",  # type: ignore
                    predictor=predictor if is_sg else None,
                    policy="medium",
                )
                engine = SimulationEngine(cfg)
                engine.run()
                m = collect_metrics(engine)

                r = raw_metrics[label]
                r["wasted_tok_ratio"].append(m.wasted_token_ratio)
                r["fail_rate"].append(m.failure_rate)
                r["late_fail_rate"].append(m.late_failure_rate)
                r["late_fail_count"].append(float(m.late_failed_count))
                r["done_count"].append(float(m.done_count))
                r["wait_ticks"].append(m.mean_new_work_wait)
                r["utilization"].append(m.resource_utilization)
                r["jain"].append(m.jain_fairness)
                r["p95_dur"].append(m.p95_duration)
                raw_waits[label].extend(engine.initial_admission_waits)

        fifo_raw = raw_metrics["FIFO (Headline Comparator)"]
        fifo_wait_mean = sum(fifo_raw["wait_ticks"]) / len(seeds)

        load_summary: Dict[str, Any] = {}

        for label, _, _, has_pred in variants:
            raw = raw_metrics[label]
            w_m, w_l, w_u = compute_ci(raw["wasted_tok_ratio"])
            f_m, f_l, f_u = compute_ci(raw["fail_rate"])
            lf_m, lf_l, lf_u = compute_ci(raw["late_fail_rate"])
            lfc_m, _, _ = compute_ci(raw["late_fail_count"])
            d_m, d_l, d_u = compute_ci(raw["done_count"])
            wait_m, wait_l, wait_u = compute_ci(raw["wait_ticks"])
            u_m, u_l, u_u = compute_ci(raw["utilization"])
            j_m, j_l, j_u = compute_ci(raw["jain"])
            dur_m, _, _ = compute_ci(raw["p95_dur"])

            p95_w = percentile(raw_waits[label], 0.95)
            wait_ratio_vs_fifo = (wait_m / fifo_wait_mean) if fifo_wait_mean > 0 else 1.0

            # Paired CIs vs FIFO (Headline Comparator)
            # (variant - FIFO): for wasted, failure, late fail, wait, negative is better!
            # for completed runs: positive is better!
            p_w_diff, p_w_l, p_w_u, p_w_sig = compute_paired_ci(raw["wasted_tok_ratio"], fifo_raw["wasted_tok_ratio"])
            p_f_diff, p_f_l, p_f_u, p_f_sig = compute_paired_ci(raw["fail_rate"], fifo_raw["fail_rate"])
            p_lf_diff, p_lf_l, p_lf_u, p_lf_sig = compute_paired_ci(raw["late_fail_rate"], fifo_raw["late_fail_rate"])
            p_lfc_diff, p_lfc_l, p_lfc_u, _ = compute_paired_ci(raw["late_fail_count"], fifo_raw["late_fail_count"])
            p_d_diff, p_d_l, p_d_u, p_d_sig = compute_paired_ci(raw["done_count"], fifo_raw["done_count"])
            p_wait_diff, p_wait_l, p_wait_u, p_wait_sig = compute_paired_ci(raw["wait_ticks"], fifo_raw["wait_ticks"])

            load_summary[label] = {
                "wasted_token_ratio": {
                    "mean": round(w_m, 4),
                    "ci_95": [round(w_l, 4), round(w_u, 4)],
                    "paired_diff_vs_fifo": [round(p_w_diff, 4), round(p_w_l, 4), round(p_w_u, 4)],
                    "paired_sig": p_w_sig,
                },
                "failure_rate": {
                    "mean": round(f_m, 4),
                    "ci_95": [round(f_l, 4), round(f_u, 4)],
                    "paired_diff_vs_fifo": [round(p_f_diff, 4), round(p_f_l, 4), round(p_f_u, 4)],
                    "paired_sig": p_f_sig,
                },
                "late_failures": {
                    "mean_rate": round(lf_m, 4),
                    "mean_count": round(lfc_m, 2),
                    "ci_95": [round(lf_l, 4), round(lf_u, 4)],
                    "paired_count_diff_vs_fifo": [round(p_lfc_diff, 2), round(p_lfc_l, 2), round(p_lfc_u, 2)],
                    "paired_rate_diff_vs_fifo": [round(p_lf_diff, 4), round(p_lf_l, 4), round(p_lf_u, 4)],
                },
                "completed_runs": {
                    "mean": round(d_m, 2),
                    "ci_95": [round(d_l, 2), round(d_u, 2)],
                    "paired_diff_vs_fifo": [round(p_d_diff, 2), round(p_d_l, 2), round(p_d_u, 2)],
                    "paired_sig": p_d_sig,
                },
                "new_work_wait": {
                    "mean_ticks": round(wait_m, 3),
                    "p95_ticks": round(p95_w, 2),
                    "wait_ratio_vs_fifo": round(wait_ratio_vs_fifo, 2),
                    "paired_diff_ticks_vs_fifo": [round(p_wait_diff, 3), round(p_wait_l, 3), round(p_wait_u, 3)],
                },
                "utilization": round(u_m, 4),
                "jain_fairness": round(j_m, 4),
                "p95_duration": round(dur_m, 2),
                "predictor_hit_rate": "N/A",  # No predictor active in these variants
            }

        results["load_data"][str(load)] = load_summary

        print(f"\n--- LOAD {load} DIRECT THESIS COMPARISON (Headline: FIFO) ---")
        header = f"{'Variant':<28} | {'Wasted Tok %':<16} | {'Fail Rate %':<16} | {'Completed Runs':<16} | {'Late Fails (Count)':<20} | {'Wait (t) / vs FIFO':<18}"
        print("-" * len(header))
        print(header)
        print("-" * len(header))
        for lbl in [v[0] for v in variants]:
            d = load_summary[lbl]
            w_str = f"{d['wasted_token_ratio']['mean']*100:.2f}% (Δ{d['wasted_token_ratio']['paired_diff_vs_fifo'][0]*100:+.2f}%)"
            f_str = f"{d['failure_rate']['mean']*100:.1f}% (Δ{d['failure_rate']['paired_diff_vs_fifo'][0]*100:+.1f}%)"
            c_str = f"{d['completed_runs']['mean']:.1f} (Δ{d['completed_runs']['paired_diff_vs_fifo'][0]:+.1f})"
            lf_str = f"{d['late_failures']['mean_count']:.2f} (Δ{d['late_failures']['paired_count_diff_vs_fifo'][0]:+.2f})"
            wait_str = f"{d['new_work_wait']['mean_ticks']:.2f}t ({d['new_work_wait']['wait_ratio_vs_fifo']:.2f}x)"
            print(f"{lbl:<28} | {w_str:<16} | {f_str:<16} | {c_str:<16} | {lf_str:<20} | {wait_str:<18}")
        print("-" * len(header))

    out_file = Path(__file__).resolve().parent.parent / "eval" / "results" / "direct_thesis_test_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved direct thesis results to: {out_file}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loads", nargs="+", type=float, default=[0.25, 0.50, 0.70, 0.85])
    parser.add_argument("--ticks", type=int, default=150)
    args = parser.parse_args()

    run_direct_thesis_eval(loads=args.loads, ticks=args.ticks)
