"""SunkGuard @reserved decorator and context manager.

Provides seamless capacity reservation and automatic usage tracking for Python agent functions.
"""

from contextlib import contextmanager
import functools
import inspect
import time
from typing import Any, Callable, Dict, Optional

from sdk.client import SunkGuardClient

_DEFAULT_CLIENT: Optional[SunkGuardClient] = None


def get_default_client() -> SunkGuardClient:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = SunkGuardClient()
    return _DEFAULT_CLIENT


class StepReservationContext:
    """Context object passed to code executing under a reserved step."""

    def __init__(self, client: SunkGuardClient, workflow_id: str, step: str, resource_id: str, units: int):
        self.client = client
        self.workflow_id = workflow_id
        self.step = step
        self.resource_id = resource_id
        self.units = units
        self.usage: Dict[str, Any] = {}
        self.decision: str = "pending"

    def record_usage(self, total_tokens: Optional[int] = None, prompt_tokens: Optional[int] = None, completion_tokens: Optional[int] = None):
        if total_tokens is not None:
            self.usage["total_tokens"] = total_tokens
        if prompt_tokens is not None:
            self.usage["prompt_tokens"] = prompt_tokens
        if completion_tokens is not None:
            self.usage["completion_tokens"] = completion_tokens


@contextmanager
def reserved_step(
    workflow_id: str,
    step: str,
    resource_id: str = "gemini",
    units: int = 1,
    timeout: float = 10.0,
    client: Optional[SunkGuardClient] = None,
):
    """Context manager acquiring a SunkGuard reservation before entering the block."""
    c = client or get_default_client()
    ctx = StepReservationContext(c, workflow_id, step, resource_id, units)

    t0 = time.time()
    res = c.request_step(workflow_id, step, resource_id, units)
    ctx.decision = res.get("decision", "granted")

    # If queued, poll until granted or timeout
    while ctx.decision == "queued" and (time.time() - t0) < timeout:
        time.sleep(0.5)
        res = c.request_step(workflow_id, step, resource_id, units)
        ctx.decision = res.get("decision", "granted")

    try:
        yield ctx
    finally:
        # Report step completion and release capacity
        c.complete_step(workflow_id, step, usage=ctx.usage if ctx.usage else None)


def reserved(
    step_name: Optional[str] = None,
    resource_id: str = "gemini",
    units: int = 1,
    timeout: float = 10.0,
    client: Optional[SunkGuardClient] = None,
):
    """Decorator wrapping agent step functions with automatic SunkGuard admission and release."""
    def decorator(fn: Callable):
        actual_step = step_name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Extract workflow_id from kwargs, args, or self/cls
            wf_id = kwargs.get("workflow_id")
            if not wf_id:
                sig = inspect.signature(fn)
                bound = sig.bind_partial(*args, **kwargs)
                wf_id = bound.arguments.get("workflow_id")
            if not wf_id and args:
                # If first arg is a string starting with wf-
                if isinstance(args[0], str) and args[0].startswith("wf-"):
                    wf_id = args[0]
            if not wf_id:
                raise ValueError(f"Function '{fn.__name__}' wrapped with @reserved requires a 'workflow_id' argument.")

            with reserved_step(wf_id, actual_step, resource_id=resource_id, units=units, timeout=timeout, client=client) as ctx:
                result = fn(*args, **kwargs)

                # Automatically extract token usage if returned in result
                if hasattr(result, "total_tokens"):
                    ctx.record_usage(total_tokens=getattr(result, "total_tokens", 0))
                elif isinstance(result, dict) and "usage" in result:
                    u = result["usage"]
                    ctx.record_usage(
                        total_tokens=u.get("total_tokens"),
                        prompt_tokens=u.get("prompt_tokens"),
                        completion_tokens=u.get("completion_tokens"),
                    )
                elif isinstance(result, dict) and "total_tokens" in result:
                    ctx.record_usage(total_tokens=result["total_tokens"])

                return result

        return wrapper

    if callable(step_name):
        fn = step_name
        step_name = fn.__name__
        return decorator(fn)
    return decorator
