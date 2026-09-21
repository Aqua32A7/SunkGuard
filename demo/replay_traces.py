"""Replay saved Gemini workflow traces through the SunkGuard control plane.

Deterministic offline replay without external API dependencies.
"""

import json
from pathlib import Path
import sys
import time

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdk.client import SunkGuardClient
from sdk.decorator import reserved_step

TRACES_DIR = Path(__file__).resolve().parent / "traces"


def replay_all_traces():
    trace_files = sorted(TRACES_DIR.glob("trace_*.json"))
    if not trace_files:
        print(f"No trace files found in {TRACES_DIR}. Run demo/run_gemini_workflow.py first.")
        return

    client = SunkGuardClient(in_memory=True)
    print(f"=== SunkGuard Offline Replay Mode ({len(trace_files)} traces found) ===")

    for tf in trace_files:
        with open(tf, "r", encoding="utf-8") as f:
            trace = json.load(f)

        print(f"\n[Replaying] {trace['scenario_name']} ({trace['workflow_id']})")
        
        # Register in controller
        reg = client.start_workflow(
            name=f"Replay: {trace['scenario_name']}",
            agent_type=trace["agent_type"],
            template_id=trace["template_id"],
        )
        wf_id = reg["workflowId"]

        for step in trace["steps"]:
            step_name = step["step_name"]
            res_id = step["resource_id"]
            units = step["units"]
            tokens = step["total_tokens"]
            latency = step["latency_seconds"]

            with reserved_step(wf_id, step_name, resource_id=res_id, units=units, client=client) as ctx:
                ctx.record_usage(
                    total_tokens=tokens,
                    prompt_tokens=step["prompt_tokens"],
                    completion_tokens=step["completion_tokens"],
                )
                print(f"  -> Replayed '{step_name}' ({units}x {res_id}): {tokens} tokens, {latency:.2f}s simulated")

        final = client.get_workflow(wf_id)
        print(f"  Result: Status={final['status']}, Progress={final['progress']}%, WorkAtRisk=${final['workAtRisk']}, PV={final['protectionValue']}")

    print("\n=== Offline Replay Complete ===")


if __name__ == "__main__":
    replay_all_traces()
