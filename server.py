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

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.canonical import PolicyMode
from core.runtime import RUNTIME

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


class StepRequestPayload(BaseModel):
    step: str


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
    wf_id = payload.id or f"wf-{len(RUNTIME.workflows_store) + 1:03d}"
    new_wf = {
        "id": wf_id,
        "name": payload.name,
        "agentType": payload.agentType,
        "status": "RUNNING",
        "progress": 0,
        "workAtRisk": 0.0,
        "currentStep": "Initializing",
        "predictionConfidence": 0.85,
        "reservationType": "NONE",
        "resourceNeed": payload.resourceNeed,
        "updatedAt": "now",
        "tokensSpent": "0",
        "remainingDemand": "pending",
        "protectionValue": 0.0,
        "waitingTime": "0s",
        "completedSteps": [],
        "timeline": [{"label": "Initialize", "detail": "Starting step", "state": "current"}],
    }
    RUNTIME.workflows_store[wf_id] = new_wf
    return {"workflowId": wf_id, "accepted": True}


@app.post("/api/workflows/{workflow_id}/steps/request")
def request_step(workflow_id: str, payload: StepRequestPayload):
    wf = RUNTIME.workflows_store.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    decision = "granted" if wf["reservationType"] == "HARD" else "queued"
    return {"workflowId": workflow_id, "step": payload.step, "decision": decision}


@app.post("/api/workflows/{workflow_id}/steps/complete")
def complete_step(workflow_id: str, payload: StepCompletePayload):
    wf = RUNTIME.workflows_store.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    wf["progress"] = min(100, wf["progress"] + 25)
    if wf["progress"] >= 100:
        wf["status"] = "COMPLETED"
        wf["currentStep"] = "Completed"
    return {"workflowId": workflow_id, "step": payload.step, "recorded": True}


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
# Optional Static Frontend Mounting
# -----------------------------------------------------------------------------

dist_path = Path(__file__).resolve().parent / "dist"
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
