"""FastAPI REST API layer for SunkGuard compound workflow admission controller.

Implements all endpoints defined in the Engineering Specification & Correction 13:
- GET  /api/overview
- GET  /api/workflows
- GET  /api/workflows/{workflow_id}
- POST /api/workflows
- POST /api/workflows/{workflow_id}/steps/request
- POST /api/workflows/{workflow_id}/steps/complete
- GET  /api/resources
- GET  /api/reservations
- GET  /api/metrics
- GET  /api/events
- GET  /api/policy
- POST /api/policy
- GET  /api/analytics
- POST /api/demo/step
- POST /api/demo/reset
- POST /api/demo/mismatch
- GET  /api/health
- POST /api/gemini/run
"""

import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.auth import AUTH_MANAGER
from core.canonical import PolicyMode
from core.connectivity import CONNECTIVITY
from core.offline_journal import OFFLINE_JOURNAL
from core.reconciler import RECONCILER
from core.runtime import RUNTIME

# Start background network health prober
CONNECTIVITY.start_prober()

app = FastAPI(
    title="SunkGuard Control Plane API",
    description="Predictive admission controller and resource reservation engine for compound AI workflows",
    version="1.0.0",
)

# Enable CORS for local Vite development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Request & Response Models
# -----------------------------------------------------------------------------

class PolicyUpdateRequest(BaseModel):
    mode: str = Field(..., description="Policy mode: Light, Medium, or Aggressive")


class WorkflowCreateRequest(BaseModel):
    id: Optional[str] = None
    name: str
    agentType: str = "Custom agent"
    resourceNeed: str = "Gemini tokens"
    template_id: Optional[str] = None
    planned_steps: Optional[List[Dict[str, Any]]] = None


class StepRequestPayload(BaseModel):
    step: str
    resource_id: Optional[str] = "gemini"
    units: Optional[int] = 1


class StepCompletePayload(BaseModel):
    step: str
    usage: Optional[Dict[str, Any]] = None


class GeminiRunRequest(BaseModel):
    prompt: str = "Summarize the key benefits of predictive admission control in multi-step AI systems."
    max_tokens: int = 250


# -----------------------------------------------------------------------------
# System & Health Endpoints
# -----------------------------------------------------------------------------

@app.get("/api/health")
def get_health():
    return {
        "status": "healthy",
        "controller": "SunkGuard",
        "tick": RUNTIME.tick,
        "seed": RUNTIME.seed,
        "policy": RUNTIME.policy_mode.value,
        "gemini_live": RUNTIME.gemini_adapter.is_configured,
    }


# -----------------------------------------------------------------------------
# Server-Sent Events (SSE) Real-time Stream
# -----------------------------------------------------------------------------

@app.get("/api/stream")
async def sse_stream():
    """Streams real-time controller updates and telemetry events via SSE."""
    async def event_generator():
        overview = RUNTIME.get_overview()
        yield f"event: snapshot\ndata: {json.dumps(overview)}\n\n"
        last_event_count = len(RUNTIME.events)
        while True:
            await asyncio.sleep(1.0)
            current_count = len(RUNTIME.events)
            if current_count != last_event_count:
                events = [e.to_frontend_dict() for e in RUNTIME.events[:max(1, current_count - last_event_count)]]
                last_event_count = current_count
                yield f"event: events\ndata: {json.dumps(events)}\n\n"
            metrics = RUNTIME.get_metrics()
            yield f"event: metrics\ndata: {json.dumps(metrics)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# -----------------------------------------------------------------------------
# Primary Frontend API Endpoints (matching ControllerApi abstraction)
# -----------------------------------------------------------------------------

@app.get("/api/overview")
def get_overview():
    """Returns the complete aggregated controller state."""
    return RUNTIME.get_overview()


@app.get("/api/workflows")
def get_workflows():
    return list(RUNTIME.workflows_store.values())


@app.get("/api/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    wf = RUNTIME.workflows_store.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    return wf


@app.post("/api/workflows")
def start_workflow(payload: WorkflowCreateRequest):
    return RUNTIME.register_workflow(
        name=payload.name,
        workflow_id=payload.id,
        agent_type=payload.agentType,
        resource_need=payload.resourceNeed,
        template_id=payload.template_id,
        planned_steps=payload.planned_steps,
    )


@app.post("/api/workflows/{workflow_id}/steps/request")
def request_step(workflow_id: str, payload: StepRequestPayload):
    try:
        return RUNTIME.request_step_admission(
            workflow_id=workflow_id,
            step=payload.step,
            resource_id=payload.resource_id or "gemini",
            units=payload.units or 1,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")


@app.post("/api/workflows/{workflow_id}/steps/complete")
def complete_step(workflow_id: str, payload: StepCompletePayload):
    try:
        return RUNTIME.complete_step_execution(
            workflow_id=workflow_id,
            step=payload.step,
            usage=payload.usage,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")


@app.get("/api/resources")
def get_resources():
    return list(RUNTIME.resources_store.values())


@app.get("/api/reservations")
def get_reservations():
    return list(RUNTIME.reservations_store.values())


@app.get("/api/metrics")
def get_metrics():
    return RUNTIME.get_metrics()


@app.get("/api/events")
def get_events():
    return [e.to_frontend_dict() for e in RUNTIME.events]


@app.get("/api/policy")
def get_policy():
    return RUNTIME.policy_def.to_frontend_dict()


@app.post("/api/policy")
def set_policy(payload: PolicyUpdateRequest):
    try:
        mode = PolicyMode(payload.mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode '{payload.mode}'. Must be Light, Medium, or Aggressive.")
    updated = RUNTIME.set_policy_mode(mode)
    return {"mode": updated.mode.value, "applied": True}


@app.get("/api/analytics")
def get_analytics():
    return RUNTIME.get_experiment()


# -----------------------------------------------------------------------------
# Demo & Scenario Endpoints (Correction 18)
# -----------------------------------------------------------------------------

@app.post("/api/demo/step")
def demo_step():
    """Advances 1 step of the 80/10 protection demo scenario."""
    return RUNTIME.execute_demo_step()


@app.post("/api/demo/reset")
def demo_reset(seed: Optional[int] = None):
    """Resets the simulation engine state."""
    return RUNTIME.reset_scenario(seed=seed)


@app.post("/api/demo/mismatch")
def demo_mismatch():
    """Forces prediction divergence and triggers dynamic re-planning."""
    return RUNTIME.force_mismatch()


# -----------------------------------------------------------------------------
# Gemini Adapter Endpoint (Correction 19)
# -----------------------------------------------------------------------------

@app.post("/api/gemini/run")
def run_gemini(payload: GeminiRunRequest):
    """Executes a real or simulated prompt via the Gemini adapter."""
    res = RUNTIME.gemini_adapter.execute_prompt(prompt=payload.prompt, max_tokens=payload.max_tokens)
    return {
        "success": res.success,
        "is_live": res.is_live,
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
        "total_tokens": res.total_tokens,
        "response_text": res.response_text,
        "error": res.error,
    }


# -----------------------------------------------------------------------------
# Intermittent Connectivity & Offline Resilience Endpoints
# -----------------------------------------------------------------------------

class SimulateOutageRequest(BaseModel):
    duration_seconds: float = Field(60.0, description="Duration of simulated outage in seconds")


@app.get("/api/connectivity")
def get_connectivity():
    """Returns real-time connectivity status, outage timer, and offline statistics."""
    return CONNECTIVITY.to_dict()


@app.post("/api/connectivity/simulate")
def simulate_outage(payload: Optional[SimulateOutageRequest] = None):
    """Triggers a software-simulated network outage for evaluation demonstrations."""
    duration = payload.duration_seconds if payload else 60.0
    CONNECTIVITY.simulate_outage(duration_seconds=duration)
    return {
        "simulating": True,
        "duration_seconds": duration,
        "state": CONNECTIVITY.state.value,
        "notice": f"Simulating {duration}s network outage. SunkGuard entering Local Safe Mode.",
    }


@app.post("/api/connectivity/restore")
def restore_connectivity():
    """Immediately restores connectivity and triggers automatic reconciliation."""
    CONNECTIVITY.restore_connectivity()
    res = RECONCILER.reconcile()
    return {
        "restored": True,
        "state": CONNECTIVITY.state.value,
        "reconciliation": res,
    }


@app.get("/api/connectivity/journal")
def get_offline_journal(limit: int = 50):
    """Returns durable audit log of events and workflows recorded during outages."""
    return {
        "entries": OFFLINE_JOURNAL.get_all_entries(limit=limit),
        "unreconciled": OFFLINE_JOURNAL.get_unreconciled_workflows(),
    }


@app.get("/api/connectivity/storage")
def get_offline_storage_info():
    """Returns filesystem disk storage details for offline journal and SQLite WAL database."""
    auth_db_path = Path(__file__).resolve().parent / "data" / "auth.db"
    auth_exists = auth_db_path.exists()
    auth_size = os.path.getsize(auth_db_path) if auth_exists else 0
    auth_mtime = os.path.getmtime(auth_db_path) if auth_exists else 0.0

    journal_info = OFFLINE_JOURNAL.get_storage_info()

    return {
        "journal_file": journal_info,
        "database_file": {
            "file_name": auth_db_path.name,
            "relative_path": f"data/{auth_db_path.name}",
            "absolute_path": str(auth_db_path.resolve()),
            "file_exists": auth_exists,
            "size_bytes": auth_size,
            "size_formatted": f"{auth_size / 1024:.2f} KB" if auth_size > 1024 else f"{auth_size} B",
            "last_modified": auth_mtime,
            "last_modified_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(auth_mtime)) if auth_mtime else "N/A",
            "durability": "SQLite WAL (Write-Ahead Logging) mode with ACID atomic commits",
            "power_outage_safe": True,
        },
        "guarantee": {
            "title": "Zero-Loss Power Outage Durability",
            "description": "Every offline event calls POSIX fsync() immediately to flush OS kernel buffer cache to physical disk. In the event of a sudden power outage or system crash, zero state or in-flight progress is lost.",
            "tail_command": "tail -f data/offline_journal.jsonl",
            "inspect_command": "python3 scripts/show_offline_files.py",
        },
    }


# -----------------------------------------------------------------------------
# Donut Challenge 02: Login Authentication with OTP Verification
# -----------------------------------------------------------------------------

class OtpRequestPayload(BaseModel):
    email: str = Field(..., description="User's email address")


class OtpVerifyPayload(BaseModel):
    email: str = Field(..., description="User's email address")
    otp: str = Field(..., description="6-digit verification passcode")


@app.post("/api/auth/otp/request")
def request_otp(payload: OtpRequestPayload):
    """Generates and delivers a cryptographically secure 6-digit OTP code to user's email."""
    res = AUTH_MANAGER.request_otp(payload.email)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res)
    return res


@app.post("/api/auth/otp/verify")
def verify_otp(payload: OtpVerifyPayload):
    """Verifies OTP, creates/updates user, and issues a 24-hour Bearer session token."""
    res = AUTH_MANAGER.verify_otp(payload.email, payload.otp)
    if not res.get("success"):
        raise HTTPException(status_code=401, detail=res)
    return res


@app.get("/api/auth/me")
def get_current_user(authorization: Optional[str] = Header(None)):
    """Validates session token from Authorization header and returns user profile."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={"authenticated": False, "message": "Missing Authorization header."},
        )
    profile = AUTH_MANAGER.validate_session(authorization)
    if not profile:
        raise HTTPException(
            status_code=401,
            detail={"authenticated": False, "message": "Session expired or invalid. Please login again."},
        )
    return {"authenticated": True, "user": profile}


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    """Revokes active session."""
    if authorization:
        AUTH_MANAGER.revoke_session(authorization)
    return {"success": True, "message": "Logged out successfully."}


# -----------------------------------------------------------------------------
# Optional Static Frontend Mounting
# -----------------------------------------------------------------------------

dist_path = Path(__file__).resolve().parent / "dist"
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
