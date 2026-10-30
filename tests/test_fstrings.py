import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits
from sericite.compiler import compile_source


def run(source):
    return SericiteEngine().create_root(source).run()


class FStringTests(unittest.TestCase):
    def test_literal_empty_and_escaped_braces(self):
        self.assertEqual(
            run('print(f"hello")\nprint(f"")\nprint(f"{{literal}}")\n'),
            "hello\n\n{literal}\n",
        )

    def test_interpolation_uses_str_and_supports_multiple_parts(self):
        source = (
            'name = "world"\n'
            "number = 3\n"
            "items = [1, 2]\n"
            'print(f"hello {name}: {number + 1}, {items}")\n'
        )
        self.assertEqual(run(source), "hello world: 4, [1, 2]\n")

    def test_existing_expressions_and_adjacent_strings(self):
        source = (
            "value = 4\n"
            'print(f"{value * 2 + 1}|{"yes" if value > 3 else "no"}|'
            '{len([value, value])}")\n'
            'print(f"hello " f"{value}")\n'
        )
        self.assertEqual(run(source), "9|yes|2\nhello 4\n")

    def test_escaped_braces_around_interpolation(self):
        self.assertEqual(run('name = "world"\nprint(f"{{{name}}}")\n'), "{world}\n")

    def test_multiline_and_nested_fstrings(self):
        source = (
            'name = "world"\n'
            'text = f"""hello\n{name}\n"""\n'
            'print(text, end="")\n'
            "print(f\"outer {f'inner {len(name)}'}\")\n"
        )
        self.assertEqual(run(source), "hello\nworld\nouter inner 5\n")

    def test_closure_names_resolve_normally(self):
        source = (
            "def make():\n"
            '    value = "captured"\n'
            "    def read():\n"
            '        return f"value={value}"\n'
            "    return read\n"
            "print(make()())\n"
        )
        self.assertEqual(run(source), "value=captured\n")

    def test_interpolations_evaluate_once_from_left_to_right(self):
        source = (
            "calls = []\n"
            "def mark(value):\n"
            "    calls.append(value)\n"
            "    return value\n"
            'text = f"{mark(1)}-{mark(2)}-{mark(3)}"\n'
            "print(text)\n"
            "print(calls)\n"
        )
        self.assertEqual(run(source), "1-2-3\n[1, 2, 3]\n")

    def test_exception_restores_handler_stack_depth(self):
        source = (
            "try:\n"
            '    text = f"prefix{1 / 0}"\n'
            "except zero_division:\n"
            '    text = "caught"\n'
            "print(text)\n"
        )
        self.assertEqual(run(source), "caught\n")

    def test_conversions_and_format_specs_are_rejected_for_now(self):
        cases = {
            'f"{value!s}"': "f-string conversions are not supported yet",
            'f"{value!r}"': "f-string conversions are not supported yet",
            'f"{value!a}"': "f-string conversions are not supported yet",
            'f"{value=}"': "f-string conversions are not supported yet",
            'f"{value:>3}"': "f-string format specs are not supported yet",
            'f"{value:{width}}"': "f-string format specs are not supported yet",
        }
        for source, message in cases.items():
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    compile_source(source, "fstring.sericite")
                self.assertEqual(ctx.exception.kind, "syntax_error")
                self.assertEqual(ctx.exception.message, message)
                self.assertEqual(ctx.exception.filename, "fstring.sericite")
                self.assertEqual(ctx.exception.line, 1)
                self.assertIsNotNone(ctx.exception.column)


class FStringAccountingTests(unittest.TestCase):
    def test_final_string_size_limit(self):
        engine = SericiteEngine(SericiteLimits(max_string_bytes=7))
        vm = engine.create_root("result = f\"ab{'xyz'}cd\"")
        vm.run()
        self.assertEqual(vm.snapshot()["locals"]["result"], "abxyzcd")

        engine = SericiteEngine(SericiteLimits(max_string_bytes=6))
        vm = engine.create_root("result = f\"ab{'xyz'}cd\"")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_intermediate_render_size_limit(self):
        engine = SericiteEngine(SericiteLimits(max_string_bytes=4))
        vm = engine.create_root('result = f"{[1, 2]}"')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_work_and_both_string_allocations_scale_with_size(self):
        counts = {}
        for size in (10, 1000):
            engine = SericiteEngine()
            checkpoints = []
            text = "x" * size
            vm = engine.create_root(
                "value = make_value()\n"
                "checkpoint()\n"
                'result = f"pre{value}post"\n'
                "checkpoint()",
                functions={
                    "make_value": lambda text=text: text,
                    "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                        checkpoints.append(
                            (
                                engine._contexts[0].instruction_count,
                                engine._contexts[0].alloc_bytes,
                            )
                        )
                    ),
                },
            )
            vm.run()
            result = engine._contexts[0].frames[0].locals["result"]
            work = checkpoints[1][0] - checkpoints[0][0]
            allocation = checkpoints[1][1] - checkpoints[0][1]
            counts[size] = work
            self.assertGreaterEqual(work, size // 64)
            self.assertEqual(allocation, len(text) * 4 + len(result) * 4 + 8)
        self.assertGreater(counts[1000], counts[10])

    def test_child_vm_string_limit_is_enforced(self):
        source = (
            'sub = VM("result = f\\"ab{\'cdef\'}\\"", max_string_bytes=4)\n'
            "try:\n"
            "    sub.run()\n"
            "except resource_exhausted:\n"
            '    print("caught")\n'
        )
        self.assertEqual(run(source), "caught\n")


if __name__ == "__main__":
    unittest.main()
