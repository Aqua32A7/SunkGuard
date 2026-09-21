"""Comprehensive unit tests for the SunkGuard Python SDK.

Tests SunkGuardClient, @reserved decorator, reserved_step context manager,
and capacity tracking.
"""

import unittest

from sdk.client import SunkGuardClient
from sdk.decorator import reserved, reserved_step


class TestSunkGuardSDK(unittest.TestCase):

    def setUp(self):
        self.client = SunkGuardClient(in_memory=True)

    def test_workflow_lifecycle(self):
        # 1. Register workflow
        reg = self.client.start_workflow(
            name="SDK Test Workflow",
            agent_type="Research agent",
            template_id="research",
        )
        self.assertTrue(reg["accepted"])
        wf_id = reg["workflowId"]
        self.assertIsNotNone(wf_id)
        self.assertIn("confidence", reg)
        self.assertIn(reg["reservationType"], ("HARD", "SOFT", "NONE"))

        # 2. Request step
        req = self.client.request_step(wf_id, step="Step 1: Planning", resource_id="pro", units=2)
        self.assertEqual(req["decision"], "granted")
        self.assertEqual(req["allocatedUnits"], 2)

        # 3. Complete step
        comp = self.client.complete_step(wf_id, step="Step 1: Planning", usage={"total_tokens": 1500})
        self.assertTrue(comp["recorded"])
        self.assertGreater(comp["progress"], 0)

        # 4. Fetch workflow state
        wf = self.client.get_workflow(wf_id)
        self.assertIn("Step 1: Planning", wf["completedSteps"])
        self.assertGreater(wf["workAtRisk"], 0.0)

    def test_reserved_decorator(self):
        reg = self.client.start_workflow(
            name="Decorator Test",
            agent_type="Code fix agent",
            template_id="codefix",
        )
        wf_id = reg["workflowId"]

        @reserved(step_name="Step 1: Inspection", resource_id="vdb", units=1, client=self.client)
        def inspect_code(query: str, workflow_id: str):
            return {"status": "inspected", "total_tokens": 600}

        res = inspect_code("Fix bug #42", workflow_id=wf_id)
        self.assertEqual(res["status"], "inspected")

        wf = self.client.get_workflow(wf_id)
        self.assertIn("Step 1: Inspection", wf["completedSteps"])

    def test_reserved_context_manager(self):
        reg = self.client.start_workflow(
            name="Context Test",
            agent_type="Support resolution",
            template_id="support",
        )
        wf_id = reg["workflowId"]

        with reserved_step(wf_id, "Step 1: Triage", resource_id="vdb", units=1, client=self.client) as ctx:
            self.assertEqual(ctx.decision, "granted")
            ctx.record_usage(total_tokens=900)

        wf = self.client.get_workflow(wf_id)
        self.assertIn("Step 1: Triage", wf["completedSteps"])
        self.assertGreater(wf["workAtRisk"], 0.0)

    def test_missing_workflow_id_raises(self):
        @reserved(step_name="No Workflow", client=self.client)
        def invalid_step(x: int):
            return x * 2

        with self.assertRaises(ValueError):
            invalid_step(10)


if __name__ == "__main__":
    unittest.main()
