"""Regime Test Environment: Windowed TPM Token Bucket & Non-Preemptible Bottleneck Steps.

Pre-registered in SPEC.md Section 11:
- Fixed time window: W_size = 20 ticks
- Token budget per window: B_window = 8,000 tokens (refills at t % 20 == 0 with NO carry-over)
- Non-preemptible bottleneck steps: d = 8 ticks, consuming 2,500 tokens
- Branching DAG transitions per template
- Evaluated on loads [0.50, 0.70, 0.85] across held-out seeds 301-400
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from core.resources import DEFAULT_RESOURCE_SPECS, ResourceManager, ResourceSpec, ResourceState
from core.workflow import Step, Workflow, WorkflowTemplate
from core.controller import BaseController, BaselineController, SunkGuardController
from core.predictor import NonOraclePredictor


WINDOW_SIZE = 20
WINDOW_TOKEN_BUDGET = 8000
BOTTLENECK_DURATION = 8
BOTTLENECK_TOKENS = 2500

# Regime resource specifications (Gemini Pro cap=6 to create severe contention under 8-tick duration)
REGIME_RESOURCE_SPECS: List[ResourceSpec] = [
    ResourceSpec(id="pro", name="Gemini Pro", short="Pro", kind="Model", cap=6, swu_per_unit=625),
    ResourceSpec(id="flash", name="Gemini Flash", short="Flash", kind="Model", cap=10, swu_per_unit=250),
    ResourceSpec(id="search", name="Web Search", short="Search", kind="Tool", cap=4, swu_per_unit=400),
    ResourceSpec(id="code", name="Code Runner", short="Code", kind="Tool", cap=3, swu_per_unit=300),
    ResourceSpec(id="vdb", name="Vector DB", short="Vector DB", kind="Service", cap=4, swu_per_unit=300),
]


@dataclass
class WindowedTokenBucket:
    """Per-window token-rate-limit resource (TPM bucket refilling per window)."""
    window_size: int = WINDOW_SIZE
    budget_per_window: int = WINDOW_TOKEN_BUDGET
    tokens_consumed_current_window: int = 0
    current_window_idx: int = 0
    # Future window reservations: window_idx -> reserved_tokens
    future_window_reservations: Dict[int, int] = field(default_factory=dict)

    def on_tick(self, tick: int) -> None:
        new_window = tick // self.window_size
        if new_window > self.current_window_idx:
            self.current_window_idx = new_window
            self.tokens_consumed_current_window = 0
            # Clean up past window reservations
            self.future_window_reservations = {
                w: r for w, r in self.future_window_reservations.items() if w >= new_window
            }

    @property
    def free_tokens_current_window(self) -> int:
        return max(0, self.budget_per_window - self.tokens_consumed_current_window)

    def can_consume(self, tokens: int, window_idx: Optional[int] = None) -> bool:
        w = self.current_window_idx if window_idx is None else window_idx
        if w == self.current_window_idx:
            return (self.tokens_consumed_current_window + tokens) <= self.budget_per_window
        else:
            rsv = self.future_window_reservations.get(w, 0)
            return (rsv + tokens) <= self.budget_per_window

    def consume(self, tokens: int) -> None:
        self.tokens_consumed_current_window += tokens

    def reserve_window(self, window_idx: int, tokens: int) -> bool:
        current_rsv = self.future_window_reservations.get(window_idx, 0)
        if current_rsv + tokens <= self.budget_per_window:
            self.future_window_reservations[window_idx] = current_rsv + tokens
            return True
        return False

    def release_window_reservation(self, window_idx: int, tokens: int) -> None:
        if window_idx in self.future_window_reservations:
            self.future_window_reservations[window_idx] = max(
                0, self.future_window_reservations[window_idx] - tokens
            )


# Branching DAG workflow templates with 8-tick non-preemptible bottleneck steps
REGIME_TEMPLATES = [
    # Template 1: Heavy Deep Synthesis
    WorkflowTemplate(
        id="regime_deep_synth",
        name="Deep Analysis & Synthesis",
        short="DeepSynth",
        description="Multi-stage agent pipeline with heavy bottleneck reasoning step.",
        raw_steps=[
            ("flash", 2, 2),  # step 0: inquiry & search (500 tokens)
            ("pro", 4, BOTTLENECK_DURATION),  # step 1: non-preemptible long bottleneck (2500 tokens)
            ("pro", 2, 3),    # step 2: executive synthesis (1250 tokens)
        ],
    ),
    # Template 2: Code Incident Resolution
    WorkflowTemplate(
        id="regime_incident_fix",
        name="Incident Root Cause Analysis",
        short="IncidentFix",
        description="Diagnostic workflow with deep model debugging step.",
        raw_steps=[
            ("flash", 2, 2),  # step 0: parse logs (500 tokens)
            ("pro", 4, BOTTLENECK_DURATION),  # step 1: non-preemptible long bottleneck (2500 tokens)
            ("flash", 2, 2),  # step 2: verification (500 tokens)
        ],
    ),
    # Template 3: Multi-Agent Briefing
    WorkflowTemplate(
        id="regime_agent_brief",
        name="Executive Strategic Brief",
        short="ExecBrief",
        description="Data extraction followed by long model evaluation.",
        raw_steps=[
            ("search", 2, 2), # step 0: tool search
            ("flash", 2, 2),  # step 1: context filter (500 tokens)
            ("pro", 4, BOTTLENECK_DURATION),  # step 2: non-preemptible long bottleneck (2500 tokens)
            ("flash", 2, 2),  # step 3: summary (500 tokens)
        ],
    ),
]


class RegimeSimulationEngine:
    """Simulation engine for SPEC Section 11 Regime Test with windowed token rate limit."""

    def __init__(
        self,
        seed: int,
        load_factor: float = 0.50,
        total_ticks: int = 200,
        variant: str = "admission_only",
        policy: str = "medium",
        headroom_factor: float = 1.0,
    ):
        from core.sim import SeededRNG
        self.seed = seed
        self.load_factor = load_factor
        self.total_ticks = total_ticks
        self.variant = variant
        self.policy = policy
        self.headroom_factor = headroom_factor

        self.rng = SeededRNG(seed)
        self.tpm_bucket = WindowedTokenBucket()
        self.rm = ResourceManager(specs=REGIME_RESOURCE_SPECS)
        self.templates = REGIME_TEMPLATES
        self.tpl_map = {t.id: t for t in self.templates}

        # Predictor
        from core.predictor import NonOraclePredictor
        self.predictor = NonOraclePredictor(ewma_alpha=0.30, drift_rate=0.05)

        # Workflows
        self.active_workflows: List[Workflow] = []
        self.completed_workflows: List[Workflow] = []
        self.failed_workflows: List[Workflow] = []
        self.starved_workflows: List[Workflow] = []
        self.next_workflow_id: int = 0
        self.tick_count: int = 0

        # Accounting
        self.total_tokens_consumed: int = 0
        self.total_tokens_wasted: int = 0
        self.completed_tokens: int = 0  # Goodput
        self.initial_admission_waits: List[int] = []

    def _create_workflow(self, template_id: str) -> Workflow:
        tpl = self.tpl_map[template_id]
        steps: List[Step] = []
        total_work = 0
        for rid, units, dur in tpl.raw_steps:
            # For pro bottleneck steps: exactly BOTTLENECK_TOKENS (2500)
            st = Step.create(rid, units, dur)
            if rid == "pro" and dur == BOTTLENECK_DURATION:
                st.tokens = BOTTLENECK_TOKENS
            steps.append(st)
            total_work += st.work

        wf = Workflow(
            id=self.next_workflow_id,
            template_id=tpl.id,
            template_name=tpl.name,
            name=f"{tpl.short}-{self.next_workflow_id}",
            steps=steps,
            pred_steps=[s.copy() for s in steps],
            base_priority=self.rng.uniform(1.0, 3.0),
            born_tick=self.tick_count,
            step_requested_tick=self.tick_count,
        )
        wf.total_estimated_work = total_work
        self.next_workflow_id += 1
        return wf

    def _spawn_arrival(self) -> Optional[Workflow]:
        # Poisson arrival according to load factor
        p = self.load_factor * 0.28
        if self.rng.random() < p:
            tid = self.rng.choice([t.id for t in self.templates])
            return self._create_workflow(tid)
        return None

    def run(self, pat: int = 16, qpat: int = 40) -> Dict[str, Any]:

        for tick in range(1, self.total_ticks + 1):
            self.tick_count = tick
            self.tpm_bucket.on_tick(tick)

            # 1. New arrival
            arr = self._spawn_arrival()
            if arr:
                self.active_workflows.append(arr)

            # 2. Advance running steps (non-preemptible execution)
            for wf in list(self.active_workflows):
                wf.age += 1
                if wf.running_step:
                    wf.running_ticks_left -= 1
                    if wf.running_ticks_left <= 0:
                        # Step complete
                        step = wf.running_step
                        res = self.rm.get(step.resource_id)
                        res.release(step.units)

                        wf.spent_tokens += step.tokens
                        wf.spent_work += step.work
                        self.total_tokens_consumed += step.tokens

                        wf.step_index += 1
                        wf.running_step = None
                        wf.running_ticks_left = 0
                        wf.wait_time = 0
                        wf.state = "waiting"
                        wf.step_requested_tick = tick

                        if wf.step_index >= len(wf.steps):
                            # Completed workflow
                            wf.state = "done"
                            self.completed_workflows.append(wf)
                            self.active_workflows.remove(wf)
                            self.completed_tokens += wf.spent_tokens

            # 3. Schedule waiting/queued candidates
            candidates = [w for w in self.active_workflows if w.running_step is None]

            # Priority sorting by variant
            if self.variant == "baseline":
                queue = list(candidates)
                self.rng.shuffle(queue)
            elif self.variant == "baseline_backoff":
                queue = [w for w in candidates if w.backoff_until <= tick]
                self.rng.shuffle(queue)
            elif self.variant == "oldest_first":
                queue = sorted(candidates, key=lambda w: (w.born_tick, w.id))
            elif self.variant == "fifo_request":
                queue = sorted(candidates, key=lambda w: (w.step_requested_tick, w.id))
            elif self.variant == "admission_only":
                # Progress weighting + aging: score = base_priority + beta * spent_work + wait_time * aging
                for w in candidates:
                    w.score = w.base_priority + 0.35 * w.spent_work + (w.wait_time * 0.16)
                queue = sorted(candidates, key=lambda w: (w.score, -w.born_tick, -w.id), reverse=True)
            elif self.variant == "admission_pv":
                # Protection value: W_done / (eps + C_rem)
                for w in candidates:
                    c_rem = max(1, w.total_estimated_work - w.spent_work)
                    pv = w.spent_work / (100.0 + c_rem)
                    w.score = w.base_priority + 40.0 * pv + (w.wait_time * 0.16)
                queue = sorted(candidates, key=lambda w: (w.score, -w.born_tick, -w.id), reverse=True)
            elif self.variant == "admission_headroom":
                # Only admit new workflows (step 0) if remaining window tokens >= headroom_factor * 2500
                headroom_needed = int(self.headroom_factor * BOTTLENECK_TOKENS)
                eligible = []
                for w in candidates:
                    if w.step_index == 0:
                        if self.tpm_bucket.free_tokens_current_window >= headroom_needed:
                            eligible.append(w)
                        else:
                            w.wait_time += 1
                            w.total_wait_time += 1
                    else:
                        eligible.append(w)
                queue = sorted(eligible, key=lambda w: (w.born_tick, w.id))
            elif self.variant in ("full_sunkguard", "full"):
                # Window-indexed advance reservations:
                # In-flight workflows (step_index > 0) reserve token budget in target windows
                self.tpm_bucket.future_window_reservations.clear()
                for w in self.active_workflows:
                    if w.step_index > 0 and not w.is_terminal:
                        for s_idx in range(w.step_index, len(w.steps)):
                            s = w.steps[s_idx]
                            if s.tokens > 0:
                                est_delay = sum(w.steps[i].duration for i in range(w.step_index, s_idx))
                                target_win = (tick + est_delay) // WINDOW_SIZE
                                self.tpm_bucket.reserve_window(target_win, min(s.tokens, 5600))
                                break

                # Score with progress weighting and aging
                for w in candidates:
                    w.score = w.base_priority + 0.60 * w.spent_work + (w.wait_time * 0.16)
                queue = sorted(candidates, key=lambda w: (w.score, -w.born_tick, -w.id), reverse=True)
            else:
                queue = list(candidates)

            # Dispatch loop
            for wf in queue:
                step = wf.current_step
                if not step:
                    continue
                res = self.rm.get(step.resource_id)

                # Check physical unit capacity
                has_units = res.free_physical >= step.units
                
                # Check window token rate limit
                has_tokens = True
                if step.tokens > 0:
                    if self.variant in ("full_sunkguard", "full") and wf.step_index == 0:
                        # New workflows cannot consume tokens reserved for in-flight work
                        reserved_in_cur = self.tpm_bucket.future_window_reservations.get(self.tpm_bucket.current_window_idx, 0)
                        unreserved_tokens = max(0, self.tpm_bucket.free_tokens_current_window - reserved_in_cur)
                        has_tokens = unreserved_tokens >= step.tokens
                    else:
                        has_tokens = self.tpm_bucket.can_consume(step.tokens)

                if has_units and has_tokens:
                    # Allocate physical units and consume window tokens
                    res.allocate(step.units)
                    if step.tokens > 0:
                        self.tpm_bucket.consume(step.tokens)

                    wf.running_step = step
                    wf.running_ticks_left = step.duration
                    wf.state = "running"
                    if wf.started_tick < 0:
                        wf.started_tick = tick
                        self.initial_admission_waits.append(tick - wf.born_tick)
                else:
                    wf.wait_time += 1
                    wf.total_wait_time += 1
                    wf.state = "queued" if (wf.step_index == 0 and wf.started_tick < 0) else "waiting"

                    if self.variant == "baseline_backoff":
                        wf.retry_attempts += 1
                        base_delay = min(8, 2 ** min(wf.retry_attempts, 3))
                        rem = max(0, (pat if wf.step_index > 0 else qpat) - wf.wait_time)
                        jitter = min(self.rng.randrange(0, base_delay + 1), rem)
                        wf.backoff_until = tick + jitter

                    # Check patience exhaustion
                    if wf.step_index > 0 and wf.wait_time > pat:
                        wf.state = "failed"
                        self.failed_workflows.append(wf)
                        self.active_workflows.remove(wf)
                        self.total_tokens_wasted += wf.spent_tokens
                    elif wf.step_index == 0 and wf.wait_time > qpat:
                        wf.state = "starved"
                        self.starved_workflows.append(wf)
                        self.active_workflows.remove(wf)

        # Terminal accounting
        for w in self.active_workflows:
            # Active workflows incomplete at simulation end
            pass

        tot_tokens = self.total_tokens_consumed + self.total_tokens_wasted
        wasted_ratio = (self.total_tokens_wasted / tot_tokens) if tot_tokens > 0 else 0.0
        tot_term = len(self.completed_workflows) + len(self.failed_workflows) + len(self.starved_workflows)
        fail_rate = (len(self.failed_workflows) + len(self.starved_workflows)) / max(1, tot_term)
        late_fail_count = sum(1 for w in self.failed_workflows if w.work_fraction_done >= 0.50)
        late_fail_rate = late_fail_count / max(1, tot_term)
        mean_wait = (sum(self.initial_admission_waits) / len(self.initial_admission_waits)) if self.initial_admission_waits else 0.0

        return {
            "wasted_token_ratio": wasted_ratio,
            "overall_failure_rate": fail_rate,
            "late_failure_rate": late_fail_rate,
            "late_failed_count": late_fail_count,
            "completed_runs": len(self.completed_workflows),
            "goodput_completed_tokens": self.completed_tokens,
            "total_tokens_wasted": self.total_tokens_wasted,
            "total_tokens_consumed": self.total_tokens_consumed,
            "mean_new_work_wait_ticks": mean_wait,
        }
