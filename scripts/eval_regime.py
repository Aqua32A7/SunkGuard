#!/usr/bin/env python3
"""Step 2 Regime Test Evaluation Suite.

Evaluates all 8 controller variants under the pre-registered regime test
(SPEC.md Section 11):
- Per-window TPM token bucket (W_size = 20t, B_window = 8,000 tokens)
- Non-preemptible long steps (d = 8t, 2,500 tokens)
- Evaluated on strictly unseen held-out seeds 301–400 across loads [0.50, 0.70, 0.85]
- Evaluates formal acceptance criteria in SPEC 11.3
"""

import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Dict, List, Tuple

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.regime import RegimeSimulationEngine


EVAL_SEEDS = range(301, 401)  # Default: seeds 301-400 (n=100)
EVAL_LOADS = [0.50, 0.70, 0.85]

VARIANTS = [
    ("Baseline", "baseline"),
    ("Baseline-Backoff", "baseline_backoff"),
    ("Oldest-First", "oldest_first"),
    ("FIFO-Request", "fifo_request"),
    ("Admission-Only", "admission_only"),
    ("Admission-PV", "admission_pv"),
    ("Admission-Headroom", "admission_headroom"),
    ("Full SunkGuard", "full_sunkguard"),
]

NON_RSV_VARIANTS = [
    "Oldest-First",
    "FIFO-Request",
    "Admission-Only",
    "Admission-PV",
    "Admission-Headroom",
]


def mean_and_ci(data: List[float]) -> Tuple[float, List[float]]:
    if not data:
        return 0.0, [0.0, 0.0]
    n = len(data)
    m = statistics.mean(data)
    if n < 2:
        return m, [m, m]
    s = statistics.stdev(data)
    t_val = 1.984  # for df = 99 at 95% confidence
    hw = t_val * (s / math.sqrt(n))
    return round(m, 5), [round(m - hw, 5), round(m + hw, 5)]


def paired_diff_ci(a: List[float], b: List[float]) -> Tuple[float, List[float]]:
    diffs = [x - y for x, y in zip(a, b)]
    return mean_and_ci(diffs)


def run_regime_evaluation(seeds: Any = None) -> Dict[str, Any]:
    eval_seeds = list(seeds) if seeds is not None else list(EVAL_SEEDS)
    seed_desc = f"{eval_seeds[0]}-{eval_seeds[-1]}" if eval_seeds else "none"

    print("=" * 90)
    print("SUNKGUARD STEP 2: REGIME TEST EVALUATION (SPEC SECTION 11)")
    print(f"Seeds: {seed_desc} (n={len(eval_seeds)} seeds) | Loads: {EVAL_LOADS}")
    print(f"Variants: {[v[0] for v in VARIANTS]}")
    print("=" * 90)

    results: Dict[str, Any] = {
        "evaluation_name": "Step 2 Regime Test (SPEC Section 11)",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seeds": seed_desc,
        "seed_count": len(eval_seeds),
        "loads": EVAL_LOADS,
        "load_results": {},
        "verdicts_per_load": {},
    }

    t0_all = time.time()

    for load in EVAL_LOADS:
        load_str = str(load)
        print(f"\n>>> Running Regime Test at Load {load:.2f} <<<")
        results["load_results"][load_str] = {}

        raw_metrics: Dict[str, Dict[str, List[float]]] = {}
        for label, code in VARIANTS:
            raw_metrics[label] = {
                "wasted": [],
                "fail": [],
                "late_fail": [],
                "done": [],
                "goodput": [],
                "wait": [],
            }

        for s in eval_seeds:
            for label, code in VARIANTS:
                eng = RegimeSimulationEngine(seed=s, load_factor=load, variant=code)
                res = eng.run(pat=16, qpat=40)

                raw_metrics[label]["wasted"].append(res["wasted_token_ratio"])
                raw_metrics[label]["fail"].append(res["overall_failure_rate"])
                raw_metrics[label]["late_fail"].append(res["late_failure_rate"])
                raw_metrics[label]["done"].append(float(res["completed_runs"]))
                raw_metrics[label]["goodput"].append(float(res["goodput_completed_tokens"]))
                raw_metrics[label]["wait"].append(float(res["mean_new_work_wait_ticks"]))

        # Aggregate metrics
        base_wait_mean = statistics.mean(raw_metrics["Baseline"]["wait"])
        base_wasted_list = raw_metrics["Baseline"]["wasted"]

        for label, code in VARIANTS:
            w_mean, w_ci = mean_and_ci(raw_metrics[label]["wasted"])
            f_mean, f_ci = mean_and_ci(raw_metrics[label]["fail"])
            lf_mean, lf_ci = mean_and_ci(raw_metrics[label]["late_fail"])
            d_mean, d_ci = mean_and_ci(raw_metrics[label]["done"])
            g_mean, g_ci = mean_and_ci(raw_metrics[label]["goodput"])
            wt_mean, wt_ci = mean_and_ci(raw_metrics[label]["wait"])

            wait_ratio = round(wt_mean / max(1e-4, base_wait_mean), 2)
            w_diff_mean, w_diff_ci = paired_diff_ci(raw_metrics[label]["wasted"], base_wasted_list)

            results["load_results"][load_str][label] = {
                "wasted_token_ratio": {"mean": w_mean, "ci_95": w_ci, "paired_diff_vs_base": [w_diff_mean, *w_diff_ci]},
                "overall_failure_rate": {"mean": f_mean, "ci_95": f_ci},
                "late_failure_rate": {"mean": lf_mean, "ci_95": lf_ci},
                "completed_runs": {"mean": d_mean, "ci_95": d_ci},
                "goodput_completed_tokens": {"mean": g_mean, "ci_95": g_ci},
                "new_work_wait": {"mean_ticks": wt_mean, "ci_95": wt_ci, "wait_ratio_vs_base": wait_ratio},
            }

            print(
                f"  {label:20s} | Wasted: {w_mean*100:5.2f}% | Fail: {f_mean*100:5.2f}% | "
                f"Done: {d_mean:4.1f} | Goodput: {g_mean:6.0f} tok | Wait: {wt_mean:4.2f}t ({wait_ratio:4.2f}x)"
            )

        # Evaluate acceptance criterion vs best non-reservation variant
        best_no_rsv_name = min(
            NON_RSV_VARIANTS,
            key=lambda name: results["load_results"][load_str][name]["wasted_token_ratio"]["mean"]
        )
        best_no_rsv_wasted = results["load_results"][load_str][best_no_rsv_name]["wasted_token_ratio"]["mean"]
        full_wasted = results["load_results"][load_str]["Full SunkGuard"]["wasted_token_ratio"]["mean"]

        rel_waste_red = (best_no_rsv_wasted - full_wasted) / max(1e-6, best_no_rsv_wasted)

        # Paired test Full vs Best No-Rsv
        full_wasted_list = raw_metrics["Full SunkGuard"]["wasted"]
        best_wasted_list = raw_metrics[best_no_rsv_name]["wasted"]
        # Diff = Best - Full (positive means Full reduced waste)
        paired_red_mean, paired_red_ci = paired_diff_ci(best_wasted_list, full_wasted_list)

        # Non-inferiority tests: Completed runs (Full - Best)
        full_done_list = raw_metrics["Full SunkGuard"]["done"]
        best_done_list = raw_metrics[best_no_rsv_name]["done"]
        paired_done_mean, paired_done_ci = paired_diff_ci(full_done_list, best_done_list)

        # Overall failure rate (Full - Best)
        full_fail_list = raw_metrics["Full SunkGuard"]["fail"]
        best_fail_list = raw_metrics[best_no_rsv_name]["fail"]
        paired_fail_mean, paired_fail_ci = paired_diff_ci(full_fail_list, best_fail_list)

        wait_ratio_full = results["load_results"][load_str]["Full SunkGuard"]["new_work_wait"]["wait_ratio_vs_base"]

        # Check SPEC 11.3 criteria:
        # 1. Relative waste reduction >= 20.0%
        # 2. Paired 95% CI of reduction strictly > 0
        # 3. Non-inferiority: completions CI lower >= -1.0, failure CI upper <= +0.015
        # 4. Wait ratio < 2.00x
        pass_rel_waste = rel_waste_red >= 0.20
        pass_stat_sig = paired_red_ci[0] > 0.0
        pass_non_inf_done = paired_done_ci[0] >= -1.0
        pass_non_inf_fail = paired_fail_ci[1] <= 0.015
        pass_wait_ceiling = wait_ratio_full < 2.00

        load_pass = (
            pass_rel_waste
            and pass_stat_sig
            and pass_non_inf_done
            and pass_non_inf_fail
            and pass_wait_ceiling
        )

        verdict_doc = {
            "load": load,
            "best_non_reservation_variant": best_no_rsv_name,
            "best_non_rsv_wasted_ratio": best_no_rsv_wasted,
            "full_sunkguard_wasted_ratio": full_wasted,
            "relative_waste_reduction": round(rel_waste_red, 4),
            "paired_waste_reduction_ci_95": paired_red_ci,
            "paired_done_diff_ci_95": paired_done_ci,
            "paired_fail_diff_ci_95": paired_fail_ci,
            "wait_ratio_vs_baseline": wait_ratio_full,
            "criterion_relative_waste_gte_20pct": pass_rel_waste,
            "criterion_stat_sig_ci_excludes_zero": pass_stat_sig,
            "criterion_non_inferiority_completed": pass_non_inf_done,
            "criterion_non_inferiority_failure": pass_non_inf_fail,
            "criterion_wait_ceiling_lt_2x": pass_wait_ceiling,
            "load_verdict": "PASS" if load_pass else "FAIL",
        }
        results["verdicts_per_load"][load_str] = verdict_doc

        print(f"\n  [VERDICT Load {load:.2f}] Best No-Rsv: {best_no_rsv_name} ({best_no_rsv_wasted*100:.2f}%) vs Full ({full_wasted*100:.2f}%)")
        print(f"    Relative Waste Reduction: {rel_waste_red*100:.2f}% (Req >= 20.0%: {'PASS' if pass_rel_waste else 'FAIL'})")
        print(f"    Paired 95% CI of Reduction: [{paired_red_ci[0]*100:.2f}%, {paired_red_ci[1]*100:.2f}%] (Excludes 0: {'PASS' if pass_stat_sig else 'FAIL'})")
        print(f"    Completions Diff CI: [{paired_done_ci[0]:.2f}, {paired_done_ci[1]:.2f}] (Req >= -1.0: {'PASS' if pass_non_inf_done else 'FAIL'})")
        print(f"    Failure Diff CI: [{paired_fail_ci[0]*100:.2f}%, {paired_fail_ci[1]*100:.2f}%] (Req <= +1.5%: {'PASS' if pass_non_inf_fail else 'FAIL'})")
        print(f"    Wait Ratio vs Base: {wait_ratio_full:.2f}x (Req < 2.0x: {'PASS' if pass_wait_ceiling else 'FAIL'})")
        print(f"    Load Verdict: {verdict_doc['load_verdict']}")

    # Overall Acceptance (must pass >= 2 of 3 loads)
    passed_loads_count = sum(
        1 for v in results["verdicts_per_load"].values() if v["load_verdict"] == "PASS"
    )
    overall_pass = passed_loads_count >= 2
    results["overall_verdict"] = "PASS" if overall_pass else "FAIL"
    results["passed_loads_count"] = passed_loads_count
    results["total_evaluated_loads"] = len(EVAL_LOADS)

    print("\n" + "=" * 90)
    print(f"REGIME TEST OVERALL VERDICT: {results['overall_verdict']} ({passed_loads_count}/{len(EVAL_LOADS)} loads passed)")
    print(f"Total Evaluation Time: {time.time() - t0_all:.2f}s")
    print("=" * 90)

    if seeds is None or (eval_seeds[0] == 301 and eval_seeds[-1] == 400 and len(eval_seeds) == 100):
        out_file = Path("eval/results/regime_test_results.json")
    else:
        out_file = Path(f"eval/results/regime_test_results_seeds_{seed_desc}.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to: {out_file}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run regime test evaluation")
    parser.add_argument("--seeds", type=str, default=None, help="Seed range e.g. 302-400 or 301-400")
    args = parser.parse_args()

    custom_seeds = None
    if args.seeds:
        if "-" in args.seeds:
            p = args.seeds.split("-")
            custom_seeds = range(int(p[0]), int(p[1]) + 1)
        else:
            custom_seeds = [int(s) for s in args.seeds.split(",")]

    run_regime_evaluation(seeds=custom_seeds)
