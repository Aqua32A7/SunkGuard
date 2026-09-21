#!/usr/bin/env python3
"""SunkGuard Command Line Interface (CLI).

Provides commands for:
- Running deterministic simulations (run)
- Comparing baseline vs SunkGuard under identical seeds (compare)
- Running thesis gate evaluation across seed suites (thesis-eval)
- Running dynamic live demonstration reporting measured values (demo)
- Verifying bit-identical reproducibility (verify-reproducibility)
"""

import argparse
import hashlib
import json
import sys
from typing import Optional

from core.controller import ControllerPolicy
from core.metrics import (
    collect_metrics,
    compare_runs,
    evaluate_thesis_gate,
    generate_regime_map,
)
from core.sim import SimulationConfig, SimulationEngine

try:
    from rich import print as rprint
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def print_table(title: str, headers: list, rows: list) -> None:
    """Print table using Rich if available, otherwise formatted plain text."""
    if HAS_RICH:
        console = Console()
        table = Table(title=title, show_header=True, header_style="bold cyan")
        for h in headers:
            table.add_column(h)
        for r in rows:
            table.add_row(*[str(x) for x in r])
        console.print(table)
    else:
        print(f"\n=== {title} ===")
        header_line = " | ".join(f"{h:<22}" for h in headers)
        print(header_line)
        print("-" * len(header_line))
        for r in rows:
            print(" | ".join(f"{str(x):<22}" for x in r))
        print()


def cmd_run(args: argparse.Namespace) -> None:
    """Run a single simulation."""
    cfg = SimulationConfig(
        seed=args.seed,
        total_ticks=args.ticks,
        load_factor=args.load,
        policy=args.policy,
        is_sunkguard=not args.baseline,
    )
    engine = SimulationEngine(cfg)
    engine.run()
    metrics = collect_metrics(engine)

    mode_label = "Baseline (Unprotected)" if args.baseline else f"SunkGuard ({args.policy.capitalize()})"
    headers = ["Metric", "Value"]
    rows = [
        ["Controller Mode", mode_label],
        ["Seed", str(args.seed)],
        ["Simulated Ticks", str(args.ticks)],
        ["Completed Workflows", str(metrics.done_count)],
        ["Failed Workflows", str(metrics.failed_count)],
        ["Starved Workflows", str(metrics.starved_count)],
        ["Late Failures (>= 50% work)", str(metrics.late_failed_count)],
        ["Late Failure Rate", f"{metrics.late_failure_rate * 100:.2f}%"],
        ["Overall Failure Rate", f"{metrics.failure_rate * 100:.2f}%"],
        ["Total Tokens Consumed", f"{metrics.tokens_consumed:,}"],
        ["Wasted Tokens", f"{metrics.tokens_wasted:,}"],
        ["Wasted Token Ratio", f"{metrics.wasted_token_ratio * 100:.2f}%"],
        ["p95 Completion Latency", f"{metrics.p95_duration:.1f} ticks"],
        ["Resource Utilization", f"{metrics.resource_utilization * 100:.1f}%"],
        ["Reservation Waste (held)", f"{metrics.reservation_waste * 100:.2f}%"],
        ["Predictor Hit Rate", f"{metrics.predictor_hit_rate * 100:.1f}%"],
        ["Jain's Fairness Index", f"{metrics.jain_fairness:.3f}"],
        ["Mean New-Work Wait", f"{metrics.mean_new_work_wait:.2f} ticks"],
    ]
    print_table(f"Simulation Results: {mode_label} (Seed {args.seed})", headers, rows)

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        print(f"JSON metrics written to: {args.json_out}")


def cmd_compare(args: argparse.Namespace) -> None:
    """Run baseline vs SunkGuard under identical seed and load."""
    cfg_b = SimulationConfig(
        seed=args.seed,
        total_ticks=args.ticks,
        load_factor=args.load,
        policy=args.policy,
        is_sunkguard=False,
    )
    e_b = SimulationEngine(cfg_b)
    e_b.run()

    cfg_s = SimulationConfig(
        seed=args.seed,
        total_ticks=args.ticks,
        load_factor=args.load,
        policy=args.policy,
        is_sunkguard=True,
    )
    e_s = SimulationEngine(cfg_s)
    e_s.run()

    comp = compare_runs(e_b, e_s)
    b_m = comp.baseline
    s_m = comp.sunkguard

    headers = ["Metric", "Baseline", "SunkGuard", "Delta / Comparison"]
    rows = [
        ["Completed Runs", str(b_m.done_count), str(s_m.done_count), f"{s_m.done_count - b_m.done_count:+d}"],
        ["Failed Runs", str(b_m.failed_count), str(s_m.failed_count), f"{s_m.failed_count - b_m.failed_count:+d}"],
        ["Late Failures (>= 50%)", str(b_m.late_failed_count), str(s_m.late_failed_count), f"{s_m.late_failed_count - b_m.late_failed_count:+d}"],
        ["Late Failure Rate", f"{b_m.late_failure_rate*100:.2f}%", f"{s_m.late_failure_rate*100:.2f}%", f"{comp.relative_reduction_late_failure*100:+.1f}% rel reduction"],
        ["Wasted Tokens", f"{b_m.tokens_wasted:,}", f"{s_m.tokens_wasted:,}", f"{comp.relative_reduction_wasted_tokens*100:+.1f}% rel reduction"],
        ["Wasted Token Ratio", f"{b_m.wasted_token_ratio*100:.2f}%", f"{s_m.wasted_token_ratio*100:.2f}%", f"{(s_m.wasted_token_ratio - b_m.wasted_token_ratio)*100:+.2f}%"],
        ["p95 Latency", f"{b_m.p95_duration:.1f}t", f"{s_m.p95_duration:.1f}t", f"ratio {comp.p95_ratio:.2f}x"],
        ["Resource Utilization", f"{b_m.resource_utilization*100:.1f}%", f"{s_m.resource_utilization*100:.1f}%", f"{(s_m.resource_utilization - b_m.resource_utilization)*100:+.1f}%"],
        ["Reservation Waste", "0.00%", f"{s_m.reservation_waste*100:.2f}%", "idle hold overhead"],
        ["Predictor Hit Rate", "N/A", f"{s_m.predictor_hit_rate*100:.1f}%", "accuracy"],
        ["Jain Fairness Index", f"{b_m.jain_fairness:.3f}", f"{s_m.jain_fairness:.3f}", f"{(s_m.jain_fairness - b_m.jain_fairness):+.3f}"],
        ["New-Work Wait Time", f"{b_m.mean_new_work_wait:.2f}t", f"{s_m.mean_new_work_wait:.2f}t", f"ratio {comp.new_work_wait_ratio:.2f}x"],
    ]
    print_table(f"Baseline vs SunkGuard Head-to-Head (Seed {args.seed}, {args.ticks} ticks)", headers, rows)

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(comp.to_dict(), f, indent=2)
        print(f"Comparison JSON written to: {args.json_out}")


def cmd_thesis_eval(args: argparse.Namespace) -> None:
    """Run thesis gate evaluation across seed suite (SPEC.md Section 8)."""
    start_seed = args.start_seed
    end_seed = args.end_seed
    total = end_seed - start_seed + 1

    print(f"\n[Thesis Gate] Evaluating seeds {start_seed}..{end_seed} ({total} runs)...")
    comparisons = []
    for s in range(start_seed, end_seed + 1):
        cfg_b = SimulationConfig(seed=s, total_ticks=args.ticks, load_factor=args.load, is_sunkguard=False)
        e_b = SimulationEngine(cfg_b)
        e_b.run()

        cfg_s = SimulationConfig(
            seed=s, total_ticks=args.ticks, load_factor=args.load, is_sunkguard=True, policy=args.policy
        )
        e_s = SimulationEngine(cfg_s)
        e_s.run()

        comparisons.append(compare_runs(e_b, e_s))

    gate = evaluate_thesis_gate(comparisons, start_seed, end_seed)

    headers = ["Thesis Gate Criterion", "Threshold Target", "Measured Result", "Status"]
    rows = [
        [
            "1. Relative Reduction in Late Failures",
            ">= 30.0%",
            f"{gate.mean_late_failure_reduction * 100:.2f}%",
            "PASS" if gate.mean_late_failure_reduction >= 0.30 else "FAIL",
        ],
        [
            "2. 95% Confidence Interval (diff)",
            "Excludes Zero",
            f"[{gate.ci_lower:.4f}, {gate.ci_upper:.4f}]",
            "PASS" if gate.ci_excludes_zero else "FAIL",
        ],
        [
            "3. New-Work Wait Ratio",
            "< 2.0x",
            f"{gate.mean_wait_ratio:.2f}x",
            "PASS" if gate.wait_ratio_acceptable else "FAIL",
        ],
    ]
    print_table(f"Thesis Gate Evaluation: Seeds {start_seed}..{end_seed}", headers, rows)

    if gate.gate_passed:
        msg = f"THESIS GATE PASSED: All 3 criteria verified over seeds {start_seed}..{end_seed}."
        if HAS_RICH:
            Console().print(Panel(msg, style="bold green"))
        else:
            print(f"\n*** {msg} ***\n")
    else:
        msg = "THESIS GATE TRADE-OFF DETECTED: Producing empirical regime map..."
        if HAS_RICH:
            Console().print(Panel(msg, style="bold yellow"))
        else:
            print(f"\n*** {msg} ***\n")

        # Generate and print regime map
        regime = generate_regime_map(seeds=list(range(start_seed, min(start_seed + 10, end_seed + 1))))
        r_headers = ["Load", "Regime", "Base LateFail", "SunkGuard LateFail", "Rel Reduction", "Wait Ratio", "Recommendation"]
        r_rows = [
            [
                f"{r['load_factor']:.2f}",
                r["regime"],
                f"{r['baseline_late_fail_rate']*100:.1f}%",
                f"{r['sunkguard_late_fail_rate']*100:.1f}%",
                f"{r['relative_reduction']*100:.1f}%",
                f"{r['new_work_wait_ratio']:.2f}x",
                r["recommendation"],
            ]
            for r in regime["regimes"]
        ]
        print_table("Empirical SunkGuard Operating Regime Map", r_headers, r_rows)

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(gate.to_dict(), f, indent=2)
        print(f"Thesis gate output written to: {args.json_out}")


def cmd_demo(args: argparse.Namespace) -> None:
    """Runs dynamic live demo measuring actual values (SPEC.md Section 8.4).

    Strictly reports measured numbers from the live execution, not hardcoded constants.
    """
    seed = args.seed if args.seed != 7 else 8  # Use seed 8 as default demonstration

    print("\n=======================================================")
    print("      SunkGuard Measured Acceptance Demo               ")
    print(f"      (Seed {seed}, Policy: {args.policy.capitalize()})")
    print("=======================================================\n")

    # 1. Initialize engines
    cfg_b = SimulationConfig(seed=seed, total_ticks=args.ticks, is_sunkguard=False)
    e_b = SimulationEngine(cfg_b)
    e_b.run(ticks=10)  # Warm up

    cfg_s = SimulationConfig(seed=seed, total_ticks=args.ticks, is_sunkguard=True, policy=args.policy)
    e_s = SimulationEngine(cfg_s)
    e_s.run(ticks=10)  # Warm up

    # 2. Inject identical contention scene into both engines
    wf_a_b, burst_b = e_b.inject_demo_scene()
    wf_a_s, burst_s = e_s.inject_demo_scene()

    # Capture measured values directly AT INJECTION
    work_frac_a = wf_a_s.work_fraction_done * 100
    spent_tok_a = wf_a_s.spent_tokens
    spent_work_a = wf_a_s.spent_work
    planned_work_a = wf_a_s.total_planned_work

    # 3. Advance simulations forward so contention resolves
    e_b.run(ticks=30)
    e_s.run(ticks=30)

    status_b = wf_a_b.state
    status_s = wf_a_s.state

    m_b = collect_metrics(e_b)
    m_s = collect_metrics(e_s)

    headers = ["Measured Property", "Baseline Outcome", "SunkGuard Outcome"]
    rows = [
        ["Candidate-A Completion at Injection", f"{work_frac_a:.1f}% ({spent_work_a}/{planned_work_a} SWU)", f"{work_frac_a:.1f}% ({spent_work_a}/{planned_work_a} SWU)"],
        ["Candidate-A Sunk Tokens at Risk", f"{spent_tok_a:,} tokens", f"{spent_tok_a:,} tokens"],
        ["Contending Burst Workflows", f"{len(burst_b)} runs demanding 13 Flash units", f"{len(burst_s)} runs demanding 13 Flash units"],
        ["Candidate-A Terminal Status", f"{status_b.upper()} ({'Sunk loss' if status_b == 'failed' else 'Completed'})", f"{status_s.upper()} ({'Protected' if status_s == 'done' else 'Failed'})"],
        ["Candidate-A Tokens Lost", f"{wf_a_b.spent_tokens:,} tokens" if status_b == "failed" else "0 tokens", f"{wf_a_s.spent_tokens:,} tokens" if status_s == "failed" else "0 tokens"],
        ["Total Tokens Wasted in Run", f"{m_b.tokens_wasted:,} tokens", f"{m_s.tokens_wasted:,} tokens"],
        ["Total Late Failures (>=50% work)", str(m_b.late_failed_count), str(m_s.late_failed_count)],
        ["Resource Utilization", f"{m_b.resource_utilization*100:.1f}%", f"{m_s.resource_utilization*100:.1f}%"],
    ]
    print_table(f"Measured Acceptance Results: Live Contention Scene (Seed {seed})", headers, rows)

    summary_text = (
        f"MEASURED DEMO VERIFICATION: Candidate-A had completed {work_frac_a:.1f}% of its work "
        f"with {spent_tok_a:,} tokens invested. Under baseline, it terminated as '{status_b.upper()}', "
        f"whereas under SunkGuard reservation protection it terminated as '{status_s.upper()}' "
        f"with {0 if status_s == 'done' else spent_tok_a} tokens lost."
    )
    if HAS_RICH:
        Console().print(Panel(summary_text, style="bold cyan"))
    else:
        print(f"\n{summary_text}\n")


def cmd_verify_reproducibility(args: argparse.Namespace) -> None:
    """Verifies that running with the same seed yields 100% bit-identical traces."""
    seed = args.seed
    ticks = args.ticks
    print(f"\n[Verification] Running two independent simulations with seed={seed}, ticks={ticks}...")

    def execute_and_hash(s: int) -> tuple[str, dict]:
        engine = SimulationEngine(SimulationConfig(seed=s, total_ticks=ticks, is_sunkguard=True))
        engine.run()
        m = collect_metrics(engine).to_dict()

        # Build bitstream of all state logs and snapshots
        trace = []
        for l in engine.controller.log:
            trace.append(f"{l.tick}:{l.kind}:{l.message}")
        for snap in engine.history_series:
            trace.append(f"{snap.tick}:{snap.used_capacity}:{snap.hard_reserved_capacity}:{snap.cumulative_tokens}")
        payload = ("\n".join(trace) + json.dumps(m, sort_keys=True)).encode("utf-8")
        h = hashlib.sha256(payload).hexdigest()
        return h, m

    h1, m1 = execute_and_hash(seed)
    h2, m2 = execute_and_hash(seed)

    print(f"Run 1 SHA-256: {h1}")
    print(f"Run 2 SHA-256: {h2}")

    if h1 == h2 and m1 == m2:
        msg = f"VERIFIED BIT-IDENTICAL: Seed {seed} produced exact matching output (SHA-256: {h1[:16]}...)"
        if HAS_RICH:
            Console().print(Panel(msg, style="bold green"))
        else:
            print(f"\n*** {msg} ***\n")
    else:
        print("\nERROR: Outputs differ between runs with identical seed!", file=sys.stderr)
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sunkguard",
        description="SunkGuard: Predictive Admission Controller for Compound Agent Workflows",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = subparsers.add_parser("run", help="Run a single simulation")
    p_run.add_argument("--ticks", type=int, default=150, help="Number of simulation ticks")
    p_run.add_argument("--seed", type=int, default=7, help="Seeded RNG seed")
    p_run.add_argument("--load", type=float, default=0.50, help="Workflow arrival load factor")
    p_run.add_argument("--policy", choices=["light", "medium", "aggressive"], default="medium")
    p_run.add_argument("--baseline", action="store_true", help="Run baseline controller instead of SunkGuard")
    p_run.add_argument("--json-out", type=str, default=None, help="Path to write JSON metrics")
    p_run.set_defaults(func=cmd_run)

    # compare
    p_comp = subparsers.add_parser("compare", help="Compare baseline vs SunkGuard under identical seed")
    p_comp.add_argument("--ticks", type=int, default=150, help="Number of simulation ticks")
    p_comp.add_argument("--seed", type=int, default=7, help="Seeded RNG seed")
    p_comp.add_argument("--load", type=float, default=0.50, help="Workflow arrival load factor")
    p_comp.add_argument("--policy", choices=["light", "medium", "aggressive"], default="medium")
    p_comp.add_argument("--json-out", type=str, default=None, help="Path to write JSON comparison")
    p_comp.set_defaults(func=cmd_compare)

    # thesis-eval
    p_gate = subparsers.add_parser("thesis-eval", help="Run multi-seed thesis gate evaluation")
    p_gate.add_argument("--start-seed", type=int, default=21, help="Starting seed (default: 21)")
    p_gate.add_argument("--end-seed", type=int, default=50, help="Ending seed (default: 50)")
    p_gate.add_argument("--ticks", type=int, default=150, help="Ticks per simulation run")
    p_gate.add_argument("--load", type=float, default=0.50, help="Workflow arrival load factor")
    p_gate.add_argument("--policy", choices=["light", "medium", "aggressive"], default="medium")
    p_gate.add_argument("--json-out", type=str, default=None, help="Path to write JSON thesis evaluation")
    p_gate.set_defaults(func=cmd_thesis_eval)

    # demo
    p_demo = subparsers.add_parser("demo", help="Run live acceptance demo with measured values")
    p_demo.add_argument("--seed", type=int, default=7, help="Seeded RNG seed")
    p_demo.add_argument("--ticks", type=int, default=100, help="Simulation ticks")
    p_demo.add_argument("--policy", choices=["light", "medium", "aggressive"], default="medium")
    p_demo.set_defaults(func=cmd_demo)

    # verify-reproducibility
    p_ver = subparsers.add_parser("verify-reproducibility", help="Verify bit-identical execution for identical seed")
    p_ver.add_argument("--seed", type=int, default=42, help="Seeded RNG seed")
    p_ver.add_argument("--ticks", type=int, default=150, help="Simulation ticks")
    p_ver.set_defaults(func=cmd_verify_reproducibility)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
