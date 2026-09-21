"""Workflow, Step, and Template models for SunkGuard core.

Implements Standard Work Units (SWU), token accounting, dynamic step prediction,
divergence modeling, and precise late failure classification (>= 50% work done).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from core.resources import DEFAULT_RESOURCE_SPECS, ResourceSpec

WorkflowState = Literal["queued", "running", "waiting", "done", "failed", "starved"]

_SPEC_MAP: Dict[str, ResourceSpec] = {s.id: s for s in DEFAULT_RESOURCE_SPECS}


@dataclass
class Step:
    """A single execution step in an agent workflow."""
    resource_id: str
    units: int
    duration: int  # in simulation ticks
    tokens: int    # model tokens consumed by this step
    work: int      # Standard Work Units (SWU)

    @classmethod
    def create(cls, resource_id: str, units: int, duration: int) -> "Step":
        spec = _SPEC_MAP.get(resource_id)
        if not spec:
            raise KeyError(f"Unknown resource ID: {resource_id}")
        # Only models consume direct tokens; all resources produce SWU
        tokens = (units * spec.swu_per_unit) if spec.is_model else 0
        work = units * spec.swu_per_unit
        return cls(
            resource_id=resource_id,
            units=units,
            duration=duration,
            tokens=tokens,
            work=work,
        )

    def copy(self) -> "Step":
        return Step(
            resource_id=self.resource_id,
            units=self.units,
            duration=self.duration,
            tokens=self.tokens,
            work=self.work,
        )


@dataclass(frozen=True)
class WorkflowTemplate:
    """Predefined compound agent workflow template."""
    id: str
    name: str
    short: str
    description: str
    # Raw steps: (resource_id, units, duration)
    raw_steps: List[tuple[str, int, int]]


DEFAULT_TEMPLATES: List[WorkflowTemplate] = [
    WorkflowTemplate(
        id="research",
        name="Market research brief",
        short="Research",
        description="Searches the web, drafts a brief, then reviews it.",
        raw_steps=[("search", 2, 3), ("pro", 4, 4), ("flash", 2, 3), ("pro", 3, 4)],
    ),
    WorkflowTemplate(
        id="codefix",
        name="Code fix agent",
        short="Code fix",
        description="Pulls context, proposes a fix, and runs the tests.",
        raw_steps=[("vdb", 2, 2), ("pro", 3, 4), ("code", 2, 3), ("code", 2, 3), ("flash", 2, 2)],
    ),
    WorkflowTemplate(
        id="support",
        name="Support resolution",
        short="Support",
        description="Answers a ticket and updates the customer record.",
        raw_steps=[("vdb", 1, 2), ("flash", 2, 3), ("crm", 2, 2), ("flash", 1, 2)],
    ),
    WorkflowTemplate(
        id="lead",
        name="Lead qualification",
        short="Lead",
        description="Scores inbound leads and routes them to sales.",
        raw_steps=[("crm", 2, 2), ("flash", 2, 3), ("pro", 2, 3), ("crm", 1, 2)],
    ),
    WorkflowTemplate(
        id="digest",
        name="Data digest",
        short="Digest",
        description="Builds a daily digest from live company data.",
        raw_steps=[("search", 2, 3), ("vdb", 2, 2), ("pro", 5, 5), ("flash", 2, 3)],
    ),
]

TEMPLATE_MAP: Dict[str, WorkflowTemplate] = {t.id: t for t in DEFAULT_TEMPLATES}


@dataclass
class Workflow:
    """Stateful instance of an executing compound agent workflow."""
    id: int
    template_id: str
    template_name: str
    name: str
    steps: List[Step]
    pred_steps: List[Step]
    divergence_step: int = -1  # Step index where execution diverges from prediction (-1 if none)
    has_diverged: bool = False
    mismatch_tick: int = -1

    step_index: int = 0
    state: WorkflowState = "queued"
    wait_time: int = 0         # Ticks spent waiting on the current step
    total_wait_time: int = 0   # Cumulative ticks spent waiting
    age: int = 0               # Total ticks since arrival

    base_priority: float = 1.0
    score: float = 1.0         # Dynamic admission score

    spent_tokens: int = 0      # Model tokens consumed so far by finished steps
    spent_work: int = 0        # SWU completed so far by finished steps
    total_planned_work: int = 0
    total_planned_tokens: int = 0

    running_ticks_left: int = 0
    running_step: Optional[Step] = None

    predictor_confidence: float = 0.50
    noise: float = 0.0

    born_tick: int = 0
    step_requested_tick: int = 0
    started_tick: int = -1
    end_tick: int = -1

    observed_history: List[Dict[str, Any]] = field(default_factory=list)

    no_reservation_until: int = 0
    backoff_until: int = 0
    retry_attempts: int = 0
    reservation_logged: bool = False
    demo_tag: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.state in ("done", "failed", "starved")

    @property
    def work_fraction_done(self) -> float:
        """Fraction of total planned work completed so far in [0.0, 1.0]."""
        if self.total_planned_work <= 0:
            return 0.0
        return self.spent_work / self.total_planned_work

    @property
    def is_late_failure(self) -> bool:
        """Strict definition: failed with >= 50% work done (SPEC.md Section 3)."""
        return self.state == "failed" and self.work_fraction_done >= 0.50

    @property
    def is_early_failure(self) -> bool:
        """Failed with > 0% but < 50% work done."""
        return self.state == "failed" and (0.0 < self.work_fraction_done < 0.50)

    @property
    def is_starved(self) -> bool:
        """Dropped in admission queue before step 0 ran."""
        return self.state == "starved"

    @property
    def current_step(self) -> Optional[Step]:
        if self.step_index < len(self.steps):
            return self.steps[self.step_index]
        return None

    def remaining_predicted_steps(self, horizon: int) -> List[Step]:
        """Lookahead slice of predicted steps for reservation planning."""
        start = self.step_index + (1 if self.running_step else 0)
        end = min(len(self.pred_steps), start + horizon)
        if start >= len(self.pred_steps):
            return []
        return self.pred_steps[start:end]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "name": self.name,
            "state": self.state,
            "step_index": self.step_index,
            "total_steps": len(self.steps),
            "spent_tokens": self.spent_tokens,
            "spent_work": self.spent_work,
            "total_work": self.total_planned_work,
            "work_fraction": round(self.work_fraction_done, 3),
            "wait_time": self.wait_time,
            "score": round(self.score, 2),
            "confidence": round(self.predictor_confidence, 2),
            "is_late_failure": self.is_late_failure,
            "born_tick": self.born_tick,
            "started_tick": self.started_tick,
            "end_tick": self.end_tick,
        }
