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


class BufferedOutputTests(unittest.TestCase):
    def test_root_can_forward_without_buffering(self) -> None:
        chunks = []
        root = SericiteEngine().create_root(
            'print("first")',
            output_writer=chunks.append,
            buffer_output=False,
        )
        self.assertEqual(root.run(), "")
        self.assertEqual(root.exec('print("second")'), "")
        self.assertEqual(root.stdout(), "")
        self.assertEqual(root.snapshot()["stdout"], "")
        self.assertEqual(chunks, ["first\n", "second\n"])

    def test_unbuffered_output_still_obeys_limit(self) -> None:
        chunks = []
        root = SericiteEngine().create_root(
            'print("abc")',
            limits=SericiteLimits(max_output_bytes=2),
            output_writer=chunks.append,
            buffer_output=False,
        )
        with self.assertRaises(SericiteError) as raised:
            root.run()
        self.assertEqual(raised.exception.kind, "resource_exhausted")
        self.assertEqual(chunks, [])

    def test_buffer_option_requires_bool(self) -> None:
        with self.assertRaises(SericiteError) as raised:
            SericiteEngine().create_root("", buffer_output=1)
        self.assertEqual(raised.exception.kind, "type_error")
        root = SericiteEngine().create_root('sub = VM("", buffer_output=1)')
        with self.assertRaises(SericiteError) as raised:
            root.run()
        self.assertEqual(raised.exception.kind, "type_error")


class ScriptOutputWriterTests(unittest.TestCase):
    def test_child_writer_forwards_and_preserves_buffered_stdout(self) -> None:
        chunks = []
        root = SericiteEngine().create_root(
            "def forward(text):\n"
            '    print(text, end="")\n'
            "sub = VM('print(\"child\")', output_writer=forward)\n"
            "out = sub.run()\n"
            'print(out, end="")',
            output_writer=chunks.append,
        )
        root.run()
        self.assertEqual(chunks, ["child\n", "child\n"])

    def test_child_can_forward_without_buffering(self) -> None:
        chunks = []
        root = SericiteEngine().create_root(
            "def forward(text):\n"
            '    print(text, end="")\n'
            "sub = VM('print(\"child\")', output_writer=forward, "
            "buffer_output=False)\n"
            "out = sub.run()\n"
            'print(out == "")',
            output_writer=chunks.append,
        )
        root.run()
        self.assertEqual(chunks, ["child\n", "True\n"])

    def test_nested_writers_chain_through_definition_side_ios(self) -> None:
        chunks = []
        child_source = (
            "def layer_2_output(text):\n"
            '    print(text, end="")\n'
            "inner = VM('print(\"deep\")', output_writer=layer_2_output)\n"
            "out = inner.run()\n"
            'print(out, end="")'
        )
        engine = SericiteEngine()
        root = engine.create_root(
            "def layer_1_output(text):\n"
            '    print(text, end="")\n'
            f"sub = VM({child_source!r}, output_writer=layer_1_output)\n"
            "sub.run()",
            output_writer=chunks.append,
        )
        root.run()
        self.assertEqual(chunks, ["deep\n", "deep\n"])
        self.assertEqual(engine._contexts[2].io.stdout(), "deep\n")
        self.assertEqual(engine._contexts[1].io.stdout(), "deep\ndeep\n")

    def test_writer_retains_closure_and_host_functions_are_supported(self) -> None:
        chunks = []
        root = SericiteEngine().create_root(
            "def make_writer(prefix):\n"
            "    def writer(text):\n"
            '        print(prefix + text, end="")\n'
            "    return writer\n"
            'sub = VM(\'print("child")\', output_writer=make_writer("[live] "))\n'
            "sub.run()"
        )
        self.assertEqual(root.run(), "[live] child\n")

        root = SericiteEngine().create_root(
            "sub = VM('print(\"host\")', output_writer=forward)\nsub.run()",
            functions={"forward": chunks.append},
        )
        root.run()
        self.assertEqual(chunks, ["host\n"])

    def test_writer_is_not_implicitly_inherited(self) -> None:
        child_source = "inner = VM('print(\"inner\")')\ninner.run()"
        root = SericiteEngine().create_root(
            "def forward(text):\n"
            '    print(text, end="")\n'
            f"sub = VM({child_source!r}, output_writer=forward)\n"
            "sub.run()"
        )
        self.assertEqual(root.run(), "")

    def test_writer_error_propagates_to_triggering_print(self) -> None:
        root = SericiteEngine().create_root(
            "def forward(text):\n"
            '    if text == "bad\\n":\n'
            '        raise "boom"\n'
            "sub = VM("
            "'try:\\n"
            '    print("bad")\\n'
            "except raise_error:\\n"
            '    print("caught")\', output_writer=forward)\n'
            'print(sub.run(), end="")'
        )
        self.assertEqual(root.run(), "bad\ncaught\n")

    def test_writer_cannot_suspend_native_print(self) -> None:
        root = SericiteEngine().create_root(
            "def waiting(text):\n"
            "    input()\n"
            "sub = VM('print(\"x\")', output_writer=waiting)\n"
            "sub.run()"
        )
        with self.assertRaises(SericiteError) as raised:
            root.run()
        self.assertEqual(raised.exception.kind, "runtime_error")

    def test_writer_execution_is_charged_to_child_quota(self) -> None:
        engine = SericiteEngine()
        root = engine.create_root(
            "def busy(text):\n"
            "    for i in range(1000):\n"
            "        pass\n"
            "sub = VM('print(\"x\")', output_writer=busy, max_instructions=100)\n"
            "sub.run()"
        )
        with self.assertRaises(SericiteError) as raised:
            root.run()
        self.assertEqual(raised.exception.kind, "resource_exhausted")
        self.assertEqual(engine._contexts[1].state, "resource_exhausted")

    def test_writer_must_be_a_grantable_function(self) -> None:
        root = SericiteEngine().create_root('sub = VM("", output_writer=42)')
        with self.assertRaises(SericiteError) as raised:
            root.run()
        self.assertEqual(raised.exception.kind, "type_error")


if __name__ == "__main__":
    unittest.main()
