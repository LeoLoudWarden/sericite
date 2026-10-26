from __future__ import annotations

import unittest

from sericite.accounting import Meter
from sericite.engine import SericiteEngine


class VirtualInputStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SericiteEngine()
        self.engine.create_root("")
        self.context = self.engine._contexts[0]
        self.io = self.context.io
        self.meter = Meter(self.engine._account_routes[0])

    def test_script_input_consumes_matching_permit(self) -> None:
        permit = self.meter.reserve(self.io, "input", self.io.input_cost("x"))
        self.io.feed_input("x", permit=permit)
        self.assertTrue(permit.consumed)
        self.assertEqual(self.io.buffered_input_count, 1)
        self.assertEqual(self.context.alloc_bytes, 12)

    def test_invalid_batch_has_no_partial_mutation(self) -> None:
        permit = self.meter.reserve(self.io, "input", 24)
        with self.assertRaises(TypeError):
            self.io.feed_batch(["accepted", None], permit=permit)
        self.assertFalse(permit.consumed)
        self.assertEqual(self.io.buffered_input_count, 0)

    def test_trusted_host_preconfiguration_is_explicit(self) -> None:
        self.io.feed_input_trusted("x")
        self.assertEqual(self.io.buffered_input_count, 1)
        self.assertEqual(self.context.alloc_bytes, 0)


if __name__ == "__main__":
    unittest.main()
