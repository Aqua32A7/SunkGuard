#!/usr/bin/env python3
"""Phase 3 Comprehensive Ablation Evaluator on Fresh Seeds 151-250.

Evaluates 8 controller variants across loads [0.25, 0.50, 0.70]:
1. Baseline (uncoordinated FIFO/random)
2. FIFO (no aging, no progress, no reservations)
3. Aging-Only (beta=0, no reservations)
4. Progress-Only (no aging, no reservations)
5. Admission-Only (aging + progress, no reservations)
6. Pred-Rsv (Progress OFF) (reservations + aging, beta=0)
7. Pred-Rsv + Progress (No Aging) (reservations + progress, no aging)
8. Full SunkGuard (reservations + progress + aging)

Per load reports:
- Wasted-token ratio (mean, 95% CI, paired 95% CI vs baseline)
- Overall failure rate (mean, 95% CI, paired 95% CI vs baseline)
- Late failure rate (mean, 95% CI, mean count, paired 95% CI vs baseline)
- Completed runs (mean, 95% CI, paired 95% CI vs baseline)
- Added wait (mean ticks, paired 95% CI vs baseline) and p95 wait
- Resource utilization (mean, 95% CI, paired 95% CI vs baseline)
- Reservation waste (mean, 95% CI)
- Jain's fairness index (mean, 95% CI, paired 95% CI vs baseline)
- p95 completion duration (mean, 95% CI, paired 95% CI vs baseline)
- Predictor hit rate (mean, 95% CI)
- Paired 95% Confidence Intervals for all metrics vs baseline

Machine-Readable Verdict Criteria per Load:
1. Relative token waste reduction: Full SunkGuard must beat the best
   no-reservation variant by >= 20.0% relative.
2. Statistical significance: Paired 95% CI of absolute reduction strictly
   excludes zero and favors Full (CI lower bound > 0).
3. Wait ceiling: Full SunkGuard new work wait ratio vs baseline < 2.00x.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.controller import POLICIES
from core.metrics import collect_metrics, percentile
from core.predictor import train_predictor_on_dev_seeds
from core.seeds import DEV_SEEDS, PHASE3_FRESH_SEEDS
from core.sim import SimulationConfig, SimulationEngine


def check_git_integrity(expected_tag: str = "thesis-gate3-frozen") -> str:
    """Verifies that the working tree is clean and HEAD matches the expected tag."""
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    dirty = status_proc.stdout.strip()
    if dirty:
        raise RuntimeError(
            f"REFUSING TO RUN: Git working tree is dirty!\nUncommitted changes:\n{dirty}\n"
            f"Commit all changes and tag with '{expected_tag}' before running Gate 3."
        )

    commit_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    head_commit = commit_proc.stdout.strip()

    tag_proc = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        capture_output=True,
        text=True,
    )
    if tag_proc.returncode != 0 or tag_proc.stdout.strip() != expected_tag:
        current_tags = tag_proc.stdout.strip() if tag_proc.returncode == 0 else "None"
        raise RuntimeError(
            f"REFUSING TO RUN: HEAD ({head_commit[:8]}) does not match tag '{expected_tag}'! "
            f"Current tag: '{current_tags}'."
        )

    return head_commit


def compute_config_hash() -> str:
    """Computes SHA-256 hash of frozen policy parameters."""
    cfg_dump = json.dumps(
        {k: vars(v) for k, v in sorted(POLICIES.items())},
        sort_keys=True,
    )
    return hashlib.sha256(cfg_dump.encode("utf-8")).hexdigest()


def compute_ci(data: List[float], confidence: float = 0.95) -> Tuple[float, float, float]:
    """Computes mean and [lower, upper] confidence interval using t-distribution."""
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
    """Computes paired differences (a - b), mean difference, 95% CI, and whether CI excludes zero."""
    diffs = [x - y for x, y in zip(a, b)]
    mean, lower, upper = compute_ci(diffs)
    excludes_zero = (lower > 0.0 and upper > 0.0) or (lower < 0.0 and upper < 0.0)
    return mean, lower, upper, excludes_zero


def run_gate3_evaluation(
    seeds: List[int],
    loads: List[float],
    ticks: int = 150,
) -> Dict[str, Any]:
    commit_hash = check_git_integrity("thesis-gate3-frozen")
    cfg_hash = compute_config_hash()

    print(f"\n================================================================================")
    print(f"       PHASE 3 ABLATION EVALUATION (SEEDS {seeds[0]}..{seeds[-1]}, {len(seeds)} SEEDS)       ")
    print(f"================================================================================")
    print(f"Git Commit:   {commit_hash}")
    print(f"Git Tag:      thesis-gate3-frozen")
    print(f"Config Hash:  {cfg_hash[:16]}...")
    print(f"Timestamp:    {datetime.now(timezone.utc).isoformat()}")

    # Train predictor on dev seeds 1..20
    predictor = train_predictor_on_dev_seeds(dev_seeds=DEV_SEEDS, ticks=ticks)

    variants: List[Tuple[str, str, bool, str]] = [
        ("Baseline", "uncoordinated", False, "no_rsv"),
        ("FIFO", "fifo", True, "no_rsv"),
        ("Aging-Only", "aging_only", True, "no_rsv"),
        ("Progress-Only", "progress_only", True, "no_rsv"),
        ("Admission-Only", "admission_only", True, "no_rsv"),
        ("Pred-Rsv (Progress OFF)", "pred_rsv_no_prog", True, "rsv"),
        ("Pred-Rsv + Progress (No Aging)", "pred_rsv_progress_no_aging", True, "rsv"),
        ("Full SunkGuard", "full_sunkguard", True, "full"),
    ]

    all_results: Dict[str, Any] = {
        "evaluation_name": "Phase 3 Comprehensive Ablation",
        "commit_hash": commit_hash,
        "git_tag": "thesis-gate3-frozen",
        "config_hash": cfg_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seeds": f"{seeds[0]}..{seeds[-1]}",
        "seed_count": len(seeds),
        "seed_list": seeds,
        "loads": loads,
        "ticks_per_simulation": ticks,
        "load_results": {},
        "verdicts_per_load": {},
        "overall_verdict": True,
    }

    for load in loads:
        print(f"\n>>> Running sweep at load level: {load} ...")
        load_data: Dict[str, Any] = {}
        raw_seed_metrics: Dict[str, Dict[str, List[float]]] = {
            v[0]: {
                "wasted_tok_ratio": [],
                "fail_rate": [],
                "late_fail_rate": [],
                "late_fail_count": [],
                "done_count": [],
                "wait_ticks": [],
                "utilization": [],
                "rsv_waste": [],
                "jain": [],
                "p95_dur": [],
                "pred_hit": [],
            }
            for v in variants
        }
        raw_waits_per_variant: Dict[str, List[int]] = {v[0]: [] for v in variants}

        for label, variant_key, is_sg, _ in variants:
            for s in seeds:
                if not is_sg:
                    cfg = SimulationConfig(
                        seed=s,
                        total_ticks=ticks,
                        load_factor=load,
                        is_sunkguard=False,
                    )
                else:
                    cfg = SimulationConfig(
                        seed=s,
                        total_ticks=ticks,
                        load_factor=load,
                        is_sunkguard=True,
                        variant=variant_key,  # type: ignore
                        predictor=predictor,
                        policy="medium",
                    )
                engine = SimulationEngine(cfg)
                engine.run()
                m = collect_metrics(engine)

                raw = raw_seed_metrics[label]
                raw["wasted_tok_ratio"].append(m.wasted_token_ratio)
                raw["fail_rate"].append(m.failure_rate)
                raw["late_fail_rate"].append(m.late_failure_rate)
                raw["late_fail_count"].append(float(m.late_failed_count))
                raw["done_count"].append(float(m.done_count))
                raw["wait_ticks"].append(m.mean_new_work_wait)
                raw["utilization"].append(m.resource_utilization)
                raw["rsv_waste"].append(m.reservation_waste)
                raw["jain"].append(m.jain_fairness)
                raw["p95_dur"].append(m.p95_duration)
                raw["pred_hit"].append(m.predictor_hit_rate)
                raw_waits_per_variant[label].extend(engine.initial_admission_waits)

        base_raw = raw_seed_metrics["Baseline"]
        base_wait_mean = sum(base_raw["wait_ticks"]) / len(seeds)

        # Compute per-variant aggregated metrics, marginal CIs, and paired CIs vs Baseline
        for label, _, _, group in variants:
            raw = raw_seed_metrics[label]
            wasted_m, wasted_l, wasted_u = compute_ci(raw["wasted_tok_ratio"])
            fail_m, fail_l, fail_u = compute_ci(raw["fail_rate"])
            late_m, late_l, late_u = compute_ci(raw["late_fail_rate"])
            late_cnt_m, _, _ = compute_ci(raw["late_fail_count"])
            done_m, done_l, done_u = compute_ci(raw["done_count"])
            wait_m, wait_l, wait_u = compute_ci(raw["wait_ticks"])
            util_m, util_l, util_u = compute_ci(raw["utilization"])
            rsv_w_m, rsv_w_l, rsv_w_u = compute_ci(raw["rsv_waste"])
            jain_m, jain_l, jain_u = compute_ci(raw["jain"])
            p95_dur_m, p95_dur_l, p95_dur_u = compute_ci(raw["p95_dur"])
            pred_hit_m, pred_hit_l, pred_hit_u = compute_ci(raw["pred_hit"])

            p95_wait = percentile(raw_waits_per_variant[label], 0.95)
            wait_ratio = (wait_m / base_wait_mean) if base_wait_mean > 0 else 1.0

            # Paired CIs vs Baseline across seeds
            paired_wasted_diff, p_wasted_l, p_wasted_u, _ = compute_paired_ci(raw["wasted_tok_ratio"], base_raw["wasted_tok_ratio"])
            paired_fail_diff, p_fail_l, p_fail_u, _ = compute_paired_ci(raw["fail_rate"], base_raw["fail_rate"])
            paired_late_diff, p_late_l, p_late_u, _ = compute_paired_ci(raw["late_fail_rate"], base_raw["late_fail_rate"])
            paired_done_diff, p_done_l, p_done_u, _ = compute_paired_ci(raw["done_count"], base_raw["done_count"])
            paired_wait_diff, p_wait_l, p_wait_u, _ = compute_paired_ci(raw["wait_ticks"], base_raw["wait_ticks"])
            paired_util_diff, p_util_l, p_util_u, _ = compute_paired_ci(raw["utilization"], base_raw["utilization"])
            paired_jain_diff, p_jain_l, p_jain_u, _ = compute_paired_ci(raw["jain"], base_raw["jain"])
            paired_dur_diff, p_dur_l, p_dur_u, _ = compute_paired_ci(raw["p95_dur"], base_raw["p95_dur"])

            load_data[label] = {
                "group": group,
                "wasted_token_ratio": {
                    "mean": round(wasted_m, 4),
                    "ci_95": [round(wasted_l, 4), round(wasted_u, 4)],
                    "paired_diff_vs_baseline": [round(paired_wasted_diff, 4), round(p_wasted_l, 4), round(p_wasted_u, 4)],
                },
                "overall_failure_rate": {
                    "mean": round(fail_m, 4),
                    "ci_95": [round(fail_l, 4), round(fail_u, 4)],
                    "paired_diff_vs_baseline": [round(paired_fail_diff, 4), round(p_fail_l, 4), round(p_fail_u, 4)],
                },
                "late_failure_rate": {
                    "mean": round(late_m, 4),
                    "ci_95": [round(late_l, 4), round(late_u, 4)],
                    "mean_count": round(late_cnt_m, 2),
                    "paired_diff_vs_baseline": [round(paired_late_diff, 4), round(p_late_l, 4), round(p_late_u, 4)],
                },
                "completed_runs": {
                    "mean": round(done_m, 2),
                    "ci_95": [round(done_l, 2), round(done_u, 2)],
                    "paired_diff_vs_baseline": [round(paired_done_diff, 2), round(p_done_l, 2), round(p_done_u, 2)],
                },
                "new_work_wait": {
                    "mean_ticks": round(wait_m, 3),
                    "p95_ticks": round(p95_wait, 2),
                    "added_wait_ticks": round(paired_wait_diff, 3),
                    "added_wait_ci_95": [round(p_wait_l, 3), round(p_wait_u, 3)],
                    "wait_ratio_vs_base": round(wait_ratio, 2),
                },
                "resource_utilization": {
                    "mean": round(util_m, 4),
                    "ci_95": [round(util_l, 4), round(util_u, 4)],
                    "paired_diff_vs_baseline": [round(paired_util_diff, 4), round(p_util_l, 4), round(p_util_u, 4)],
                },
                "reservation_waste": {
                    "mean": round(rsv_w_m, 4),
                    "ci_95": [round(rsv_w_l, 4), round(rsv_w_u, 4)],
                },
                "jain_fairness": {
                    "mean": round(jain_m, 4),
                    "ci_95": [round(jain_l, 4), round(jain_u, 4)],
                    "paired_diff_vs_baseline": [round(paired_jain_diff, 4), round(p_jain_l, 4), round(p_jain_u, 4)],
                },
                "p95_completion_duration": {
                    "mean": round(p95_dur_m, 2),
                    "ci_95": [round(p95_dur_l, 2), round(p95_dur_u, 2)],
                    "paired_diff_vs_baseline": [round(paired_dur_diff, 2), round(p_dur_l, 2), round(p_dur_u, 2)],
                },
                "predictor_hit_rate": {
                    "mean": round(pred_hit_m, 4),
                    "ci_95": [round(pred_hit_l, 4), round(pred_hit_u, 4)],
                },
            }

        # Identify best no-reservation variant on wasted-token ratio
        no_rsv_variants = ["FIFO", "Aging-Only", "Progress-Only", "Admission-Only"]
        best_no_rsv_label = min(no_rsv_variants, key=lambda lbl: load_data[lbl]["wasted_token_ratio"]["mean"])
        best_no_rsv_wasted = load_data[best_no_rsv_label]["wasted_token_ratio"]["mean"]
        full_wasted = load_data["Full SunkGuard"]["wasted_token_ratio"]["mean"]

        # Paired difference: best_no_rsv_wasted - full_wasted (positive means Full had lower waste)
        paired_diff_mean, diff_l, diff_u, ci_excludes_zero = compute_paired_ci(
            raw_seed_metrics[best_no_rsv_label]["wasted_tok_ratio"],
            raw_seed_metrics["Full SunkGuard"]["wasted_tok_ratio"],
        )
        rel_reduction = (paired_diff_mean / best_no_rsv_wasted) if best_no_rsv_wasted > 0 else 0.0

        # Criteria check:
        # 1. Full beats best no-reservation variant by >= 20% relative on wasted tokens
        criterion_20pct_rel = rel_reduction >= 0.20
        # 2. 95% CI on absolute reduction excludes zero and favors Full (diff_l > 0)
        criterion_ci_excludes_zero = (diff_l > 0.0)
        # 3. Within wait ceilings (< 2.0x vs baseline)
        full_wait_ratio = load_data["Full SunkGuard"]["new_work_wait"]["wait_ratio_vs_base"]
        criterion_wait_ceiling = full_wait_ratio < 2.00

        load_verdict = criterion_20pct_rel and criterion_ci_excludes_zero and criterion_wait_ceiling

        verdict_data = {
            "best_no_reservation_variant": best_no_rsv_label,
            "best_no_rsv_wasted_ratio": round(best_no_rsv_wasted, 4),
            "full_sunkguard_wasted_ratio": round(full_wasted, 4),
            "absolute_reduction_mean": round(paired_diff_mean, 4),
            "absolute_reduction_paired_ci_95": [round(diff_l, 4), round(diff_u, 4)],
            "relative_reduction": round(rel_reduction, 4),
            "full_wait_ratio_vs_baseline": round(full_wait_ratio, 2),
            "criteria": {
                "rel_reduction_gte_20pct": {
                    "value_pct": round(rel_reduction * 100, 2),
                    "threshold_pct": 20.0,
                    "passed": criterion_20pct_rel,
                },
                "ci_excludes_zero_favoring_full": {
                    "ci_lower": round(diff_l, 4),
                    "ci_upper": round(diff_u, 4),
                    "passed": criterion_ci_excludes_zero,
                },
                "within_wait_ceiling_lt_2x": {
                    "wait_ratio": round(full_wait_ratio, 2),
                    "ceiling": 2.00,
                    "passed": criterion_wait_ceiling,
                },
            },
            "verdict": "PASS" if load_verdict else "FAIL",
        }

        all_results["load_results"][str(load)] = load_data
        all_results["verdicts_per_load"][str(load)] = verdict_data
        if not load_verdict:
            all_results["overall_verdict"] = False

        # Print Table for this load
        print(f"\n--- RESULTS TABLE AT LOAD {load} ---")
        header = f"{'Variant':<32} | {'Wasted Tok %':<18} | {'Fail %':<10} | {'Late Fails':<10} | {'Done':<8} | {'Wait (t)':<12} | {'p95 W':<8} | {'Util %':<8} | {'Jain':<6}"
        print("-" * len(header))
        print(header)
        print("-" * len(header))
        for label in [v[0] for v in variants]:
            d = load_data[label]
            w_str = f"{d['wasted_token_ratio']['mean']*100:.1f}% [{d['wasted_token_ratio']['ci_95'][0]*100:.1f}..{d['wasted_token_ratio']['ci_95'][1]*100:.1f}]"
            f_str = f"{d['overall_failure_rate']['mean']*100:.1f}%"
            lf_str = f"{d['late_failure_rate']['mean_count']:.2f}"
            done_str = f"{d['completed_runs']['mean']:.1f}"
            wait_str = f"{d['new_work_wait']['mean_ticks']:.2f}t ({d['new_work_wait']['wait_ratio_vs_base']:.1f}x)"
            p95w_str = f"{d['new_work_wait']['p95_ticks']:.1f}t"
            u_str = f"{d['resource_utilization']['mean']*100:.1f}%"
            j_str = f"{d['jain_fairness']['mean']:.2f}"
            print(f"{label:<32} | {w_str:<18} | {f_str:<10} | {lf_str:<10} | {done_str:<8} | {wait_str:<12} | {p95w_str:<8} | {u_str:<8} | {j_str:<6}")
        print("-" * len(header))
        print(f"Comparison: Full SunkGuard vs Best No-Reservation Variant ({best_no_rsv_label}):")
        print(f"  Relative Token Waste Reduction: {rel_reduction*100:.2f}% (Required: >= 20.0%) -> {'PASS' if criterion_20pct_rel else 'FAIL'}")
        print(f"  Paired 95% CI of Reduction: [{diff_l:.4f}, {diff_u:.4f}] (Excludes 0: {criterion_ci_excludes_zero}) -> {'PASS' if criterion_ci_excludes_zero else 'FAIL'}")
        print(f"  Wait Ratio vs Baseline: {full_wait_ratio:.2f}x (Required: < 2.00x) -> {'PASS' if criterion_wait_ceiling else 'FAIL'}")
        print(f"  LOAD {load} VERDICT: {'PASS' if load_verdict else 'FAIL'}")

    all_results["final_verdict"] = "PASS" if all_results["overall_verdict"] else "FAIL"

    # Save results to eval/results/gate3_ablation_results.json and root gate3_results.json
    out_paths = [
        Path(__file__).resolve().parent.parent / "eval" / "results" / "gate3_ablation_results.json",
        Path(__file__).resolve().parent.parent / "gate3_results.json",
    ]
    for p in out_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nSaved machine-readable results to: {p}")

    print(f"\n================================================================================")
    print(f"OVERALL THESIS GATE 3 VERDICT: {all_results['final_verdict']}")
    print(f"================================================================================\n")

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Phase 3 comprehensive ablation on fresh seeds 151-250")
    parser.add_argument("--loads", nargs="+", type=float, default=[0.25, 0.50, 0.70])
    parser.add_argument("--ticks", type=int, default=150)
    args = parser.parse_args()

    run_gate3_evaluation(
        seeds=PHASE3_FRESH_SEEDS,
        loads=args.loads,
        ticks=args.ticks,
    )
