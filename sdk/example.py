"""Runnable example demonstrating SunkGuard @reserved decorator and client.

Usage:
    python3 sdk/example.py
"""

import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdk.client import SunkGuardClient
from sdk.decorator import reserved, reserved_step


# Initialize client (uses in-memory mode or active local server)
client = SunkGuardClient()


# Define compound workflow steps decorated with @reserved
@reserved(step_name="Step 1: Planning", resource_id="pro", units=2)
def plan_investigation(query: str, workflow_id: str):
    print(f"[{workflow_id}] Executing Plan Investigation for query: '{query}'")
    # Simulate generating plan
    return {"plan": "1. Search docs, 2. Synthesize findings", "total_tokens": 850}


@reserved(step_name="Step 2: Analysis", resource_id="pro", units=3)
def analyze_data(plan: str, workflow_id: str):
    print(f"[{workflow_id}] Executing Data Analysis under reservation...")
    return {"analysis": "Key findings identified", "total_tokens": 1620}


@reserved(step_name="Step 3: Verification", resource_id="flash", units=1)
def verify_output(analysis: str, workflow_id: str):
    print(f"[{workflow_id}] Executing Verification...")
    return {"verified": True, "total_tokens": 420}


def run_compound_workflow():
    print("=== SunkGuard SDK Compound Workflow Demo ===")
    
    # 1. Register workflow
    reg = client.start_workflow(
        name="SDK Demo Analysis",
        agent_type="Research agent",
        resource_need="Gemini tokens",
        template_id="research",
    )
    wf_id = reg["workflowId"]
    print(f"Registered workflow: {wf_id}")
    print(f"Prediction Confidence: {reg.get('confidence')}")
    print(f"Reservation Granted: {reg.get('reservationType')}")

    # 2. Execute step 1
    out1 = plan_investigation(query="Quarterly compute trends", workflow_id=wf_id)
    wf_state = client.get_workflow(wf_id)
    print(f"After Step 1: Progress={wf_state['progress']}%, Status={wf_state['status']}, Tokens={wf_state['tokensSpent']}")

    # 3. Execute step 2
    out2 = analyze_data(plan=out1["plan"], workflow_id=wf_id)
    wf_state = client.get_workflow(wf_id)
    print(f"After Step 2: Progress={wf_state['progress']}%, Status={wf_state['status']}, WorkAtRisk=${wf_state['workAtRisk']}")

    # 4. Execute step 3 using context manager
    with reserved_step(wf_id, "Step 3: Verification", resource_id="flash", units=1) as ctx:
        out3 = verify_output(analysis=out2["analysis"], workflow_id=wf_id)
        ctx.record_usage(total_tokens=out3["total_tokens"])

    # 5. Final state
    final_wf = client.get_workflow(wf_id)
    print("\n=== Workflow Completed Successfully ===")
    print(f"ID: {final_wf['id']}")
    print(f"Final Status: {final_wf['status']}")
    print(f"Completed Steps: {final_wf['completedSteps']}")
    print(f"Total Tokens Spent: {final_wf['tokensSpent']}")
    print(f"Work At Risk: ${final_wf['workAtRisk']}")
    print(f"Protection Value: {final_wf['protectionValue']}")


if __name__ == "__main__":
    run_compound_workflow()
