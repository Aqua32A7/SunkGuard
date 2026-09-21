#!/usr/bin/env python3
"""Phase 2 Thesis Gate & Controller Ablation Evaluator.

Enforces experimental integrity:
- Refuses to run if git working tree is dirty.
- Refuses to run if HEAD does not match tag 'thesis-gate2-frozen'.
- Strictly uses held-out seeds 51-100.
- Evaluates all 4 controller variants against Baseline.
- Records commit hash, config hash, seed list, and timestamp into gate2_results.json.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.controller import POLICIES, ControllerVariant
from core.metrics import collect_metrics, percentile
from core.predictor import NonOraclePredictor, train_predictor_on_dev_seeds
from core.seeds import DEV_SEEDS, PHASE2_HELD_OUT_SEEDS
from core.sim import SimulationConfig, SimulationEngine


def check_git_integrity(expected_tag: str = "thesis-gate2-frozen") -> str:
    """Verifies that the working tree is clean and HEAD matches the expected tag."""
    # 1. Check for dirty working tree
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
            f"Commit all changes and tag with '{expected_tag}' before running Gate 2."
        )

    # 2. Check current commit hash
    commit_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    head_commit = commit_proc.stdout.strip()

    # 3. Check tag match
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


def run_ablation_evaluation(
    predictor: NonOraclePredictor,
    seeds: List[int],
    loads: List[float],
    ticks: int = 150,
) -> Dict[str, Any]:
    """Runs ablation sweep across all 4 variants and Baseline on held-out seeds."""
    variants: List[tuple[str, str, bool]] = [
        ("Baseline", "uncoordinated", False),
        ("Admission-Only", "admission_only", True),
        ("Pred-Rsv (Progress OFF)", "prediction_reservation", True),
        ("Pred-Rsv + Progress (No Aging)", "prediction_reservation_progress", True),
        ("Full SunkGuard (+Aging)", "full_sunkguard", True),
    ]

    ablation_results = []

    for load in loads:
        load_entry: Dict[str, Any] = {"load": load, "variants": {}}

        for label, variant_key, is_sg in variants:
            wasted_tok_list = []
            fail_rate_list = []
            done_cnt_list = []
            late_fail_list = []
            wait_ticks_list = []
            raw_waits = []

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

                wasted_tok_list.append(m.wasted_token_ratio)
                fail_rate_list.append(m.failure_rate)
                done_cnt_list.append(m.done_count)
                late_fail_list.append(m.late_failed_count)
                wait_ticks_list.append(m.mean_new_work_wait)
                raw_waits.extend(engine.initial_admission_waits)

            n = len(seeds)
            avg_wasted_tok = sum(wasted_tok_list) / n
            avg_fail_rate = sum(fail_rate_list) / n
            avg_done = sum(done_cnt_list) / n
            avg_late_fail = sum(late_fail_list) / n
            avg_wait = sum(wait_ticks_list) / n
            p95_wait = percentile(raw_waits, 0.95)

            load_entry["variants"][label] = {
                "wasted_token_ratio": avg_wasted_tok,
                "overall_failure_rate": avg_fail_rate,
                "completed_runs": avg_done,
                "late_failures": avg_late_fail,
                "mean_wait_ticks": avg_wait,
                "p95_wait_ticks": p95_wait,
            }

        # Calculate deltas relative to Baseline
        base_stats = load_entry["variants"]["Baseline"]
        base_wasted = base_stats["wasted_token_ratio"]
        base_wait = base_stats["mean_wait_ticks"]

        for label, stats in load_entry["variants"].items():
            if label == "Baseline":
                stats["wasted_token_reduction"] = 0.0
                stats["added_wait_ticks"] = 0.0
                stats["wait_ratio_of_means"] = 1.0
            else:
                rel_red = (base_wasted - stats["wasted_token_ratio"]) / base_wasted if base_wasted > 0 else 0.0
                stats["wasted_token_reduction"] = rel_red
                stats["added_wait_ticks"] = stats["mean_wait_ticks"] - base_wait
                stats["wait_ratio_of_means"] = stats["mean_wait_ticks"] / base_wait if base_wait > 0 else 1.0

        ablation_results.append(load_entry)

    return {"loads_evaluated": ablation_results}


def main():
    parser = argparse.ArgumentParser(description="Phase 2 Thesis Gate 2 Evaluation")
    parser.add_argument("--skip-git-check", action="store_true", help="Bypass git tag/clean check for dev dry-runs")
    parser.add_argument("--json-out", type=str, default="gate2_results.json", help="Path to write results JSON")
    parser.add_argument("--ticks", type=int, default=150, help="Ticks per simulation")
    args = parser.parse_args()

    commit_hash = "dev-dry-run"
    if not args.skip_git_check:
        commit_hash = check_git_integrity("thesis-gate2-frozen")
        print(f"[Gate 2 Integrity] Verified clean tree at tagged commit: {commit_hash[:8]}")
    else:
        print("[Gate 2 Warning] Running with --skip-git-check (dry-run mode)")

    config_hash = compute_config_hash()
    test_seeds = PHASE2_HELD_OUT_SEEDS  # seeds 51-100
    loads = [0.25, 0.40, 0.50, 0.55, 0.70, 0.85]

    print(f"[Predictor Training] Training non-oracle predictor on DEV_SEEDS (1-20)...")
    predictor = train_predictor_on_dev_seeds(dev_seeds=DEV_SEEDS, ticks=args.ticks)
    print(f"[Predictor Training] Fitted transitions across {len(predictor.transitions)} templates.")

    print(f"[Gate 2 Ablation] Evaluating {len(test_seeds)} held-out seeds ({test_seeds[0]}..{test_seeds[-1]})...")
    eval_data = run_ablation_evaluation(predictor, test_seeds, loads, ticks=args.ticks)

    output = {
        "gate": "thesis-gate2-frozen",
        "commit_hash": commit_hash,
        "config_hash": config_hash,
        "seed_count": len(test_seeds),
        "seed_list": test_seeds,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation": eval_data,
    }

    with open(args.json_out, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[Gate 2 Complete] Results written to {args.json_out}")

    # Print summary table at target load 0.50 and 0.55
    print("\n==========================================================================================")
    print("                 PHASE 2 CONTROLLER ABLATION RESULTS (HELD-OUT SEEDS 51-100)               ")
    print("==========================================================================================")

    for target_load in [0.25, 0.50, 0.70]:
        entry = next(e for e in eval_data["loads_evaluated"] if abs(e["load"] - target_load) < 0.01)
        print(f"\n### Load Level: {target_load:.2f}")
        headers = ["Variant", "Wasted Tok Ratio", "Wasted Tok Red%", "Overall Fail%", "Done Runs", "Late Fails", "Added Wait (t)", "Ratio of Means"]
        print("| " + " | ".join(headers) + " |")
        print("|" + "|".join(["---"] * len(headers)) + "|")
        for vname, vstats in entry["variants"].items():
            print(
                f"| {vname:<30} | {vstats['wasted_token_ratio']*100:.2f}% | "
                f"{vstats['wasted_token_reduction']*100:+.1f}% | {vstats['overall_failure_rate']*100:.1f}% | "
                f"{vstats['completed_runs']:.1f} | {vstats['late_failures']:.2f} | "
                f"{vstats['added_wait_ticks']:+.2f}t | {vstats['wait_ratio_of_means']:.2f}x |"
            )


if __name__ == "__main__":
    main()
