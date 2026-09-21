"""Discrete event simulation engine for SunkGuard core.

Runs a synchronous, simulated clock (t = 0, 1, 2, ...) with a single seeded RNG.
Strictly adheres to:
- No wall-clock usage (time.time() / datetime.now() forbidden)
- No unseeded random
- No asyncio
- Guaranteed bit-identical reproducibility for identical seeds.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from core.controller import (
    BaseController,
    BaselineController,
    ControllerLogEntry,
    ControllerPolicy,
    ControllerVariant,
    SunkGuardController,
)
from core.predictor import NonOraclePredictor
from core.resources import DEFAULT_RESOURCE_SPECS, ResourceManager, ResourceSpec
from core.rng import SeededRNG
from core.workflow import (
    DEFAULT_TEMPLATES,
    Step,
    TEMPLATE_MAP,
    Workflow,
    WorkflowState,
    WorkflowTemplate,
)


@dataclass
class SimulationConfig:
    """Simulation run parameters."""
    seed: int = 7
    total_ticks: int = 200
    load_factor: float = 0.50
    policy: ControllerPolicy = "medium"
    variant: ControllerVariant = "full_sunkguard"
    is_sunkguard: bool = True
    predictor: Optional[NonOraclePredictor] = None
    resource_specs: Optional[List[ResourceSpec]] = None
    templates: Optional[List[WorkflowTemplate]] = None
    beta_pv: float = 1.0


@dataclass
class TimeSeriesSnapshot:
    """Per-tick telemetry snapshot."""
    tick: int
    active_count: int
    running_count: int
    waiting_count: int
    used_capacity: int
    hard_reserved_capacity: int
    soft_reserved_capacity: int
    free_capacity: int
    tokens_this_tick: int
    cumulative_tokens: int
    cumulative_wasted_tokens: int
    cumulative_wasted_work: int


class SimulationEngine:
    """Synchronous, deterministic discrete event simulation engine."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.rng = SeededRNG(config.seed)
        self.rm = ResourceManager(config.resource_specs or DEFAULT_RESOURCE_SPECS)
        self.templates = config.templates or DEFAULT_TEMPLATES
        self.tpl_map = {t.id: t for t in self.templates}

        # Initialize controller
        if config.is_sunkguard:
            self.controller: BaseController = SunkGuardController(
                rng=self.rng,
                policy=config.policy,
                variant=config.variant,
                predictor=config.predictor,
                beta_pv=config.beta_pv,
            )
        else:
            self.controller = BaselineController(
                rng=self.rng,
                policy=config.policy,
                variant=config.variant,
            )

        # Simulation clock and state
        self.tick_count: int = 0
        self.next_workflow_id: int = 0
        self.active_workflows: List[Workflow] = []
        self.completed_workflows: List[Workflow] = []
        self.failed_workflows: List[Workflow] = []
        self.starved_workflows: List[Workflow] = []

        # Aggregate metrics
        self.total_tokens_consumed: int = 0
        self.total_tokens_wasted: int = 0
        self.total_work_executed: int = 0
        self.total_work_wasted: int = 0

        # Detailed step counters for late failures
        self.late_failed_count: int = 0
        self.early_failed_count: int = 0

        # Predictor accuracy tracking
        self.total_predictions_made: int = 0
        self.correct_predictions_count: int = 0

        # Durations and latency tracking
        self.completion_durations: List[int] = []
        self.initial_admission_waits: List[int] = []

        # Time-averaged capacity counters
        self.cumulative_used_capacity: int = 0
        self.cumulative_hard_reserved: int = 0
        self.cumulative_soft_reserved: int = 0

        # Tokens breakdown
        self.tokens_by_resource: Dict[str, int] = {s.id: 0 for s in self.rm.specs.values()}
        self.tokens_by_template: Dict[str, int] = {t.id: 0 for t in self.templates}

        # Time series history
        self.history_series: List[TimeSeriesSnapshot] = []

    @property
    def current_tick(self) -> int:
        return self.tick_count

    def _create_workflow_from_template(
        self,
        template: WorkflowTemplate,
        base_priority: float,
        divergence_step: int,
        noise: float,
        name_override: Optional[str] = None,
        custom_steps: Optional[List[Tuple[str, int, int]]] = None,
        demo_tag: str = "",
    ) -> Workflow:
        self.next_workflow_id += 1
        wf_id = self.next_workflow_id

        raw = custom_steps or template.raw_steps
        steps = [Step.create(rid, u, d) for rid, u, d in raw]
        pred_steps = [s.copy() for s in steps]

        # Apply divergence to predicted step if requested
        if 1 <= divergence_step < len(steps):
            cur_r = steps[divergence_step].resource_id
            # Alternate resource substitution
            alt_r = (
                "flash" if cur_r == "pro" else
                "pro" if cur_r == "flash" else
                "vdb" if cur_r == "search" else "search"
            )
            pred_steps[divergence_step] = Step.create(
                alt_r, steps[divergence_step].units, steps[divergence_step].duration
            )

        name = name_override or f"{template.short} #{wf_id}"
        total_work = sum(s.work for s in steps)
        total_tokens = sum(s.tokens for s in steps)

        return Workflow(
            id=wf_id,
            template_id=template.id,
            template_name=template.name,
            name=name,
            steps=steps,
            pred_steps=pred_steps,
            divergence_step=divergence_step,
            has_diverged=False,
            step_index=0,
            state="queued",
            base_priority=base_priority,
            score=base_priority,
            total_planned_work=total_work,
            total_planned_tokens=total_tokens,
            noise=noise,
            born_tick=self.tick_count,
            step_requested_tick=self.tick_count,
            demo_tag=demo_tag,
        )

    def _spawn_arrival(self) -> Optional[Workflow]:
        """Poisson / Bernoulli arrival process driven strictly by seeded RNG."""
        if self.rng.random() > self.config.load_factor:
            return None

        tpl_idx = self.rng.randrange(0, len(self.templates))
        tpl = self.templates[tpl_idx]
        num_steps = len(tpl.raw_steps)

        base_pri = 1.0 + self.rng.randrange(0, 3)
        # 16% probability of dynamic divergence at some step > 0
        divergence_step = (
            self.rng.randrange(1, num_steps)
            if (num_steps > 1 and self.rng.random() < 0.16)
            else -1
        )
        noise = (self.rng.random() - 0.5) * 0.16

        return self._create_workflow_from_template(
            template=tpl,
            base_priority=base_pri,
            divergence_step=divergence_step,
            noise=noise,
        )

    def _on_workflow_started(self, workflow: Workflow, tick: int) -> None:
        """Callback when workflow transitions from queued to running step 0."""
        wait_time = tick - workflow.born_tick
        self.initial_admission_waits.append(wait_time)

    def _on_workflow_terminal(self, workflow: Workflow, outcome: WorkflowState) -> None:
        """Process terminal state transition."""
        workflow.state = outcome
        workflow.end_tick = self.tick_count
        self.controller.on_workflow_terminal(workflow, self.rm)

        if outcome == "done":
            self.completed_workflows.append(workflow)
            self.completion_durations.append(self.tick_count - workflow.born_tick)
            # Track predictor hits for completed workflows
            self.total_predictions_made += len(workflow.steps)
            if workflow.has_diverged:
                self.correct_predictions_count += max(0, len(workflow.steps) - 1)
            else:
                self.correct_predictions_count += len(workflow.steps)

        elif outcome == "failed":
            self.failed_workflows.append(workflow)
            self.total_tokens_wasted += workflow.spent_tokens
            self.total_work_wasted += workflow.spent_work
            if workflow.is_late_failure:
                self.late_failed_count += 1
            else:
                self.early_failed_count += 1

        elif outcome == "starved":
            self.starved_workflows.append(workflow)
            # Starved in admission queue: 0 spent tokens/work

    def inject_demo_scene(self) -> Tuple[Workflow, List[Workflow]]:
        """Injects the benchmark late-stage vs new-run contention scenario.

        Creates:
        1. A nearly finished workflow (e.g. Data Digest at step 3 of 4, 87% work done).
        2. A burst of 6 newly arrived heavy workflows competing for the same resource.
        All work fractions, tokens, and outcomes are live-measured.
        """
        # 1. Nearly finished workflow
        digest_tpl = self.tpl_map["digest"]
        wf_a = self._create_workflow_from_template(
            template=digest_tpl,
            base_priority=1.0,
            divergence_step=-1,
            noise=0.0,
            name_override=f"Candidate-A (Late Stage #{self.next_workflow_id + 1})",
            demo_tag="candidate_a",
        )
        # Fast-forward wf_a through steps 0, 1, 2
        wf_a.step_index = 3
        for i in range(3):
            st = wf_a.steps[i]
            wf_a.spent_tokens += st.tokens
            wf_a.spent_work += st.work
            wf_a.observed_history.append({
                "resource_id": st.resource_id,
                "units": st.units,
                "duration": st.duration,
                "work": st.work,
                "tokens": st.tokens,
            })
            self.total_tokens_consumed += st.tokens
            self.total_work_executed += st.work
            if st.resource_id in self.tokens_by_resource:
                self.tokens_by_resource[st.resource_id] += st.tokens

        wf_a.state = "waiting"
        wf_a.started_tick = max(0, self.tick_count - 10)
        wf_a.born_tick = max(0, self.tick_count - 14)
        self.active_workflows.append(wf_a)

        # 2. Six heavy newly arrived runs demanding Flash
        burst_wfs: List[Workflow] = []
        for i in range(1, 7):
            wf_b = self._create_workflow_from_template(
                template=self.tpl_map["support"],
                base_priority=3.0,
                divergence_step=-1,
                noise=0.0,
                name_override=f"NewRun-B{i} (Burst)",
                custom_steps=[("flash", 13, 9)],
                demo_tag="burst_b",
            )
            self.active_workflows.append(wf_b)
            burst_wfs.append(wf_b)

        self.controller.add_log(
            self.tick_count,
            f"Injected contention scene: 1 late-stage run ({round(wf_a.work_fraction_done * 100, 1)}% done, {wf_a.spent_tokens:,} tokens) vs 6 heavy new runs",
            "warn",
        )
        return wf_a, burst_wfs

    def step(self) -> None:
        """Advance the simulation by exactly one integer tick."""
        self.tick_count += 1
        tick = self.tick_count
        tokens_this_tick = 0

        # 1. Arrival of new workflows
        new_wf = self._spawn_arrival()
        if new_wf:
            self.active_workflows.append(new_wf)

        # 2. Advance currently running steps
        for wf in self.active_workflows:
            wf.age += 1
            if wf.running_step:
                wf.running_ticks_left -= 1
                if wf.running_ticks_left <= 0:
                    # Completed running step
                    step = wf.running_step
                    res = self.rm.get(step.resource_id)
                    res.release(step.units)

                    wf.spent_tokens += step.tokens
                    wf.spent_work += step.work
                    wf.observed_history.append({
                        "resource_id": step.resource_id,
                        "units": step.units,
                        "duration": step.duration,
                        "work": step.work,
                        "tokens": step.tokens,
                    })
                    tokens_this_tick += step.tokens
                    self.total_tokens_consumed += step.tokens
                    self.total_work_executed += step.work

                    if step.resource_id in self.tokens_by_resource:
                        self.tokens_by_resource[step.resource_id] += step.tokens
                    self.tokens_by_template[wf.template_id] = (
                        self.tokens_by_template.get(wf.template_id, 0) + step.tokens
                    )

                    wf.step_index += 1
                    wf.running_step = None
                    wf.running_ticks_left = 0
                    wf.wait_time = 0
                    wf.state = "waiting"
                    wf.step_requested_tick = tick
                    wf.backoff_until = 0
                    wf.retry_attempts = 0

                    if wf.step_index >= len(wf.steps):
                        self._on_workflow_terminal(wf, "done")
                    else:
                        # Check for branch divergence
                        if (
                            self.config.is_sunkguard
                            and wf.step_index == wf.divergence_step
                            and not wf.has_diverged
                        ):
                            self.controller.handle_divergence(tick, wf, self.rm)

        # 3. Controller Planning cycle
        if self.config.is_sunkguard:
            self.controller.plan(tick, self.active_workflows, self.rm)

        # 4. Resource Allocation / Dispatch cycle
        eligible_candidates = [
            w for w in self.active_workflows
            if not w.running_step and not w.is_terminal
        ]
        self.controller.schedule(
            tick=tick,
            candidates=eligible_candidates,
            rm=self.rm,
            on_started=self._on_workflow_started,
            on_failed=self._on_workflow_terminal,
        )

        # 5. Aggregate instantaneous capacity metrics
        tot_cap = self.rm.total_capacity()
        tot_in_use = self.rm.total_in_use()
        tot_hard_rsv = self.rm.total_hard_reserved()
        tot_soft_rsv = self.rm.total_soft_reserved()

        self.cumulative_used_capacity += tot_in_use
        self.cumulative_hard_reserved += tot_hard_rsv
        self.cumulative_soft_reserved += tot_soft_rsv

        # 6. Record telemetry snapshot
        running_cnt = sum(1 for w in self.active_workflows if w.state == "running")
        waiting_cnt = sum(1 for w in self.active_workflows if w.state in ("waiting", "queued"))

        snapshot = TimeSeriesSnapshot(
            tick=tick,
            active_count=len(self.active_workflows),
            running_count=running_cnt,
            waiting_count=waiting_cnt,
            used_capacity=tot_in_use,
            hard_reserved_capacity=tot_hard_rsv,
            soft_reserved_capacity=tot_soft_rsv,
            free_capacity=max(0, tot_cap - tot_in_use - tot_hard_rsv),
            tokens_this_tick=tokens_this_tick,
            cumulative_tokens=self.total_tokens_consumed,
            cumulative_wasted_tokens=self.total_tokens_wasted,
            cumulative_wasted_work=self.total_work_wasted,
        )
        self.history_series.append(snapshot)
        if len(self.history_series) > 300:
            self.history_series.pop(0)

        # 7. Prune terminal workflows from active list
        self.active_workflows = [w for w in self.active_workflows if not w.is_terminal]

    def run(self, ticks: Optional[int] = None) -> None:
        """Run the simulation for a given or configured number of ticks."""
        total = ticks if ticks is not None else self.config.total_ticks
        for _ in range(total):
            self.step()
