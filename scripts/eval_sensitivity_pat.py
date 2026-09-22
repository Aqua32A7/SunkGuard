#!/usr/bin/env python3
"""Sensitivity Analysis: oldest_first vs progress_only vs admission_only across PAT in {4, 8, 16, 32}.

Evaluates on exploratory held-out seeds 401-500 (n=100) across loads [0.50, 0.70]:
- oldest_first (strict arrival order, no aging, no progress)
- progress_only (progress weighting ON, wait aging OFF, no reservations)
- admission_only (progress weighting ON, wait aging ON, no reservations)

Records:
- Wasted-token ratio (mean, 95% CI)
- Overall failure rate (mean, 95% CI)
- Completed runs (mean, 95% CI)
- Late failures (count, rate)
- New-work wait ticks (mean, p95)
- Starved count (step-0 timeouts)
- Jain's fairness index
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

from core.metrics import collect_metrics, percentile
from core.sim import SimulationConfig, SimulationEngine


SEEDS = range(401, 501)  # n=100 seeds (401-500)
PATS = [4, 8, 16, 32]
LOADS = [0.50, 0.70]

VARIANTS = [
    ("Oldest-First", "oldest_first"),
    ("Progress-Only", "progress_only"),
    ("Admission-Only", "admission_only"),
]


def mean_and_ci(data: List[float]) -> Tuple[float, List[float]]:
    if not data:
        return 0.0, [0.0, 0.0]
    n = len(data)
    m = statistics.mean(data)
    if n < 2:
        return m, [m, m]
    s = statistics.stdev(data)
    t_val = 1.984  # df=99, 95% CI
    hw = t_val * (s / math.sqrt(n))
    return round(m, 5), [round(m - hw, 5), round(m + hw, 5)]


def paired_diff_ci(a: List[float], b: List[float]) -> Tuple[float, List[float]]:
    diffs = [x - y for x, y in zip(a, b)]
    return mean_and_ci(diffs)


def run_sensitivity_evaluation() -> Dict[str, Any]:
    print("=" * 90)
    print("SENSITIVITY ANALYSIS: oldest_first vs progress_only vs admission_only")
    print(f"Seeds: 401-500 (n={len(SEEDS)}) | PAT in {PATS} | Loads: {LOADS}")
    print("=" * 90)

    results: Dict[str, Any] = {
        "evaluation_name": "PAT Sensitivity Analysis (Exploratory Seeds 401-500)",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seeds": "401-500",
        "seed_count": len(SEEDS),
        "pats": PATS,
        "loads": LOADS,
        "results": {},
    }

    t0_all = time.time()

    for load in LOADS:
        load_str = f"{load:.2f}"
        results["results"][load_str] = {}
        print(f"\n################ LOAD {load_str} ################")

        for pat in PATS:
            pat_str = str(pat)
            results["results"][load_str][pat_str] = {}
            print(f"\n--- Evaluating PAT = {pat} ticks ---")

            raw: Dict[str, Dict[str, List[float]]] = {
                label: {
                    "wasted": [],
                    "fail": [],
                    "done": [],
                    "late_cnt": [],
                    "late_rate": [],
                    "wait": [],
                    "starved": [],
                    "jain": [],
                }
                for label, _ in VARIANTS
            }

            for s in SEEDS:
                for label, v_code in VARIANTS:
                    cfg = SimulationConfig(
                        seed=s,
                        total_ticks=200,
                        load_factor=load,
                        is_sunkguard=True,
                        variant=v_code,
                        policy="medium",
                        pat_override=pat,
                    )
                    eng = SimulationEngine(cfg)
                    eng.run()
                    m = collect_metrics(eng)

                    # Initial admission wait
                    step0_waits = [
                        w.initial_wait_time
                        for w in eng.completed_workflows + eng.failed_workflows + eng.starved_workflows
                        if hasattr(w, "initial_wait_time")
                    ]
                    mean_wait = statistics.mean(step0_waits) if step0_waits else 0.0

                    raw[label]["wasted"].append(m.wasted_token_ratio)
                    raw[label]["fail"].append(m.failure_rate)
                    raw[label]["done"].append(float(m.done_count))
                    raw[label]["late_cnt"].append(float(m.late_failed_count))
                    raw[label]["late_rate"].append(m.late_failure_rate)
                    raw[label]["wait"].append(mean_wait)
                    raw[label]["starved"].append(float(m.starved_count))
                    raw[label]["jain"].append(m.jain_fairness)

            # Summarize
            for label, _ in VARIANTS:
                w_m, w_ci = mean_and_ci(raw[label]["wasted"])
                f_m, f_ci = mean_and_ci(raw[label]["fail"])
                d_m, d_ci = mean_and_ci(raw[label]["done"])
                lf_m, lf_ci = mean_and_ci(raw[label]["late_cnt"])
                wt_m, wt_ci = mean_and_ci(raw[label]["wait"])
                st_m, st_ci = mean_and_ci(raw[label]["starved"])
                jn_m, jn_ci = mean_and_ci(raw[label]["jain"])

                results["results"][load_str][pat_str][label] = {
                    "wasted_token_ratio": {"mean": w_m, "ci_95": w_ci},
                    "overall_failure_rate": {"mean": f_m, "ci_95": f_ci},
                    "completed_runs": {"mean": d_m, "ci_95": d_ci},
                    "late_failure_count": {"mean": lf_m, "ci_95": lf_ci},
                    "step0_wait_ticks": {"mean": wt_m, "ci_95": wt_ci},
                    "starved_count": {"mean": st_m, "ci_95": st_ci},
                    "jain_fairness": {"mean": jn_m, "ci_95": jn_ci},
                }

                print(
                    f"  {label:16s} | Waste: {w_m*100:5.3f}% [{w_ci[0]*100:.2f}, {w_ci[1]*100:.2f}] | "
                    f"Fail: {f_m*100:5.2f}% | Done: {d_m:5.1f} | LateF: {lf_m:4.2f} | "
                    f"Wait: {wt_m:4.2f}t | Starved: {st_m:4.2f} | Jain: {jn_m:.4f}"
                )

            # Paired comparison: Admission-Only vs Progress-Only (isolating the effect of aging)
            adm_w = raw["Admission-Only"]["wasted"]
            prg_w = raw["Progress-Only"]["wasted"]
            diff_w_m, diff_w_ci = paired_diff_ci(adm_w, prg_w)

            adm_f = raw["Admission-Only"]["fail"]
            prg_f = raw["Progress-Only"]["fail"]
            diff_f_m, diff_f_ci = paired_diff_ci(adm_f, prg_f)

            adm_wt = raw["Admission-Only"]["wait"]
            prg_wt = raw["Progress-Only"]["wait"]
            diff_wt_m, diff_wt_ci = paired_diff_ci(adm_wt, prg_wt)

            results["results"][load_str][pat_str]["paired_adm_vs_prog"] = {
                "delta_waste": {"mean": diff_w_m, "ci_95": diff_w_ci},
                "delta_fail": {"mean": diff_f_m, "ci_95": diff_f_ci},
                "delta_wait": {"mean": diff_wt_m, "ci_95": diff_wt_ci},
            }
            print(
                f"  --> Paired (Adm - Prog): ΔWaste = {diff_w_m*100:+.3f}% [{diff_w_ci[0]*100:+.3f}%, {diff_w_ci[1]*100:+.3f}%] | "
                f"ΔFail = {diff_f_m*100:+.2f}% | ΔWait = {diff_wt_m:+.2f}t"
            )

    out_file = Path(__file__).resolve().parent.parent / "eval" / "results" / "sensitivity_pat_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n[DONE] Saved sensitivity results in {time.time() - t0_all:.1f}s to: {out_file}")
    return results


if __name__ == "__main__":
    run_sensitivity_evaluation()
