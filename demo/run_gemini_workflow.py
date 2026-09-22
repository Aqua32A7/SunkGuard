"""Live Gemini Compound Workflow Runner and Trace Collector.

Executes real multi-step agent workflows via GeminiProviderAdapter within strict
call and token guardrails, measures per-step latency, records canonical trace files,
and performs tick calibration (Item J: 1 tick = median step latency in seconds).
"""

import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Dict, List

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.gemini_adapter import GeminiProviderAdapter
from sdk.client import SunkGuardClient
from sdk.decorator import reserved_step

TRACES_DIR = Path(__file__).resolve().parent / "traces"
TRACES_DIR.mkdir(parents=True, exist_ok=True)


WORKFLOW_SCENARIOS = [
    {
        "name": "Market Intelligence Brief",
        "agent_type": "Research agent",
        "template_id": "research",
        "steps": [
            {
                "name": "Deconstruct Inquiry",
                "resource": "pro",
                "units": 2,
                "prompt": "You are a lead market research planner. Deconstruct the inquiry 'Generative AI infrastructure market dynamics 2026' into 3 core architectural sub-questions. Keep response under 100 words.",
                "max_tokens": 120,
            },
            {
                "name": "Synthesize Capacity Insights",
                "resource": "pro",
                "units": 3,
                "prompt": "You are an industry analyst. Given high token contention in multi-tenant LLM inference clusters, list 2 structural causes of compound workflow failure under stampede load. Keep response under 100 words.",
                "max_tokens": 120,
            },
            {
                "name": "Review and Format Recommendation",
                "resource": "flash",
                "units": 1,
                "prompt": "You are an executive editor. Provide a 2-sentence executive summary recommending predictive admission control with sunk-cost protection for compound agent pipelines.",
                "max_tokens": 80,
            },
        ],
    },
    {
        "name": "Distributed System Incident Analysis",
        "agent_type": "Code fix agent",
        "template_id": "codefix",
        "steps": [
            {
                "name": "Parse Incident Diagnostics",
                "resource": "flash",
                "units": 2,
                "prompt": "You are an SRE. Diagnose a cascading timeout event where downstream tool reservations expired during long chain execution. State 2 immediate diagnostic hypotheses in 50 words.",
                "max_tokens": 100,
            },
            {
                "name": "Draft Architectural Mitigation",
                "resource": "pro",
                "units": 4,
                "prompt": "You are a distributed systems architect. Propose a starvation-preventing aging queue formula with reservation limits to eliminate compound workflow convoy stalls. Be concise (under 80 words).",
                "max_tokens": 120,
            },
            {
                "name": "Verify Resilience Guarantees",
                "resource": "flash",
                "units": 1,
                "prompt": "You are a verification engineer. Confirm whether wait aging guarantees finite admission bounds under sustained high load. Respond in 2 sentences.",
                "max_tokens": 75,
            },
        ],
    },
    {
        "name": "High-Volume Support Escalation",
        "agent_type": "Support resolution",
        "template_id": "support",
        "steps": [
            {
                "name": "Classify Ticket Urgency",
                "resource": "flash",
                "units": 1,
                "prompt": "Classify this ticket: 'Enterprise client experiencing 429 quota exhaustion on critical inference pipeline.' Output severity and impact level in 30 words.",
                "max_tokens": 60,
            },
            {
                "name": "Formulate Resolution Guidance",
                "resource": "pro",
                "units": 2,
                "prompt": "Provide guidance on upgrading client tier, applying hard capacity reservation for in-flight chains, and throttling new requests. Concise, under 80 words.",
                "max_tokens": 100,
            },
            {
                "name": "Finalize Escalation Record",
                "resource": "flash",
                "units": 1,
                "prompt": "Format the final escalation status update for executive dashboard review. One concise paragraph.",
                "max_tokens": 70,
            },
        ],
    },
]


def run_and_record_traces() -> Dict[str, Any]:
    adapter = GeminiProviderAdapter()
    # Connects to live server (http://localhost:8000) if online, else falls back to in-memory
    client = SunkGuardClient()

    print(f"Starting Gemini workflow execution (Live API: {adapter.is_configured}, Model: {adapter.model})...")
    print(f"Call Cap: {adapter.call_cap}, Token Cap: {adapter.token_cap}")

    all_step_latencies: List[float] = []
    recorded_traces: List[Dict[str, Any]] = []

    for idx, scenario in enumerate(WORKFLOW_SCENARIOS, start=1):
        print(f"\n--- Workflow {idx}: {scenario['name']} ({scenario['agent_type']}) ---")
        
        # Start workflow in SunkGuard
        reg = client.start_workflow(
            name=scenario["name"],
            agent_type=scenario["agent_type"],
            template_id=scenario["template_id"],
        )
        wf_id = reg["workflowId"]
        print(f"Workflow ID: {wf_id} | Confidence: {reg.get('confidence')} | Reservation: {reg.get('reservationType')}")

        trace_steps = []
        workflow_start_time = time.time()

        for step_idx, step_def in enumerate(scenario["steps"], start=1):
            step_name = step_def["name"]
            resource = step_def["resource"]
            units = step_def["units"]
            prompt = step_def["prompt"]
            max_tokens = step_def["max_tokens"]

            print(f"  [Step {step_idx}] Reserving {units}x {resource} for '{step_name}'...")
            t0 = time.time()
            with reserved_step(wf_id, step_name, resource_id=resource, units=units, client=client) as ctx:
                # Execute prompt through adapter
                call_res = adapter.execute_prompt(prompt, max_tokens=max_tokens)
                dt = time.time() - t0
                all_step_latencies.append(dt)

                ctx.record_usage(
                    total_tokens=call_res.total_tokens,
                    prompt_tokens=call_res.prompt_tokens,
                    completion_tokens=call_res.completion_tokens,
                )

                print(f"    Completed in {dt:.3f}s | Success: {call_res.success} | Tokens: {call_res.total_tokens} (Prompt: {call_res.prompt_tokens}, Resp: {call_res.completion_tokens})")
                if call_res.response_text:
                    snippet = call_res.response_text.strip().replace("\n", " ")[:90]
                    print(f"    Output: {snippet}...")

                trace_steps.append({
                    "step_index": step_idx,
                    "step_name": step_name,
                    "resource_id": resource,
                    "units": units,
                    "prompt": prompt,
                    "response_text": call_res.response_text,
                    "prompt_tokens": call_res.prompt_tokens,
                    "completion_tokens": call_res.completion_tokens,
                    "total_tokens": call_res.total_tokens,
                    "latency_seconds": round(dt, 4),
                    "success": call_res.success,
                    "is_live": call_res.is_live,
                    "error": call_res.error,
                })

        wf_total_time = time.time() - workflow_start_time
        final_wf_state = client.get_workflow(wf_id)

        trace_doc = {
            "workflow_id": wf_id,
            "scenario_name": scenario["name"],
            "agent_type": scenario["agent_type"],
            "template_id": scenario["template_id"],
            "total_latency_seconds": round(wf_total_time, 4),
            "final_progress_pct": final_wf_state["progress"],
            "final_status": final_wf_state["status"],
            "tokens_spent": final_wf_state["tokensSpent"],
            "work_at_risk": final_wf_state["workAtRisk"],
            "protection_value": final_wf_state["protectionValue"],
            "steps": trace_steps,
        }
        recorded_traces.append(trace_doc)

        trace_file = TRACES_DIR / f"trace_{idx:02d}.json"
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace_doc, f, indent=2)
        print(f"  Saved trace: {trace_file}")

    # Item J: Compute calibrated median step latency
    median_latency = statistics.median(all_step_latencies)
    mean_latency = statistics.mean(all_step_latencies)

    calibration_summary = {
        "call_count": len(all_step_latencies),
        "total_tokens_consumed": adapter.tokens_used,
        "mean_step_latency_seconds": round(mean_latency, 4),
        "median_step_latency_seconds": round(median_latency, 4),
        "calibrated_seconds_per_tick": round(median_latency, 4),
        "traces_saved": len(recorded_traces),
    }

    cal_file = TRACES_DIR / "calibration_summary.json"
    with open(cal_file, "w", encoding="utf-8") as f:
        json.dump(calibration_summary, f, indent=2)

    print("\n=======================================================")
    print("           TICK CALIBRATION SUMMARY (ITEM J)           ")
    print("=======================================================")
    print(f"Total Workflow Steps Executed: {len(all_step_latencies)}")
    print(f"Total API Tokens Consumed:    {adapter.tokens_used}")
    print(f"Mean Step Latency:            {mean_latency:.3f} seconds")
    print(f"Median Step Latency (1 tick): {median_latency:.3f} seconds")
    print(f"Summary Written:              {cal_file}")
    print("=======================================================\n")

    return calibration_summary


if __name__ == "__main__":
    run_and_record_traces()
