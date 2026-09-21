"""Concurrent Gemini Workflow Test comparing oldest_first vs admission_only on real tokens.

Executes a concurrent batch of 6-8 workflows with strict self-imposed guardrails
(<= 16 API calls, max 40 tokens per call) to measure real token usage, latency,
and throughput under contention, verifying that traces contain zero secrets.
"""

import concurrent.futures
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.gemini_adapter import GeminiProviderAdapter
from core.runtime import RUNTIME

TRACES_DIR = Path(__file__).resolve().parent / "traces"
TRACES_DIR.mkdir(parents=True, exist_ok=True)

# 6 compact real workflow tasks with minimal token footprint
CONCURRENT_TASKS = [
    {
        "id": "wf-c01",
        "name": "Market Trend Extractor",
        "prompt": "Identify 1 emerging trend in AI infrastructure for 2026 in 10 words.",
        "units": 3,
        "priority_boost": 0.1,
    },
    {
        "id": "wf-c02",
        "name": "Database Lock Diagnoser",
        "prompt": "Explain deadlock detection in distributed DBs in 10 words.",
        "units": 3,
        "priority_boost": 0.5,
    },
    {
        "id": "wf-c03",
        "name": "SRE Incident Classifier",
        "prompt": "Classify cascading failure in distributed microservices in 10 words.",
        "units": 3,
        "priority_boost": 0.2,
    },
    {
        "id": "wf-c04",
        "name": "API Rate Limit Synthesizer",
        "prompt": "State the difference between token bucket and leaky bucket in 10 words.",
        "units": 3,
        "priority_boost": 0.7,
    },
    {
        "id": "wf-c05",
        "name": "Vector Index Optimizer",
        "prompt": "Why use HNSW over flat index for search in 10 words.",
        "units": 3,
        "priority_boost": 0.3,
    },
    {
        "id": "wf-c06",
        "name": "Admission Policy Verifier",
        "prompt": "Define predictive reservation in distributed control planes in 10 words.",
        "units": 3,
        "priority_boost": 0.6,
    },
]


def sanitize_no_secrets(obj: Any) -> bool:
    """Strictly confirms that object string representation contains no API keys or secrets."""
    text = json.dumps(obj)
    # Check for Google API key pattern or auth tokens
    if re.search(r"AIza[0-9A-Za-z\-_]{35}", text):
        return False
    if re.search(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", text, re.IGNORECASE):
        return False
    if "api_key" in text.lower() and re.search(r'api_key["\']?\s*[:=]\s*["\'][a-zA-Z0-9_\-]{10,}', text, re.IGNORECASE):
        return False
    return True


def run_single_workflow(
    task: Dict[str, Any],
    variant: str,
    adapter: GeminiProviderAdapter,
    shared_lock: Any,
) -> Dict[str, Any]:
    wf_id = f"{task['id']}-{variant[:3]}"
    t_start = time.time()
    
    # 1. Register workflow in RUNTIME
    RUNTIME.register_workflow(
        name=task["name"],
        workflow_id=wf_id,
        agent_type="Concurrent Agent",
        resource_need="Gemini Pro 3 units",
        template_id="research",
        planned_steps=[{"label": task["name"], "resource": "pro", "units": task["units"]}],
    )

    # 2. Acquire step admission under controller contention (simulating queuing until granted)
    granted = False
    attempts = 0
    while not granted and attempts < 200:
        attempts += 1
        with shared_lock:
            adm = RUNTIME.request_step_admission(
                workflow_id=wf_id,
                step=task["name"],
                resource_id="pro",
                units=task["units"],
            )
        if adm.get("decision") == "granted":
            granted = True
            break
        time.sleep(0.1)

    if not granted:
        return {
            "workflow_id": wf_id,
            "name": task["name"],
            "status": "TIMED_OUT",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_seconds": round(time.time() - t_start, 3),
            "is_live": False,
            "output_snippet": "",
        }

    # 3. Execute live Gemini API call on real tokens
    call_res = adapter.execute_prompt(task["prompt"], max_tokens=35)
    t_latency = round(time.time() - t_start, 3)

    # 4. Release step resources in RUNTIME
    with shared_lock:
        RUNTIME.complete_step_execution(
            workflow_id=wf_id,
            step=task["name"],
            usage={
                "prompt_tokens": call_res.prompt_tokens,
                "completion_tokens": call_res.completion_tokens,
                "total_tokens": call_res.total_tokens,
            },
        )

    return {
        "workflow_id": wf_id,
        "name": task["name"],
        "status": "COMPLETED" if call_res.success else "FAILED",
        "prompt_tokens": call_res.prompt_tokens,
        "completion_tokens": call_res.completion_tokens,
        "total_tokens": call_res.total_tokens,
        "latency_seconds": t_latency,
        "is_live": call_res.is_live,
        "output_snippet": call_res.response_text[:60] if call_res.response_text else "",
    }


def run_benchmark():
    import threading
    adapter = GeminiProviderAdapter()
    print("=" * 70)
    print("CONCURRENT GEMINI WORKFLOW BENCHMARK")
    print(f"Live API: {adapter.is_configured} | Model: {adapter.model}")
    print(f"Workflows per batch: 6 | Self-imposed cap: 16 calls")
    print("=" * 70)

    results = {}
    shared_lock = threading.Lock()

    for variant in ["oldest_first", "admission_only"]:
        print(f"\n>>> Running Batch with Controller Variant: {variant} <<<")
        # Reset runtime resources
        for r in RUNTIME.rm.resources.values():
            r.in_use = 0
            r.hard_reserved = 0
            r.soft_reserved = 0
        RUNTIME.controller.variant = variant

        batch_start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(run_single_workflow, task, variant, adapter, shared_lock)
                for task in CONCURRENT_TASKS
            ]
            batch_results = [f.result() for f in futures]
        batch_duration = round(time.time() - batch_start, 3)

        completed = sum(1 for r in batch_results if r["status"] == "COMPLETED")
        tokens_spent = sum(r.get("total_tokens", 0) for r in batch_results)
        latencies = [r["latency_seconds"] for r in batch_results]
        mean_lat = round(sum(latencies) / len(latencies), 3) if latencies else 0.0

        results[variant] = {
            "variant": variant,
            "workflows_dispatched": len(CONCURRENT_TASKS),
            "completed": completed,
            "total_tokens_consumed": tokens_spent,
            "mean_workflow_latency_sec": mean_lat,
            "batch_duration_sec": batch_duration,
            "details": batch_results,
        }

        print(f"  Completed: {completed}/{len(CONCURRENT_TASKS)}")
        print(f"  Real Tokens Consumed: {tokens_spent}")
        print(f"  Mean Workflow Latency: {mean_lat}s")
        print(f"  Batch Elapsed Time: {batch_duration}s")

    # Save benchmark report trace
    trace_file = TRACES_DIR / "concurrent_gemini_test_trace.json"
    with open(trace_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Confirm traces contain no secrets
    assert sanitize_no_secrets(results), "CRITICAL: Secrets detected in benchmark results!"
    for trace_path in TRACES_DIR.glob("*.json"):
        with open(trace_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert not re.search(r"AIza[0-9A-Za-z\-_]{35}", content), f"Secret found in {trace_path}!"
            assert not re.search(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", content, re.IGNORECASE), f"Bearer secret found in {trace_path}!"

    print("\n" + "=" * 70)
    print("BENCHMARK COMPARISON SUMMARY")
    print("=" * 70)
    print(f"Oldest-First:   Tokens = {results['oldest_first']['total_tokens_consumed']} | Mean Latency = {results['oldest_first']['mean_workflow_latency_sec']}s | Batch Time = {results['oldest_first']['batch_duration_sec']}s")
    print(f"Admission-Only: Tokens = {results['admission_only']['total_tokens_consumed']} | Mean Latency = {results['admission_only']['mean_workflow_latency_sec']}s | Batch Time = {results['admission_only']['batch_duration_sec']}s")
    print(f"\nTrace written to: {trace_file}")
    print("Verified: Zero secrets or API keys found in any trace files.")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
