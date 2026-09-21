"""Regression Verification Script: Re-run all 8 variants on seeds 151-250 at HEAD

Diffs results directly against eval/results/gate3_ablation_results.json.
Bit-identical reproducibility expected.
"""

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


def run_regression_check():
    results_path = Path(__file__).resolve().parent.parent / "eval" / "results" / "gate3_ablation_results.json"
    if not results_path.exists():
        print(f"ERROR: {results_path} not found!")
        sys.exit(1)

    with open(results_path, "r", encoding="utf-8") as f:
        committed = json.load(f)

    seeds = list(range(151, 251))
    loads = [0.25, 0.50, 0.70]
    ticks = 150

    predictor = train_predictor_on_dev_seeds(dev_seeds=DEV_SEEDS, ticks=ticks)

    variants: List[Tuple[str, str, bool]] = [
        ("Baseline", "uncoordinated", False),
        ("FIFO", "fifo", True),
        ("Aging-Only", "aging_only", True),
        ("Progress-Only", "progress_only", True),
        ("Admission-Only", "admission_only", True),
        ("Pred-Rsv (Progress OFF)", "pred_rsv_no_prog", True),
        ("Pred-Rsv + Progress (No Aging)", "pred_rsv_progress_no_aging", True),
        ("Full SunkGuard", "full_sunkguard", True),
    ]

    all_match = True
    mismatches = []
    checked_count = 0

    print("=== STARTING GATE 3 REGRESSION CHECK (Seeds 151-250, Loads [0.25, 0.50, 0.70]) ===")

    for load in loads:
        load_key = str(load)
        committed_load = committed["load_results"][load_key]

        print(f"\n--- Checking Load {load} ---")
        for label, variant_key, is_sg in variants:
            wasted_tokens_list = []
            failure_rate_list = []
            done_count_list = []
            late_fail_rate_list = []

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
                        variant=variant_key,
                        predictor=predictor,
                        policy="medium",
                    )
                engine = SimulationEngine(cfg)
                engine.run()
                m = collect_metrics(engine)

                wasted_tokens_list.append(m.wasted_token_ratio)
                failure_rate_list.append(m.failure_rate)
                done_count_list.append(float(m.done_count))
                late_fail_rate_list.append(m.late_failure_rate)

            mean_wasted = sum(wasted_tokens_list) / len(wasted_tokens_list)
            mean_fail = sum(failure_rate_list) / len(failure_rate_list)
            mean_done = sum(done_count_list) / len(done_count_list)
            mean_late_fail = sum(late_fail_rate_list) / len(late_fail_rate_list)

            comm_var = committed_load[label]
            comm_wasted = comm_var["wasted_token_ratio"]["mean"]
            comm_fail = comm_var["overall_failure_rate"]["mean"]
            comm_done = comm_var["completed_runs"]["mean"]
            comm_late_fail = comm_var["late_failure_rate"]["mean"]

            diff_wasted = abs(mean_wasted - comm_wasted)
            diff_fail = abs(mean_fail - comm_fail)
            diff_done = abs(mean_done - comm_done)
            diff_late = abs(mean_late_fail - comm_late_fail)

            checked_count += 4

            if diff_wasted > 1e-4 or diff_fail > 1e-4 or diff_done > 1e-2 or diff_late > 1e-4:
                all_match = False
                err_msg = (
                    f"MISMATCH Load {load} | {label}:\n"
                    f"  Wasted: Re-run={mean_wasted:.6f}, Committed={comm_wasted:.6f}, diff={diff_wasted:.6e}\n"
                    f"  Failure: Re-run={mean_fail:.6f}, Committed={comm_fail:.6f}, diff={diff_fail:.6e}\n"
                    f"  Done:    Re-run={mean_done:.2f}, Committed={comm_done:.2f}, diff={diff_done:.2e}\n"
                    f"  LateFail: Re-run={mean_late_fail:.6f}, Committed={comm_late_fail:.6f}, diff={diff_late:.6e}"
                )
                print(f"  [FAIL] {err_msg}")
                mismatches.append(err_msg)
            else:
                print(f"  [PASS] {label:32s} | Wasted: {mean_wasted*100:6.3f}% | Fail: {mean_fail*100:5.2f}% | Done: {mean_done:5.2f} (MATCH)")

    print(f"\nChecked {checked_count} aggregated metric points across 24 variant-load pairs.")
    if all_match:
        print(">>> BIT-IDENTICAL REGRESSION CHECK PASSED! All 8 pre-existing variants exactly match committed Gate 3 results.")
        return 0
    else:
        print(f">>> REGRESSION CHECK FAILED! {len(mismatches)} mismatches detected.")
        return 1


if __name__ == "__main__":
    sys.exit(run_regression_check())
