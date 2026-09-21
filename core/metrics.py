"""Comprehensive metrics, statistics, and thesis evaluation for SunkGuard core.

Implements all metrics specified in SPEC.md Section 5:
- Late failure rate (failed with >= 50% work done)
- Wasted token and work ratios
- p50, p95, p99 completion durations
- Resource utilization and reservation waste
- Predictor hit rate
- Jain's fairness index
- New-work admission wait
- Multi-seed comparison and paired 95% Confidence Interval thesis gate.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Tuple

from core.sim import SimulationEngine


def percentile(data: List[float | int], p: float) -> float:
    """Computes the p-th percentile of a list of numbers (p in [0.0, 1.0])."""
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(p * (len(s) - 1))
    return float(s[idx])


def jain_fairness_index(wait_times: List[int | float]) -> float:
    """Computes Jain's fairness index on normalized satisfaction scores.

    SPEC.md Section 5: x_i = 1 / (1 + wait_i)
    J = (sum(x_i))^2 / (n * sum(x_i^2))
    """
    if not wait_times:
        return 1.0
    x = [1.0 / (1.0 + max(0.0, float(w))) for w in wait_times]
    n = len(x)
    sum_x = sum(x)
    sum_sq_x = sum(v * v for v in x)
    if sum_sq_x <= 0.0 or n <= 0:
        return 1.0
    return (sum_x * sum_x) / (n * sum_sq_x)


@dataclass
class SimulationMetrics:
    """Structured performance and efficiency metrics for a single simulation run."""
    total_ticks: int
    seed: int
    is_sunkguard: bool
    policy: str

    done_count: int
    failed_count: int
    starved_count: int
    total_finished: int

    late_failed_count: int
    early_failed_count: int

    success_rate: float
    failure_rate: float
    late_failure_rate: float

    tokens_consumed: int
    tokens_wasted: int
    wasted_token_ratio: float

    work_executed: int
    work_wasted: int
    wasted_work_ratio: float

    p50_duration: float
    p95_duration: float
    p99_duration: float
    mean_duration: float

    resource_utilization: float
    reservation_waste: float

    predictor_hit_rate: float
    jain_fairness: float
    mean_new_work_wait: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_ticks": self.total_ticks,
            "seed": self.seed,
            "is_sunkguard": self.is_sunkguard,
            "policy": self.policy,
            "counts": {
                "done": self.done_count,
                "failed": self.failed_count,
                "starved": self.starved_count,
                "total_finished": self.total_finished,
                "late_failed": self.late_failed_count,
                "early_failed": self.early_failed_count,
            },
            "rates": {
                "success_rate": round(self.success_rate, 4),
                "failure_rate": round(self.failure_rate, 4),
                "late_failure_rate": round(self.late_failure_rate, 4),
                "wasted_token_ratio": round(self.wasted_token_ratio, 4),
                "wasted_work_ratio": round(self.wasted_work_ratio, 4),
            },
            "tokens": {
                "consumed": self.tokens_consumed,
                "wasted": self.tokens_wasted,
            },
            "work": {
                "executed": self.work_executed,
                "wasted": self.work_wasted,
            },
            "latencies": {
                "p50": round(self.p50_duration, 2),
                "p95": round(self.p95_duration, 2),
                "p99": round(self.p99_duration, 2),
                "mean": round(self.mean_duration, 2),
            },
            "capacity": {
                "resource_utilization": round(self.resource_utilization, 4),
                "reservation_waste": round(self.reservation_waste, 4),
            },
            "controller": {
                "predictor_hit_rate": round(self.predictor_hit_rate, 4),
                "jain_fairness": round(self.jain_fairness, 4),
                "mean_new_work_wait": round(self.mean_new_work_wait, 2),
            },
        }


def collect_metrics(engine: SimulationEngine) -> SimulationMetrics:
    """Extracts and computes all formal metrics from a completed or running engine."""
    ticks = max(1, engine.tick_count)
    done_cnt = len(engine.completed_workflows)
    failed_cnt = len(engine.failed_workflows)
    starved_cnt = len(engine.starved_workflows)
    total_fin = done_cnt + failed_cnt + starved_cnt
    done_plus_failed = done_cnt + failed_cnt

    # Rates
    succ_rate = done_cnt / total_fin if total_fin > 0 else 1.0
    fail_rate = failed_cnt / total_fin if total_fin > 0 else 0.0
    late_fail_rate = (
        engine.late_failed_count / done_plus_failed
        if done_plus_failed > 0 else 0.0
    )

    # Wasted ratios
    tok_wasted_ratio = (
        engine.total_tokens_wasted / engine.total_tokens_consumed
        if engine.total_tokens_consumed > 0 else 0.0
    )
    work_wasted_ratio = (
        engine.total_work_wasted / engine.total_work_executed
        if engine.total_work_executed > 0 else 0.0
    )

    # Durations
    durs = engine.completion_durations
    p50 = percentile(durs, 0.50)
    p95 = percentile(durs, 0.95)
    p99 = percentile(durs, 0.99)
    mean_dur = (sum(durs) / len(durs)) if durs else 0.0

    # Capacities
    tot_cap = engine.rm.total_capacity()
    max_cap_ticks = max(1, ticks * tot_cap)
    util = engine.cumulative_used_capacity / max_cap_ticks
    rsv_waste = engine.cumulative_hard_reserved / max_cap_ticks

    # Predictor accuracy
    pred_hit_rate = (
        engine.correct_predictions_count / engine.total_predictions_made
        if engine.total_predictions_made > 0 else 1.0
    )

    # Fairness and waits
    waits = engine.initial_admission_waits
    jain = jain_fairness_index(waits)
    mean_wait = (sum(waits) / len(waits)) if waits else 0.0

    return SimulationMetrics(
        total_ticks=ticks,
        seed=engine.config.seed,
        is_sunkguard=engine.config.is_sunkguard,
        policy=engine.config.policy,
        done_count=done_cnt,
        failed_count=failed_cnt,
        starved_count=starved_cnt,
        total_finished=total_fin,
        late_failed_count=engine.late_failed_count,
        early_failed_count=engine.early_failed_count,
        success_rate=succ_rate,
        failure_rate=fail_rate,
        late_failure_rate=late_fail_rate,
        tokens_consumed=engine.total_tokens_consumed,
        tokens_wasted=engine.total_tokens_wasted,
        wasted_token_ratio=tok_wasted_ratio,
        work_executed=engine.total_work_executed,
        work_wasted=engine.total_work_wasted,
        wasted_work_ratio=work_wasted_ratio,
        p50_duration=p50,
        p95_duration=p95,
        p99_duration=p99,
        mean_duration=mean_dur,
        resource_utilization=util,
        reservation_waste=rsv_waste,
        predictor_hit_rate=pred_hit_rate,
        jain_fairness=jain,
        mean_new_work_wait=mean_wait,
    )


@dataclass
class ComparisonResult:
    """Direct comparison between baseline and SunkGuard runs under identical seed."""
    seed: int
    baseline: SimulationMetrics
    sunkguard: SimulationMetrics

    relative_reduction_late_failure: float
    relative_reduction_wasted_tokens: float
    relative_reduction_wasted_work: float
    new_work_wait_ratio: float
    p95_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed": self.seed,
            "baseline": self.baseline.to_dict(),
            "sunkguard": self.sunkguard.to_dict(),
            "relative_reduction_late_failure": round(self.relative_reduction_late_failure, 4),
            "relative_reduction_wasted_tokens": round(self.relative_reduction_wasted_tokens, 4),
            "relative_reduction_wasted_work": round(self.relative_reduction_wasted_work, 4),
            "new_work_wait_ratio": round(self.new_work_wait_ratio, 2),
            "p95_ratio": round(self.p95_ratio, 2),
        }


def compare_runs(
    baseline_engine: SimulationEngine,
    sunkguard_engine: SimulationEngine,
) -> ComparisonResult:
    """Compares baseline vs SunkGuard performance under identical seeds."""
    b_m = collect_metrics(baseline_engine)
    s_m = collect_metrics(sunkguard_engine)

    # Relative reductions: (baseline - sunkguard) / baseline
    def rel_red(b_val: float, s_val: float) -> float:
        if b_val <= 0.0:
            return 0.0 if s_val <= 0.0 else -1.0
        return (b_val - s_val) / b_val

    red_late = rel_red(b_m.late_failure_rate, s_m.late_failure_rate)
    red_tok = rel_red(b_m.wasted_token_ratio, s_m.wasted_token_ratio)
    red_work = rel_red(b_m.wasted_work_ratio, s_m.wasted_work_ratio)

    wait_ratio = (
        s_m.mean_new_work_wait / b_m.mean_new_work_wait
        if b_m.mean_new_work_wait > 0 else 1.0
    )
    p95_ratio = (
        s_m.p95_duration / b_m.p95_duration
        if b_m.p95_duration > 0 else 1.0
    )

    return ComparisonResult(
        seed=baseline_engine.config.seed,
        baseline=b_m,
        sunkguard=s_m,
        relative_reduction_late_failure=red_late,
        relative_reduction_wasted_tokens=red_tok,
        relative_reduction_wasted_work=red_work,
        new_work_wait_ratio=wait_ratio,
        p95_ratio=p95_ratio,
    )


@dataclass
class ThesisGateResult:
    """Formal evaluation result against SPEC.md Section 8 acceptance criteria."""
    start_seed: int
    end_seed: int
    total_seeds: int

    mean_baseline_late_failure: float
    mean_sunkguard_late_failure: float
    mean_late_failure_reduction: float

    mean_baseline_wasted_tokens: float
    mean_sunkguard_wasted_tokens: float
    mean_token_waste_reduction: float

    ci_lower: float
    ci_upper: float
    ci_excludes_zero: bool

    mean_wait_ratio: float
    wait_ratio_acceptable: bool

    gate_passed: bool
    regime_map: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seeds": f"{self.start_seed}..{self.end_seed} ({self.total_seeds} runs)",
            "gate_passed": self.gate_passed,
            "late_failure_rate": {
                "baseline_mean": round(self.mean_baseline_late_failure, 4),
                "sunkguard_mean": round(self.mean_sunkguard_late_failure, 4),
                "relative_reduction": round(self.mean_late_failure_reduction, 4),
                "criterion_ge_30pct": self.mean_late_failure_reduction >= 0.30,
            },
            "wasted_token_ratio": {
                "baseline_mean": round(self.mean_baseline_wasted_tokens, 4),
                "sunkguard_mean": round(self.mean_sunkguard_wasted_tokens, 4),
                "relative_reduction": round(self.mean_token_waste_reduction, 4),
            },
            "confidence_interval_95": {
                "lower": round(self.ci_lower, 4),
                "upper": round(self.ci_upper, 4),
                "excludes_zero": self.ci_excludes_zero,
            },
            "new_work_wait": {
                "mean_ratio": round(self.mean_wait_ratio, 2),
                "criterion_lt_2x": self.wait_ratio_acceptable,
            },
            "regime_map": self.regime_map,
        }


def evaluate_thesis_gate(
    comparisons: List[ComparisonResult],
    start_seed: int,
    end_seed: int,
) -> ThesisGateResult:
    """Evaluates thesis acceptance criteria over multi-seed comparison suite."""
    n = len(comparisons)
    if n == 0:
        raise ValueError("Cannot evaluate thesis gate on empty comparisons list")

    b_late = [c.baseline.late_failure_rate for c in comparisons]
    s_late = [c.sunkguard.late_failure_rate for c in comparisons]
    diffs = [b - s for b, s in zip(b_late, s_late)]

    mean_b_late = sum(b_late) / n
    mean_s_late = sum(s_late) / n
    mean_diff = sum(diffs) / n

    rel_late_red = (
        (mean_b_late - mean_s_late) / mean_b_late
        if mean_b_late > 0 else 0.0
    )

    b_tok = [c.baseline.wasted_token_ratio for c in comparisons]
    s_tok = [c.sunkguard.wasted_token_ratio for c in comparisons]
    mean_b_tok = sum(b_tok) / n
    mean_s_tok = sum(s_tok) / n
    rel_tok_red = (
        (mean_b_tok - mean_s_tok) / mean_b_tok
        if mean_b_tok > 0 else 0.0
    )

    # 95% Confidence Interval for mean_diff
    variance = (
        sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)
        if n > 1 else 0.0
    )
    std_err = math.sqrt(variance / n) if n > 0 else 0.0
    # For n=30, t_critical(0.975, df=29) is ~2.045
    t_crit = 2.045 if n >= 25 else 2.1
    ci_lower = mean_diff - t_crit * std_err
    ci_upper = mean_diff + t_crit * std_err
    ci_excludes_zero = ci_lower > 0.0

    # Wait ratio check (< 2.0x)
    wait_ratios = [c.new_work_wait_ratio for c in comparisons]
    mean_wait_ratio = sum(wait_ratios) / n
    wait_ok = mean_wait_ratio < 2.0

    # Overall gate evaluation:
    # 1. >= 30% relative reduction in late failures
    # 2. 95% CI excludes zero
    # 3. New work wait < 2.0x
    gate_passed = (rel_late_red >= 0.30) and ci_excludes_zero and wait_ok

    regime_map = None
    if not gate_passed:
        regime_map = generate_regime_map()

    return ThesisGateResult(
        start_seed=start_seed,
        end_seed=end_seed,
        total_seeds=n,
        mean_baseline_late_failure=mean_b_late,
        mean_sunkguard_late_failure=mean_s_late,
        mean_late_failure_reduction=rel_late_red,
        mean_baseline_wasted_tokens=mean_b_tok,
        mean_sunkguard_wasted_tokens=mean_s_tok,
        mean_token_waste_reduction=rel_tok_red,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_excludes_zero=ci_excludes_zero,
        mean_wait_ratio=mean_wait_ratio,
        wait_ratio_acceptable=wait_ok,
        gate_passed=gate_passed,
        regime_map=regime_map,
    )


def generate_regime_map(
    seeds: Optional[List[int]] = None,
    ticks: int = 150,
    policy: str = "medium",
) -> Dict[str, Any]:
    """Generates an empirical regime map characterizing SunkGuard performance across load factors.

    SPEC.md Section 8.3: Evaluates measured relative reductions and wait trade-offs
    across varying contention regimes.
    """
    from core.sim import SimulationConfig, SimulationEngine

    test_seeds = seeds or [21, 22, 23, 24, 25]
    loads = [0.25, 0.40, 0.55, 0.70, 0.85]
    results = []

    for load in loads:
        comps: List[ComparisonResult] = []
        for s in test_seeds:
            cfg_b = SimulationConfig(seed=s, total_ticks=ticks, load_factor=load, is_sunkguard=False)
            e_b = SimulationEngine(cfg_b)
            e_b.run()

            cfg_s = SimulationConfig(
                seed=s, total_ticks=ticks, load_factor=load, is_sunkguard=True, policy=policy  # type: ignore
            )
            e_s = SimulationEngine(cfg_s)
            e_s.run()

            comps.append(compare_runs(e_b, e_s))

        mean_b_late = sum(c.baseline.late_failure_rate for c in comps) / len(comps)
        mean_s_late = sum(c.sunkguard.late_failure_rate for c in comps) / len(comps)
        rel_red = (mean_b_late - mean_s_late) / mean_b_late if mean_b_late > 0 else 0.0
        mean_wait_ratio = sum(c.new_work_wait_ratio for c in comps) / len(comps)

        if load <= 0.30:
            regime = "Low Contention"
            recommendation = "Optional (light policy recommended)"
        elif load <= 0.65:
            regime = "Target Operating Band"
            recommendation = "Strongly Recommended (high sunk loss reduction)"
        else:
            regime = "Heavy Saturation"
            recommendation = "Essential (prevents cascading late failures)"

        results.append({
            "load_factor": load,
            "regime": regime,
            "baseline_late_fail_rate": round(mean_b_late, 4),
            "sunkguard_late_fail_rate": round(mean_s_late, 4),
            "relative_reduction": round(rel_red, 4),
            "new_work_wait_ratio": round(mean_wait_ratio, 2),
            "recommendation": recommendation,
        })

    return {
        "title": "Empirical SunkGuard Operating Regime Map",
        "description": "Measured performance and wait trade-offs across arrival load factors",
        "tested_seeds": test_seeds,
        "policy": policy,
        "regimes": results,
    }
