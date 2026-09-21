"""Canonical data models and controller loop specifications for SunkGuard.

Strictly adheres to the SunkGuard Execution Guide / Engineering Specification:
1. Canonical workflow states: CREATED, QUEUED, RUNNING, WAITING, COMPLETED, FAILED.
2. Canonical event types: WORKFLOW_CREATED, WORKFLOW_STARTED, WORKFLOW_QUEUED,
   STEP_REQUESTED, STEP_GRANTED, STEP_STARTED, STEP_COMPLETED, STEP_FAILED,
   RESOURCE_RESERVED, RESOURCE_RELEASED, RESERVATION_EXPIRED, PREDICTION_UPDATED,
   PREDICTION_MISMATCH, WORKFLOW_COMPLETED, WORKFLOW_FAILED.
3. EWMA trackers for tokens, API calls, and step durations.
4. Decision records capturing explainability inputs (work-at-risk, Delta P_fail, PV).
5. Configurable policy modes: Light, Medium, Aggressive.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Literal, Optional, Tuple


class CanonicalWorkflowState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CanonicalEventType(str, Enum):
    WORKFLOW_CREATED = "WORKFLOW_CREATED"
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    WORKFLOW_QUEUED = "WORKFLOW_QUEUED"
    STEP_REQUESTED = "STEP_REQUESTED"
    STEP_GRANTED = "STEP_GRANTED"
    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_FAILED = "STEP_FAILED"
    RESOURCE_RESERVED = "RESOURCE_RESERVED"
    RESOURCE_RELEASED = "RESOURCE_RELEASED"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
    PREDICTION_UPDATED = "PREDICTION_UPDATED"
    PREDICTION_MISMATCH = "PREDICTION_MISMATCH"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"


class ReservationKind(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    NONE = "NONE"


class PolicyMode(str, Enum):
    LIGHT = "Light"
    MEDIUM = "Medium"
    AGGRESSIVE = "Aggressive"


@dataclass
class EWMATracker:
    """Exponentially Weighted Moving Average tracker for duration and token consumption.
    
    Formula: EWMA_t = alpha * observed_t + (1 - alpha) * EWMA_(t-1)
    """
    alpha: float = 0.30
    estimates: Dict[str, float] = field(default_factory=dict)

    def update(self, key: str, observed: float) -> float:
        if key not in self.estimates:
            self.estimates[key] = float(observed)
        else:
            self.estimates[key] = (self.alpha * observed) + ((1.0 - self.alpha) * self.estimates[key])
        return self.estimates[key]

    def get(self, key: str, default: float = 0.0) -> float:
        return self.estimates.get(key, default)


@dataclass
class DecisionRecord:
    """Canonical explainability record for admission & reservation decisions."""
    workflow_id: str
    decision: Literal["granted", "queued", "reserved", "rejected", "released"]
    work_at_risk: float
    predicted_chain: List[str]
    predicted_resource_demand: str
    confidence: float
    p_fail_without: float
    p_fail_with: float
    delta_p_fail: float
    protection_value: float
    reservation_type: ReservationKind
    final_reason: str
    created_at_tick: int
    normalized_capacity_cost: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "decision": self.decision,
            "work_at_risk": round(self.work_at_risk, 2),
            "predicted_chain": self.predicted_chain,
            "predicted_resource_demand": self.predicted_resource_demand,
            "confidence": round(self.confidence, 4),
            "p_fail_without": round(self.p_fail_without, 4),
            "p_fail_with": round(self.p_fail_with, 4),
            "delta_p_fail": round(self.delta_p_fail, 4),
            "protection_value": round(self.protection_value, 2),
            "reservation_type": self.reservation_type.value,
            "final_reason": self.final_reason,
            "created_at_tick": self.created_at_tick,
            "normalized_capacity_cost": round(self.normalized_capacity_cost, 2),
        }


@dataclass
class CanonicalEvent:
    """Structured event log entry adhering to the specification."""
    id: str
    event_type: CanonicalEventType
    title: str
    detail: str
    tick: int
    timestamp_str: str
    workflow_id: Optional[str] = None
    resource_id: Optional[str] = None
    payload: Optional[str] = None
    category: str = "System"
    ui_type: Literal["success", "info", "warning", "danger"] = "info"

    def to_frontend_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.ui_type,
            "title": self.title,
            "detail": self.detail,
            "timestamp": self.timestamp_str,
            "category": self.category,
            "workflowId": self.workflow_id,
            "resource": self.resource_id,
            "payload": self.payload,
        }


@dataclass
class PolicyDefinition:
    """Canonical policy configuration mapping to the Engineering Specification."""
    mode: PolicyMode
    description: str
    reservation_ceiling: int      # Hard cap percentage (e.g. 70%)
    aging_rate: float             # Aging factor per tick
    confidence_threshold: float   # Minimum confidence for HARD reservation (>= 0.80)
    soft_threshold: float         # Minimum confidence for SOFT reservation (>= 0.50)
    prediction_horizon: int       # Lookahead horizon in steps
    risk_weight: float            # Multiplier for work-at-risk
    chain_depth_label: str

    def to_frontend_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "reservationCeiling": self.reservation_ceiling,
            "agingRate": round(self.aging_rate, 2),
            "confidenceThreshold": round(self.confidence_threshold, 2),
            "softThreshold": round(self.soft_threshold, 2),
            "predictionHorizon": self.prediction_horizon,
            "chainDepth": self.chain_depth_label,
            "riskWeight": round(self.risk_weight, 2),
        }


CANONICAL_POLICIES: Dict[PolicyMode, PolicyDefinition] = {
    PolicyMode.LIGHT: PolicyDefinition(
        mode=PolicyMode.LIGHT,
        description="Keep fresh work moving while protecting only the next high-confidence step.",
        reservation_ceiling=70,
        aging_rate=0.35,
        confidence_threshold=0.85,
        soft_threshold=0.55,
        prediction_horizon=2,
        risk_weight=1.0,
        chain_depth_label="Next step",
    ),
    PolicyMode.MEDIUM: PolicyDefinition(
        mode=PolicyMode.MEDIUM,
        description="Balance late-stage protection with queue freshness and bounded wait time.",
        reservation_ceiling=70,
        aging_rate=0.35,
        confidence_threshold=0.80,
        soft_threshold=0.50,
        prediction_horizon=4,
        risk_weight=1.4,
        chain_depth_label="Remaining chain",
    ),
    PolicyMode.AGGRESSIVE: PolicyDefinition(
        mode=PolicyMode.AGGRESSIVE,
        description="Protect the highest work-at-risk paths deeper into their predicted chain.",
        reservation_ceiling=80,
        aging_rate=0.35,
        confidence_threshold=0.75,
        soft_threshold=0.45,
        prediction_horizon=6,
        risk_weight=2.0,
        chain_depth_label="Full chain + margin",
    ),
}
