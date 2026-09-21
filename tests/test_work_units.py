"""Unit tests for Standard Work Units (SWU) and cost-equivalence conversions."""

import unittest

from core.resources import DEFAULT_RESOURCE_SPECS
from core.workflow import Step


class TestWorkUnits(unittest.TestCase):
    """SPEC.md Section 2: Work units and tool/service cost-equivalence."""

    def test_model_token_conversions(self):
        # Gemini Pro: 1,600 tokens/unit
        pro_step = Step.create("pro", units=3, duration=4)
        self.assertEqual(pro_step.tokens, 3 * 1600)
        self.assertEqual(pro_step.work, 3 * 1600)

        # Gemini Flash: 700 tokens/unit
        flash_step = Step.create("flash", units=5, duration=2)
        self.assertEqual(flash_step.tokens, 5 * 700)
        self.assertEqual(flash_step.work, 5 * 700)

    def test_tool_and_service_cost_equivalence(self):
        # Search: 400 SWU/unit, 0 direct model tokens
        search_step = Step.create("search", units=2, duration=3)
        self.assertEqual(search_step.tokens, 0)
        self.assertEqual(search_step.work, 2 * 400)

        # Code runner: 300 SWU/unit
        code_step = Step.create("code", units=2, duration=3)
        self.assertEqual(code_step.tokens, 0)
        self.assertEqual(code_step.work, 2 * 300)

        # Vector DB: 300 SWU/unit
        vdb_step = Step.create("vdb", units=4, duration=2)
        self.assertEqual(vdb_step.tokens, 0)
        self.assertEqual(vdb_step.work, 4 * 300)

        # CRM API: 300 SWU/unit
        crm_step = Step.create("crm", units=3, duration=2)
        self.assertEqual(crm_step.tokens, 0)
        self.assertEqual(crm_step.work, 3 * 300)

    def test_all_registered_resources_have_swu(self):
        for spec in DEFAULT_RESOURCE_SPECS:
            self.assertGreater(spec.swu_per_unit, 0)
            self.assertGreater(spec.cap, 0)


if __name__ == "__main__":
    unittest.main()
