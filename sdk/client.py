"""SunkGuard Client SDK for compound agent workflows.

Provides lightweight client bindings to interact with the SunkGuard control plane
either via REST API (/api/) or direct in-memory runtime.
"""

import json
import os
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request


class SunkGuardClient:
    """Client for registering agent workflows, reserving capacity, and reporting progress."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        in_memory: Optional[bool] = None,
    ):
        self.base_url = (base_url or os.environ.get("SUNKGUARD_API_URL", "http://localhost:8000")).rstrip("/")
        self._runtime = None

        if in_memory is not None:
            self.in_memory = in_memory
        elif self.base_url.startswith("memory://"):
            self.in_memory = True
        else:
            # Quick probe to see if local server is listening
            try:
                req = urllib.request.Request(f"{self.base_url}/api/health", method="GET")
                with urllib.request.urlopen(req, timeout=0.3) as resp:
                    self.in_memory = (resp.status != 200)
            except Exception:
                self.in_memory = True

    @property
    def runtime(self):
        if self._runtime is None:
            from core.runtime import RUNTIME
            self._runtime = RUNTIME
        return self._runtime

    def _http_request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            # Fall back to in-memory runtime
            self.in_memory = True
            return self._dispatch_in_memory(method, path, payload)

    def _dispatch_in_memory(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        rt = self.runtime
        payload = payload or {}

        if path == "/api/workflows" and method == "POST":
            return rt.register_workflow(
                name=payload.get("name", "Agent workflow"),
                workflow_id=payload.get("id"),
                agent_type=payload.get("agentType", "Custom agent"),
                resource_need=payload.get("resourceNeed", "Gemini tokens"),
                template_id=payload.get("template_id"),
                planned_steps=payload.get("planned_steps"),
            )
        elif path.startswith("/api/workflows/") and path.endswith("/steps/request") and method == "POST":
            wf_id = path.split("/")[3]
            return rt.request_step_admission(
                workflow_id=wf_id,
                step=payload.get("step", ""),
                resource_id=payload.get("resource_id", "gemini"),
                units=payload.get("units", 1),
            )
        elif path.startswith("/api/workflows/") and path.endswith("/steps/complete") and method == "POST":
            wf_id = path.split("/")[3]
            return rt.complete_step_execution(
                workflow_id=wf_id,
                step=payload.get("step", ""),
                usage=payload.get("usage"),
            )
        elif path.startswith("/api/workflows/") and method == "GET":
            wf_id = path.split("/")[3]
            wf = rt.workflows_store.get(wf_id)
            if not wf:
                raise KeyError(f"Workflow '{wf_id}' not found.")
            return wf
        elif path == "/api/overview" and method == "GET":
            return rt.get_overview()
        elif path == "/api/metrics" and method == "GET":
            return rt.get_metrics()
        else:
            raise NotImplementedError(f"Unsupported in-memory endpoint: {method} {path}")

    def start_workflow(
        self,
        name: str,
        agent_type: str = "Custom agent",
        resource_need: str = "Gemini tokens",
        template_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        planned_steps: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Registers a workflow with the SunkGuard control plane."""
        payload = {
            "name": name,
            "agentType": agent_type,
            "resourceNeed": resource_need,
            "template_id": template_id,
            "id": workflow_id,
            "planned_steps": planned_steps,
        }
        if self.in_memory:
            return self._dispatch_in_memory("POST", "/api/workflows", payload)
        return self._http_request("POST", "/api/workflows", payload)

    def request_step(
        self,
        workflow_id: str,
        step: str,
        resource_id: str = "gemini",
        units: int = 1,
    ) -> Dict[str, Any]:
        """Requests admission and reservation for a specific step."""
        payload = {"step": step, "resource_id": resource_id, "units": units}
        if self.in_memory:
            return self._dispatch_in_memory("POST", f"/api/workflows/{workflow_id}/steps/request", payload)
        return self._http_request("POST", f"/api/workflows/{workflow_id}/steps/request", payload)

    def complete_step(
        self,
        workflow_id: str,
        step: str,
        usage: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Reports step completion and releases resource holds."""
        payload = {"step": step, "usage": usage}
        if self.in_memory:
            return self._dispatch_in_memory("POST", f"/api/workflows/{workflow_id}/steps/complete", payload)
        return self._http_request("POST", f"/api/workflows/{workflow_id}/steps/complete", payload)

    def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Retrieves live status and metrics for a workflow."""
        if self.in_memory:
            return self._dispatch_in_memory("GET", f"/api/workflows/{workflow_id}")
        return self._http_request("GET", f"/api/workflows/{workflow_id}")
