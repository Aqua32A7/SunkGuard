import os
import sys
import json
from typing import List, Dict, Any

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.controller import POLICIES
from core.metrics import collect_metrics, percentile
from core.predictor import train_predictor_on_dev_seeds
from core.seeds import DEV_SEEDS
from core.sim import SimulationConfig, SimulationEngine

def evaluate_completion_latency(seeds: List[int], loads: List[float]):
    predictor = train_predictor_on_dev_seeds(dev_seeds=DEV_SEEDS, ticks=150)
    variants = [
        ("Baseline", "uncoordinated", False),
        ("Admission-Only", "admission_only", True),
        ("Full SunkGuard", "full_sunkguard", True),
    ]

    results = {}
    for load in loads:
        results[str(load)] = {}
        for label, vkey, is_sg in variants:
            all_durations = []
            all_waits = []
            per_seed_p95_dur = []
            per_seed_p99_dur = []
            per_seed_mean_dur = []
            per_seed_done = []
            per_seed_fail = []

            for s in seeds:
                cfg = SimulationConfig(
                    seed=s,
                    total_ticks=150,
                    load_factor=load,
                    is_sunkguard=is_sg,
                    variant=vkey,
                    predictor=predictor,
                    policy="medium",
                )
                engine = SimulationEngine(cfg)
                engine.run()
                m = collect_metrics(engine)

                # Collect completion durations of successful workflows: (end_tick - born_tick)
                completed_durs = [
                    (wf.end_tick - wf.born_tick)
                    for wf in engine.completed_workflows
                    if wf.end_tick >= 0
                ]
                all_durations.extend(completed_durs)
                all_waits.extend(engine.initial_admission_waits)

                if completed_durs:
                    per_seed_p95_dur.append(percentile(completed_durs, 0.95))
                    per_seed_p99_dur.append(percentile(completed_durs, 0.99))
                    per_seed_mean_dur.append(sum(completed_durs) / len(completed_durs))
                per_seed_done.append(m.done_count)
                per_seed_fail.append(m.failure_rate)

            n = len(seeds)
            results[str(load)][label] = {
                "aggregate_p50_duration": percentile(all_durations, 0.50),
                "aggregate_p95_duration": percentile(all_durations, 0.95),
                "aggregate_p99_duration": percentile(all_durations, 0.99),
                "mean_duration": sum(per_seed_mean_dur) / len(per_seed_mean_dur) if per_seed_mean_dur else 0.0,
                "aggregate_p95_wait": percentile(all_waits, 0.95),
                "aggregate_p99_wait": percentile(all_waits, 0.99),
                "done_runs": sum(per_seed_done) / n,
                "fail_rate": sum(per_seed_fail) / n,
            }

    return results

if __name__ == "__main__":
    fresh_seeds = list(range(101, 151)) # 50 fresh seeds
    loads = [0.25, 0.50, 0.70]
    print(f"Running completion latency evaluation across {len(fresh_seeds)} FRESH seeds ({fresh_seeds[0]}..{fresh_seeds[-1]})...")
    res = evaluate_completion_latency(fresh_seeds, loads)

    print("\n================ LATENCY EVALUATION RESULTS (FRESH SEEDS 101-150) ================")
    for load_str, variants in res.items():
        print(f"\n### Load Level: {load_str}")
        print(f"| Variant | Done Runs | Fail% | Mean Dur | p50 Dur | p95 Dur | p99 Dur | p95 Wait | p99 Wait |")
        print(f"|---|---|---|---|---|---|---|---|---|")
        for vname, d in variants.items():
            print(f"| {vname:15} | {d['done_runs']:5.1f} | {d['fail_rate']*100:4.1f}% | {d['mean_duration']:6.2f}t | {d['aggregate_p50_duration']:4.1f}t | {d['aggregate_p95_duration']:4.1f}t | {d['aggregate_p99_duration']:4.1f}t | {d['aggregate_p95_wait']:4.1f}t | {d['aggregate_p99_wait']:4.1f}t |")
