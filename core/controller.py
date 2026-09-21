"""Admission controllers for compound agent workflows.

Implements:
1. BaselineController: Uncoordinated contention resolution (FIFO / random without reservations).
2. SunkGuardController: Predictive admission control with DeltaP_failure estimation,
   confidence-gated hard/soft reservations, TTL enforcement, aging queue, and divergence handling.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Set, Tuple

from core.resources import ResourceManager, ReservationKind
from core.rng import SeededRNG
from core.workflow import Workflow, Step

ControllerPolicy = Literal["light", "medium", "aggressive"]


@dataclass(frozen=True)
class PolicyConfig:
    name: ControllerPolicy
    horizon: int        # Lookahead horizon (steps)
    threshold: float    # Work completion fraction threshold for reservation eligibility
    weight: float       # Sunk work weight multiplier in priority calculation
    pat: int = 8        # Step wait patience limit before failure
    qpat: int = 28      # Initial admission wait patience limit before starvation
    ttl: int = 14       # Reservation time-to-live in ticks
    hard_cap: float = 0.80  # Max fraction of resource capacity allocatable to hard holds
    aging: float = 0.35 # Priority aging coefficient per wait tick


POLICIES: Dict[ControllerPolicy, PolicyConfig] = {
    "light": PolicyConfig(name="light", horizon=1, threshold=0.55, weight=0.6),
    "medium": PolicyConfig(name="medium", horizon=2, threshold=0.30, weight=1.2),
    "aggressive": PolicyConfig(name="aggressive", horizon=9, threshold=0.10, weight=2.4),
}


@dataclass
class Reservation:
    key: str            # "wf_id:resource_id"
    workflow_id: int
    resource_id: str
    units: int
    kind: ReservationKind
    ttl: int
    confidence: float


@dataclass
class ControllerLogEntry:
    tick: int
    message: str
    kind: Literal["ok", "warn", "bad", "rsv", "ttl"]


class BaseController(ABC):
    """Abstract interface for workflow admission and resource scheduling."""

    def __init__(self, rng: SeededRNG, policy: ControllerPolicy = "medium"):
        self.rng = rng
        self.policy_config = POLICIES[policy]
        self.log: List[ControllerLogEntry] = []

    def add_log(self, tick: int, message: str, kind: Literal["ok", "warn", "bad", "rsv", "ttl"] = "ok") -> None:
        self.log.append(ControllerLogEntry(tick=tick, message=message, kind=kind))
        if len(self.log) > 100:
            self.log.pop(0)

    @abstractmethod
    def plan(self, tick: int, active_workflows: List[Workflow], rm: ResourceManager) -> None:
        """Run periodic reservation / admission planning."""
        pass

    @abstractmethod
    def schedule(
        self,
        tick: int,
        candidates: List[Workflow],
        rm: ResourceManager,
        on_started: Optional[callable] = None,
        on_failed: Optional[callable] = None,
    ) -> None:
        """Dispatch resources to candidate waiting workflows."""
        pass

    @abstractmethod
    def handle_divergence(self, tick: int, workflow: Workflow, rm: ResourceManager) -> None:
        """Handle dynamic branch divergence / prediction mismatch."""
        pass

    @abstractmethod
    def on_workflow_terminal(self, workflow: Workflow, rm: ResourceManager) -> None:
        """Clean up state and reservations when a workflow finishes or terminates."""
        pass


class BaselineController(BaseController):
    """Uncoordinated FIFO/Random baseline scheduler without reservations or sunk-cost bias."""

    def plan(self, tick: int, active_workflows: List[Workflow], rm: ResourceManager) -> None:
        # Baseline performs no predictive planning or reservations
        pass

    def schedule(
        self,
        tick: int,
        candidates: List[Workflow],
        rm: ResourceManager,
        on_started: Optional[callable] = None,
        on_failed: Optional[callable] = None,
    ) -> None:
        cfg = self.policy_config
        # Randomized scheduling order among eligible pending workflows (seeded RNG)
        queue = list(candidates)
        self.rng.shuffle(queue)

        for wf in queue:
            step = wf.current_step
            if not step:
                continue
            res = rm.get(step.resource_id)

            if res.free_physical >= step.units:
                # Capacity available: allocate and start step
                res.allocate(step.units)
                wf.running_step = step
                wf.running_ticks_left = step.duration
                wf.state = "running"
                if wf.started_tick < 0:
                    wf.started_tick = tick
                    if on_started:
                        on_started(wf, tick)
            else:
                # Capacity unavailable: increment wait counter
                wf.wait_time += 1
                wf.total_wait_time += 1
                wf.state = "queued" if (wf.step_index == 0 and wf.started_tick < 0) else "waiting"

                # Check patience exhaustion
                if wf.step_index > 0 and wf.wait_time > cfg.pat:
                    wf.state = "failed"
                    self.add_log(tick, f"{wf.name} timed out waiting for {res.spec.name} (lost {wf.spent_tokens} tokens)", "bad")
                    if on_failed:
                        on_failed(wf, "failed")
                elif wf.step_index == 0 and wf.wait_time > cfg.qpat:
                    wf.state = "starved"
                    self.add_log(tick, f"{wf.name} timed out in admission queue", "bad")
                    if on_failed:
                        on_failed(wf, "starved")

    def handle_divergence(self, tick: int, workflow: Workflow, rm: ResourceManager) -> None:
        # Baseline does not track predictions
        workflow.has_diverged = True
        workflow.mismatch_tick = tick

    def on_workflow_terminal(self, workflow: Workflow, rm: ResourceManager) -> None:
        pass


class SunkGuardController(BaseController):
    """Predictive admission controller with DeltaP_failure estimation,

    confidence-gated hard/soft reservations, aging queue, and divergence handling.
    """

    def __init__(self, rng: SeededRNG, policy: ControllerPolicy = "medium"):
        super().__init__(rng, policy)
        self.reservations: List[Reservation] = []

    def _sync_resource_reservation_tallies(self, rm: ResourceManager) -> None:
        """Update aggregate reservation counters on all resources."""
        for r in rm.resources.values():
            r.hard_reserved = 0
            r.soft_reserved = 0
        for rsv in self.reservations:
            r = rm.get(rsv.resource_id)
            if rsv.kind == "hard":
                r.hard_reserved += rsv.units
            else:
                r.soft_reserved += rsv.units

    def estimate_delta_p_failure(
        self,
        workflow: Workflow,
        rm: ResourceManager,
        horizon: Optional[int] = None,
    ) -> Tuple[float, float, float]:
        """Calculates DeltaP_failure, S_no_rsv, and S_rsv according to SPEC.md Section 4.

        Returns (delta_p_failure, s_no_rsv, s_rsv).
        """
        h = horizon or self.policy_config.horizon
        rem_steps = workflow.remaining_predicted_steps(h)
        if not rem_steps:
            return 0.0, 1.0, 1.0

        c_w = workflow.predictor_confidence
        pat = self.policy_config.pat
        s_no_rsv = 1.0
        s_rsv = 1.0

        for s in rem_steps:
            r = rm.get(s.resource_id)
            # Instantaneous load: used + queue / capacity
            rho = (r.in_use + r.hard_reserved) / max(1, r.cap)
            # Hazard rate without reservation (bounded in [0.0, 1.0])
            buffer = 0.15
            hazard = min(1.0, max(0.0, (rho - 1.0 + buffer) / (pat / max(1, s.duration))))
            # Hazard with reservation
            hazard_rsv = (1.0 - c_w) * hazard

            s_no_rsv *= (1.0 - hazard)
            s_rsv *= (1.0 - hazard_rsv)

        delta_p = max(0.0, s_rsv - s_no_rsv)
        return delta_p, s_no_rsv, s_rsv

    def plan(self, tick: int, active_workflows: List[Workflow], rm: ResourceManager) -> None:
        """Periodic reservation management cycle:

        1. Decrement TTLs and expire aged reservations.
        2. Evaluate eligible workflows (work_done / total >= threshold).
        3. Allocate hard/soft reservations gated by confidence and capacity bounds.
        """
        cfg = self.policy_config
        wf_by_id = {w.id: w for w in active_workflows}

        # 1. TTL countdown and expiration
        retained_reservations: List[Reservation] = []
        for rsv in self.reservations:
            rsv.ttl -= 1
            wf = wf_by_id.get(rsv.workflow_id)
            if not wf:
                continue  # Workflow is gone
            if rsv.ttl <= 0:
                res = rm.get(rsv.resource_id)
                self.add_log(
                    tick,
                    f"TTL expired: released {rsv.units} units of {res.spec.name} held for {wf.name}",
                    "ttl",
                )
                wf.no_reservation_until = tick + 6
                continue
            retained_reservations.append(rsv)
        self.reservations = retained_reservations
        self._sync_resource_reservation_tallies(rm)

        # 2. Identify candidate workflows
        candidates: List[Workflow] = []
        for w in active_workflows:
            if w.is_terminal:
                continue
            if w.work_fraction_done >= cfg.threshold and tick >= w.no_reservation_until:
                if w.remaining_predicted_steps(cfg.horizon):
                    candidates.append(w)

        # Sort candidates by sunk value at risk density
        def value_key(wf: Workflow) -> float:
            rem = wf.remaining_predicted_steps(cfg.horizon)
            units = sum(s.units for s in rem) or 1
            return wf.spent_work / units

        candidates.sort(key=value_key, reverse=True)

        # 3. Formulate reservation requests
        wanted_keys: Set[str] = set()

        for w in candidates:
            # Update predictor confidence
            mismatch_penalty = 0.25 if (w.has_diverged and tick - w.mismatch_tick < 6) else 0.0
            base_conf = 0.58 + 0.13 * w.step_index + w.noise - mismatch_penalty
            w.predictor_confidence = max(0.30, min(0.97, base_conf))

            rem_steps = w.remaining_predicted_steps(cfg.horizon)
            # Max required units per resource across lookahead horizon
            per_resource_units: Dict[str, int] = {}
            for s in rem_steps:
                per_resource_units[s.resource_id] = max(
                    per_resource_units.get(s.resource_id, 0), s.units
                )

            for rid, units in per_resource_units.items():
                key = f"{w.id}:{rid}"
                res = rm.get(rid)

                # Determine reservation tier
                kind: Optional[ReservationKind] = None
                if w.predictor_confidence >= 0.80:
                    kind = "hard"
                elif w.predictor_confidence >= 0.50:
                    kind = "soft"

                if not kind:
                    continue

                # Enforce hard reservation capacity cap (default 80%)
                if kind == "hard":
                    other_hard = sum(
                        r.units for r in self.reservations
                        if r.resource_id == rid and r.kind == "hard" and r.key != key
                    )
                    cap_limit = int(res.cap * cfg.hard_cap)
                    if other_hard + units > cap_limit:
                        # Downgrade to soft reservation to avoid locking all capacity
                        kind = "soft"

                wanted_keys.add(key)
                existing = next((r for r in self.reservations if r.key == key), None)
                if existing:
                    existing.units = units
                    existing.kind = kind
                    existing.confidence = w.predictor_confidence
                else:
                    new_rsv = Reservation(
                        key=key,
                        workflow_id=w.id,
                        resource_id=rid,
                        units=units,
                        kind=kind,
                        ttl=cfg.ttl,
                        confidence=w.predictor_confidence,
                    )
                    self.reservations.append(new_rsv)
                    if not w.reservation_logged:
                        w.reservation_logged = True
                        h_desc = "remaining chain" if cfg.horizon >= 9 else f"next {cfg.horizon} step(s)"
                        self.add_log(
                            tick,
                            f"Protecting {w.name}: reserved {h_desc} ({kind}, {int(w.predictor_confidence * 100)}% conf)",
                            "rsv",
                        )

        # Drop reservations that are no longer wanted
        self.reservations = [r for r in self.reservations if r.key in wanted_keys]
        self._sync_resource_reservation_tallies(rm)

    def schedule(
        self,
        tick: int,
        candidates: List[Workflow],
        rm: ResourceManager,
        on_started: Optional[callable] = None,
        on_failed: Optional[callable] = None,
    ) -> None:
        """Aging priority queue scheduling."""
        cfg = self.policy_config

        # Calculate dynamic priority scores with aging
        for wf in candidates:
            aging_boost = wf.wait_time * cfg.aging
            sunk_boost = cfg.weight * (wf.spent_work / 1000.0)
            wf.score = wf.base_priority + aging_boost + sunk_boost

        # Sort by score descending
        queue = sorted(candidates, key=lambda w: w.score, reverse=True)

        for wf in queue:
            step = wf.current_step
            if not step:
                continue
            res = rm.get(step.resource_id)

            # Check if this workflow already holds a hard reservation on this resource
            holding_hard = sum(
                r.units for r in self.reservations
                if r.workflow_id == wf.id and r.resource_id == step.resource_id and r.kind == "hard"
            )

            if res.can_allocate(step.units, holding_hard_units=holding_hard):
                # Capacity available: allocate physical units
                res.allocate(step.units)
                wf.running_step = step
                wf.running_ticks_left = step.duration
                wf.state = "running"
                if wf.started_tick < 0:
                    wf.started_tick = tick
                    if on_started:
                        on_started(wf, tick)

                # Consume / release reservation for this step once running
                self.reservations = [
                    r for r in self.reservations
                    if not (r.workflow_id == wf.id and r.resource_id == step.resource_id)
                ]
                self._sync_resource_reservation_tallies(rm)
            else:
                wf.wait_time += 1
                wf.total_wait_time += 1
                wf.state = "queued" if (wf.step_index == 0 and wf.started_tick < 0) else "waiting"

                # Check patience expiration
                if wf.step_index > 0 and wf.wait_time > cfg.pat:
                    wf.state = "failed"
                    self.add_log(
                        tick,
                        f"{wf.name} failed at step {wf.step_index + 1}/{len(wf.steps)}, losing {wf.spent_tokens:,} tokens",
                        "bad",
                    )
                    self.on_workflow_terminal(wf, rm)
                    if on_failed:
                        on_failed(wf, "failed")
                elif wf.step_index == 0 and wf.wait_time > cfg.qpat:
                    wf.state = "starved"
                    self.add_log(tick, f"{wf.name} timed out in admission queue", "bad")
                    self.on_workflow_terminal(wf, rm)
                    if on_failed:
                        on_failed(wf, "starved")

    def handle_divergence(self, tick: int, workflow: Workflow, rm: ResourceManager) -> None:
        """Dynamic branch divergence: releases stale reservation and aligns prediction."""
        workflow.has_diverged = True
        workflow.mismatch_tick = tick

        actual_step = workflow.steps[workflow.divergence_step]
        predicted_step = workflow.pred_steps[workflow.divergence_step]

        # Release stale reservations for this workflow
        self.reservations = [r for r in self.reservations if r.workflow_id != workflow.id]
        self._sync_resource_reservation_tallies(rm)

        # Update prediction with actual trajectory
        workflow.pred_steps[workflow.divergence_step] = actual_step.copy()

        res_actual = rm.get(actual_step.resource_id)
        res_was = rm.get(predicted_step.resource_id)
        self.add_log(
            tick,
            f"{workflow.name} diverged: expected {res_was.spec.name}, got {res_actual.spec.name}. Released stale hold and re-predicted.",
            "warn",
        )

    def on_workflow_terminal(self, workflow: Workflow, rm: ResourceManager) -> None:
        """Release all reservations when workflow finishes or terminates."""
        self.reservations = [r for r in self.reservations if r.workflow_id != workflow.id]
        self._sync_resource_reservation_tallies(rm)
