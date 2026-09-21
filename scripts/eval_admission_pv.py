#!/usr/bin/env python3
"""Exploratory Variant Evaluation: admission_pv.

Specification:
- Priority = base + aging + beta * W_done / (eps + predicted remaining capacity units)
- No reservations (R = empty)
- Tune beta ONLY on DEV_SEEDS (1-20) across loads [0.25, 0.50, 0.70]
- Evaluate tuned beta on fresh exploratory seeds (251-300)
- Compare against Admission-Only, FIFO, and Baseline
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.metrics import collect_metrics, percentile
from core.predictor import train_predictor_on_dev_seeds
from core.seeds import DEV_SEEDS
from core.sim import SimulationConfig, SimulationEngine

EXPLORATORY_SEEDS: List[int] = list(range(251, 301))


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
    diffs = [x - y for x, y in zip(a, b)]
    mean, lower, upper = compute_ci(diffs)
    excludes_zero = (lower > 0.0 and upper > 0.0) or (lower < 0.0 and upper < 0.0)
    return mean, lower, upper, excludes_zero


def tune_beta_on_dev_seeds(
    predictor,
    candidate_betas: List[float] = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0],
    dev_seeds: List[int] = DEV_SEEDS,
    loads: List[float] = [0.25, 0.50, 0.70],
    ticks: int = 150,
) -> Tuple[float, Dict[float, float]]:
    print(f"\n--- TUNING BETA ON DEV SEEDS 1..{dev_seeds[-1]} ({len(dev_seeds)} seeds) ---")
    beta_scores: Dict[float, float] = {}

    for beta in candidate_betas:
        load_wastes = []
        for load in loads:
            seed_wastes = []
            for s in dev_seeds:
                cfg = SimulationConfig(
                    seed=s,
                    total_ticks=ticks,
                    load_factor=load,
                    is_sunkguard=True,
                    variant="admission_pv",
                    predictor=predictor,
                    policy="medium",
                    beta_pv=beta,
                )
                engine = SimulationEngine(cfg)
                engine.run()
                m = collect_metrics(engine)
                seed_wastes.append(m.wasted_token_ratio)
            load_wastes.append(sum(seed_wastes) / len(seed_wastes))
        # Average wasted token ratio across loads (weighted towards heavier loads where contention exists)
        avg_waste = (load_wastes[0] + 2.0 * load_wastes[1] + 3.0 * load_wastes[2]) / 6.0
        beta_scores[beta] = avg_waste
        print(f"  beta = {beta:4.1f} | Weighted Dev Wasted Tok Ratio = {avg_waste*100:.3f}% (L0.25: {load_wastes[0]*100:.2f}%, L0.50: {load_wastes[1]*100:.2f}%, L0.70: {load_wastes[2]*100:.2f}%)")

    best_beta = min(beta_scores, key=lambda b: beta_scores[b])
    print(f"\nOptimal beta selected strictly from Dev Seeds: beta* = {best_beta}")
    return best_beta, beta_scores


def run_exploratory_evaluation(
    best_beta: float,
    eval_seeds: List[int] = EXPLORATORY_SEEDS,
    loads: List[float] = [0.25, 0.50, 0.70, 0.85],
    ticks: int = 150,
) -> Dict[str, Any]:
    print(f"\n================================================================================")
    print(f" EXPLORATORY EVALUATION: admission_pv (beta*={best_beta}) on SEEDS {eval_seeds[0]}..{eval_seeds[-1]} ")
    print(f"================================================================================")

    predictor = train_predictor_on_dev_seeds(dev_seeds=DEV_SEEDS, ticks=ticks)

    variants: List[Tuple[str, str, bool, float]] = [
        ("Baseline (Stampede)", "uncoordinated", False, 1.0),
        ("FIFO (Headline)", "fifo", True, 1.0),
        ("Admission-Only (Production)", "admission_only", True, 1.0),
        (f"Admission-PV (Exploratory beta={best_beta})", "admission_pv", True, best_beta),
    ]

    all_data: Dict[str, Any] = {
        "status": "EXPLORATORY",
        "selected_beta": best_beta,
        "tuning_seeds": "1..20 (DEV_SEEDS)",
        "evaluation_seeds": f"{eval_seeds[0]}..{eval_seeds[-1]}",
        "seed_count": len(eval_seeds),
        "loads": loads,
        "load_results": {},
    }

    for load in loads:
        print(f"\n>>> Running exploratory evaluation at load: {load} ...")
        raw: Dict[str, Dict[str, List[float]]] = {
            v[0]: {"wasted": [], "fail": [], "late_cnt": [], "done": [], "wait": []}
            for v in variants
        }

        for label, v_key, is_sg, b_val in variants:
            for s in eval_seeds:
                cfg = SimulationConfig(
                    seed=s,
                    total_ticks=ticks,
                    load_factor=load,
                    is_sunkguard=is_sg,
                    variant=v_key if is_sg else "full_sunkguard",  # type: ignore
                    predictor=predictor if is_sg else None,
                    policy="medium",
                    beta_pv=b_val,
                )
                engine = SimulationEngine(cfg)
                engine.run()
                m = collect_metrics(engine)
                raw[label]["wasted"].append(m.wasted_token_ratio)
                raw[label]["fail"].append(m.failure_rate)
                raw[label]["late_cnt"].append(float(m.late_failed_count))
                raw[label]["done"].append(float(m.done_count))
                raw[label]["wait"].append(m.mean_new_work_wait)

        fifo_wasted = raw["FIFO (Headline)"]["wasted"]
        adm_wasted = raw["Admission-Only (Production)"]["wasted"]

        load_summary: Dict[str, Any] = {}
        for label in [v[0] for v in variants]:
            w_m, w_l, w_u = compute_ci(raw[label]["wasted"])
            f_m, f_l, f_u = compute_ci(raw[label]["fail"])
            lf_m, _, _ = compute_ci(raw[label]["late_cnt"])
            d_m, d_l, d_u = compute_ci(raw[label]["done"])
            wait_m, wait_l, wait_u = compute_ci(raw[label]["wait"])

            # Paired CI vs FIFO
            p_vs_fifo, p_fifo_l, p_fifo_u, _ = compute_paired_ci(raw[label]["wasted"], fifo_wasted)
            # Paired CI vs Admission-Only
            p_vs_adm, p_adm_l, p_adm_u, p_adm_sig = compute_paired_ci(raw[label]["wasted"], adm_wasted)

            load_summary[label] = {
                "wasted_token_ratio": {
                    "mean": round(w_m, 4),
                    "ci_95": [round(w_l, 4), round(w_u, 4)],
                    "paired_diff_vs_fifo": [round(p_vs_fifo, 4), round(p_fifo_l, 4), round(p_fifo_u, 4)],
                    "paired_diff_vs_admission_only": [round(p_vs_adm, 4), round(p_adm_l, 4), round(p_adm_u, 4)],
                },
                "failure_rate": round(f_m, 4),
                "late_fail_count": round(lf_m, 2),
                "completed_runs": round(d_m, 2),
                "wait_ticks": round(wait_m, 3),
            }

        all_data["load_results"][str(load)] = load_summary

        print(f"\n--- LOAD {load} EXPLORATORY COMPARISON ---")
        header = f"{'Variant':<42} | {'Wasted Tok %':<16} | {'Fail %':<10} | {'Late Fails':<10} | {'Done':<8} | {'Wait (t)':<8}"
        print("-" * len(header))
        print(header)
        print("-" * len(header))
        for lbl in [v[0] for v in variants]:
            d = load_summary[lbl]
            w_str = f"{d['wasted_token_ratio']['mean']*100:.2f}% [{d['wasted_token_ratio']['ci_95'][0]*100:.2f}..{d['wasted_token_ratio']['ci_95'][1]*100:.2f}]"
            f_str = f"{d['failure_rate']*100:.1f}%"
            lf_str = f"{d['late_fail_count']:.2f}"
            done_str = f"{d['completed_runs']:.1f}"
            wait_str = f"{d['wait_ticks']:.2f}t"
            print(f"{lbl:<42} | {w_str:<16} | {f_str:<10} | {lf_str:<10} | {done_str:<8} | {wait_str:<8}")
        print("-" * len(header))

    out_file = Path(__file__).resolve().parent.parent / "eval" / "results" / "exploratory_admission_pv_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2)
    print(f"\nSaved exploratory results to: {out_file}")

    return all_data


if __name__ == "__main__":
    predictor = train_predictor_on_dev_seeds(dev_seeds=DEV_SEEDS)
    best_beta, tuning_table = tune_beta_on_dev_seeds(predictor)
    run_exploratory_evaluation(best_beta=best_beta)
