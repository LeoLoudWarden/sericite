from __future__ import annotations

import unittest

from sericite.accounting import Meter
from sericite.engine import SericiteEngine, SericiteError, SericiteLimits


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


class VirtualOutputWriterTests(unittest.TestCase):
    def test_root_writer_observes_writes_and_preserves_stdout(self) -> None:
        chunks = []
        root = SericiteEngine().create_root(
            'print("a", end="")\nprint("b")', output_writer=chunks.append
        )
        self.assertEqual(root.run(), "ab\n")
        self.assertEqual(chunks, ["a", "b\n"])
        self.assertEqual(root.stdout(), "ab\n")

    def test_child_does_not_inherit_root_writer(self) -> None:
        chunks = []
        root = SericiteEngine().create_root(
            'sub = VM("print(\'child\')")\nsub.run()\nprint("root")',
            output_writer=chunks.append,
        )
        self.assertEqual(root.run(), "root\n")
        self.assertEqual(chunks, ["root\n"])

    def test_rejected_output_is_not_forwarded(self) -> None:
        chunks = []
        root = SericiteEngine().create_root(
            'print("abc")',
            limits=SericiteLimits(max_output_bytes=2),
            output_writer=chunks.append,
        )
        with self.assertRaises(SericiteError) as raised:
            root.run()
        self.assertEqual(raised.exception.kind, "resource_exhausted")
        self.assertEqual(chunks, [])
        self.assertEqual(root.stdout(), "")


if __name__ == "__main__":
    unittest.main()
