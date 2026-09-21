"""Unit tests for ResourceState and ResourceManager."""

import unittest

from core.resources import DEFAULT_RESOURCE_SPECS, ResourceManager, ResourceSpec


class TestResources(unittest.TestCase):

    def setUp(self):
        self.rm = ResourceManager()

    def test_allocation_and_release(self):
        pro = self.rm.get("pro")
        self.assertEqual(pro.in_use, 0)
        self.assertEqual(pro.cap, 7)
        self.assertEqual(pro.free_physical, 7)

        pro.allocate(3)
        self.assertEqual(pro.in_use, 3)
        self.assertEqual(pro.free_physical, 4)

        pro.release(2)
        self.assertEqual(pro.in_use, 1)
        self.assertEqual(pro.free_physical, 6)

        pro.release(5)  # Release more than in_use clamps to 0
        self.assertEqual(pro.in_use, 0)

    def test_over_allocation_raises_error(self):
        pro = self.rm.get("pro")
        with self.assertRaises(ValueError):
            pro.allocate(8)  # Cap is 7

    def test_hard_reservation_blocks_allocation(self):
        search = self.rm.get("search")  # cap = 4
        search.hard_reserved = 3
        search.in_use = 1

        # Free unreserved is 0 (cap 4 - in_use 1 - hard 3)
        self.assertEqual(search.free_unreserved, 0)

        # Another unreserved workflow needing 1 unit cannot allocate
        self.assertFalse(search.can_allocate(units=1, holding_hard_units=0))

        # But a workflow holding 1 of those hard reserved units CAN allocate!
        self.assertTrue(search.can_allocate(units=1, holding_hard_units=1))


if __name__ == "__main__":
    unittest.main()
