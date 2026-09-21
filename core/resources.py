"""Resource definitions and capacity tracking for SunkGuard core.

Models heterogeneous compute (LLMs, tools, external services) under concurrency
and rate limits with support for active in-use tracking, hard/soft reservations,
and standard work unit (SWU) conversions.
"""

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

ResourceKind = Literal["Model", "Tool", "Service"]
ReservationKind = Literal["hard", "soft"]


@dataclass(frozen=True)
class ResourceSpec:
    """Static definition and capacity parameters of a resource."""
    id: str
    name: str
    short: str
    kind: ResourceKind
    cap: int
    swu_per_unit: int  # Standard Work Units (token-equivalents) per unit

    @property
    def is_model(self) -> bool:
        return self.kind == "Model"


# Standard resource registry matching SPEC.md Section 2.2
DEFAULT_RESOURCE_SPECS: List[ResourceSpec] = [
    ResourceSpec(id="pro", name="Gemini Pro", short="Pro", kind="Model", cap=7, swu_per_unit=1600),
    ResourceSpec(id="flash", name="Gemini Flash", short="Flash", kind="Model", cap=14, swu_per_unit=700),
    ResourceSpec(id="search", name="Web Search", short="Search", kind="Tool", cap=4, swu_per_unit=400),
    ResourceSpec(id="code", name="Code Runner", short="Code", kind="Tool", cap=3, swu_per_unit=300),
    ResourceSpec(id="vdb", name="Vector DB", short="Vector DB", kind="Service", cap=5, swu_per_unit=300),
    ResourceSpec(id="crm", name="CRM API", short="CRM", kind="Service", cap=3, swu_per_unit=300),
]


class ResourceState:
    """Dynamic utilization and reservation state of a single resource."""

    def __init__(self, spec: ResourceSpec):
        self.spec = spec
        self.in_use: int = 0
        self.hard_reserved: int = 0
        self.soft_reserved: int = 0

    @property
    def cap(self) -> int:
        return self.spec.cap

    @property
    def free_unreserved(self) -> int:
        """Units that are neither currently in use nor committed to hard holds."""
        return max(0, self.cap - self.in_use - self.hard_reserved)

    @property
    def free_physical(self) -> int:
        """Raw physical units not actively executing right now."""
        return max(0, self.cap - self.in_use)

    def can_allocate(self, units: int, holding_hard_units: int = 0) -> bool:
        """Check if `units` can be scheduled right now.

        If the requesting workflow holds `holding_hard_units`, those units are
        already counted in `self.hard_reserved`, so they can be consumed.
        """
        # Capacity blocked by OTHER workflows' hard reservations
        other_hard = max(0, self.hard_reserved - holding_hard_units)
        return (self.cap - self.in_use - other_hard) >= units

    def allocate(self, units: int) -> None:
        """Mark `units` as actively running."""
        if self.in_use + units > self.cap:
            raise ValueError(
                f"Cannot allocate {units} units on {self.spec.id}: "
                f"in_use ({self.in_use}) + units > cap ({self.cap})"
            )
        self.in_use += units

    def release(self, units: int) -> None:
        """Release `units` after step completion or cancellation."""
        self.in_use = max(0, self.in_use - units)

    def to_dict(self) -> dict:
        return {
            "id": self.spec.id,
            "name": self.spec.name,
            "short": self.spec.short,
            "kind": self.spec.kind,
            "cap": self.spec.cap,
            "in_use": self.in_use,
            "hard_reserved": self.hard_reserved,
            "soft_reserved": self.soft_reserved,
            "free": self.free_unreserved,
        }


class ResourceManager:
    """Manages the full pool of resources, their state, and reservation tallies."""

    def __init__(self, specs: Optional[List[ResourceSpec]] = None):
        specs = specs or DEFAULT_RESOURCE_SPECS
        self.specs: Dict[str, ResourceSpec] = {s.id: s for s in specs}
        self.resources: Dict[str, ResourceState] = {s.id: ResourceState(s) for s in specs}

    def reset(self) -> None:
        """Reset all in-use and reservation counters."""
        for r in self.resources.values():
            r.in_use = 0
            r.hard_reserved = 0
            r.soft_reserved = 0

    def get(self, resource_id: str) -> ResourceState:
        if resource_id not in self.resources:
            raise KeyError(f"Unknown resource ID: {resource_id}")
        return self.resources[resource_id]

    def total_capacity(self) -> int:
        return sum(r.cap for r in self.resources.values())

    def total_in_use(self) -> int:
        return sum(r.in_use for r in self.resources.values())

    def total_hard_reserved(self) -> int:
        return sum(r.hard_reserved for r in self.resources.values())

    def total_soft_reserved(self) -> int:
        return sum(r.soft_reserved for r in self.resources.values())

    def to_dict(self) -> Dict[str, dict]:
        return {rid: r.to_dict() for rid, r in self.resources.items()}
