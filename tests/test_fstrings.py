import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


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

    def test_str_and_repr_conversions(self):
        source = (
            'text = "hello"\n'
            "items = [text, 1]\n"
            'print(f"{text!s}|{text!r}")\n'
            'print(f"{items!s}")\n'
            'print(f"{items!r}")\n'
        )
        self.assertEqual(run(source), "hello|'hello'\n['hello', 1]\n['hello', 1]\n")

    def test_repr_conversion_preserves_safe_container_rendering(self):
        self.assertEqual(
            run('items = [1]\nprint(f"{[items, items]!r}")\n'), "[[1], [...]]\n"
        )

    def test_ascii_conversion_escapes_non_ascii_recursively(self):
        source = 'text = "hé你好😀"\nprint(f"{text!a}")\nprint(f"{[text]!a}")\nprint(f"{text!r}")\n'
        escaped = r"'h\xe9\u4f60\u597d\U0001f600'"
        self.assertEqual(run(source), f"{escaped}\n[{escaped}]\n'hé你好😀'\n")

    def test_debug_form_uses_repr_and_allows_explicit_conversion(self):
        source = (
            'name = "world"\n'
            "number = 3\n"
            'print(f"{name=}")\n'
            'print(f"{number + 1=}")\n'
            'print(f"{name = }")\n'
            'print(f"{name=!s}")\n'
            'print(f"{name=!a}")\n'
        )
        self.assertEqual(
            run(source),
            "name='world'\nnumber + 1=4\nname = 'world'\nname=world\nname='world'\n",
        )

    def test_dynamic_width_precision_type_and_debug_form(self):
        source = (
            "value = 3.14159\n"
            "width = 10\n"
            "precision = 2\n"
            'kind = "f"\n'
            'print(f"{value:{width}.{precision}{kind}}")\n'
            'base = "x"\n'
            'print(f"{255:{base}}")\n'
            'name = "hello"\n'
            'print(f"{name=:>{width}}")\n'
        )
        self.assertEqual(run(source), "      3.14\nff\nname=     hello\n")

    def test_dynamic_spec_supports_nested_fstrings_and_expressions(self):
        source = (
            "width = 8\n"
            "print(f\"{'abc':{f'>{width}'}}\")\n"
            "print(f\"{255:{'#06' + 'x'}}\")\n"
            "print(f\"{'é':{4!s}}\")\n"
        )
        self.assertEqual(run(source), "     abc\n0x00ff\né   \n")

    def test_dynamic_spec_evaluates_once_after_the_target(self):
        source = (
            "calls = []\n"
            "def mark(value):\n"
            "    calls.append(value)\n"
            "    return value\n"
            'result = f"{mark(3.14159):{mark(10)}.{mark(2)}f}"\n'
            "print(result)\n"
            "print(calls)\n"
        )
        self.assertEqual(run(source), "      3.14\n[3.14159, 10, 2]\n")

    def test_dynamic_spec_error_restores_stack_and_preserves_order(self):
        source = (
            "calls = []\n"
            "def target():\n"
            '    calls.append("target")\n'
            "    return 1.0\n"
            "def bad_spec():\n"
            '    calls.append("spec")\n'
            "    return 1 / 0\n"
            "try:\n"
            '    text = f"prefix{target():{bad_spec()}d}"\n'
            "except zero_division:\n"
            '    text = "caught"\n'
            "print(text)\n"
            "print(calls)\n"
        )
        self.assertEqual(run(source), "caught\n['target', 'spec']\n")


class FStringFormatSpecTests(unittest.TestCase):
    def test_string_alignment_fill_width_and_precision(self):
        source = (
            'text = "abc"\n'
            'print(f"{text:>6}|{text:<6}|{text:^6}|{text:.2}|{text:*>5}")\n'
        )
        self.assertEqual(run(source), "   abc|abc   | abc  |ab|**abc\n")

    def test_integer_bases_padding_sign_character_and_grouping(self):
        source = (
            "value = 255\n"
            'print(f"{value:d}|{value:#x}|{value:#X}|{value:#b}|{value:#o}")\n'
            'print(f"{value:08d}|{value:+06d}|{65:c}")\n'
            'print(f"{1234567:,d}|{1234567:_d}")\n'
        )
        self.assertEqual(
            run(source),
            "255|0xff|0XFF|0b11111111|0o377\n00000255|+00255|A\n1,234,567|1_234_567\n",
        )

    def test_float_precision_scientific_general_and_percent(self):
        source = (
            "value = 3.14159\n"
            'print(f"{value:.2f}|{value:10.3f}|{value:.1e}|{value:.3g}")\n'
            'print(f"{0.125:.1%}|{1.25:.2}")\n'
        )
        self.assertEqual(run(source), "3.14|     3.142|3.1e+00|3.14\n12.5%|1.2\n")

    def test_integer_can_use_float_presentation_types(self):
        self.assertEqual(
            run('print(f"{1:.2f}|{1:e}|{1:%}")\n'), "1.00|1.000000e+00|100.000000%\n"
        )

    def test_conversions_are_applied_before_string_formatting(self):
        source = (
            'name = "hello"\n'
            'print(f"{name!r:>9}|{name!a:*>9}|{[1, 2]!s:>8}")\n'
            'print(f"{name=:.3s}")\n'
            'print(f"{name=:>9}")\n'
        )
        self.assertEqual(
            run(source),
            "  'hello'|**'hello'|  [1, 2]\nname=hel\nname=    hello\n",
        )

    def test_empty_spec_preserves_normal_conversion(self):
        self.assertEqual(
            run("print(f\"{[1, 2]:}|{True:}|{'x'!r:}\")\n"),
            "[1, 2]|True|'x'\n",
        )

    def test_invalid_specs_have_stable_sericite_errors(self):
        cases = {
            'f"{1:.}"': "conversion_error",
            'f"{1:>3xx}"': "conversion_error",
            'f"{1:.2}"': "conversion_error",
            "f\"{'x':05d}\"": "conversion_error",
            'f"{1.5:d}"': "type_error",
            'f"{1:s}"': "type_error",
            'f"{[1]:>3}"': "type_error",
            'f"{True:>3}"': "type_error",
        }
        for source, kind in cases.items():
            with self.subTest(source=source):
                engine = SericiteEngine()
                vm = engine.create_root(f"result = {source}")
                with self.assertRaises(SericiteError) as ctx:
                    vm.run()
                self.assertEqual(ctx.exception.kind, kind)

    def test_format_error_restores_handler_stack_depth(self):
        source = (
            "try:\n"
            '    text = f"prefix{1:.}"\n'
            "except conversion_error:\n"
            '    text = "caught"\n'
            "print(text)\n"
        )
        self.assertEqual(run(source), "caught\n")


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

    def test_ascii_result_limit_includes_escapes(self):
        engine = SericiteEngine(SericiteLimits(max_string_bytes=6))
        vm = engine.create_root("result = f\"{'é'!a}\"")
        vm.run()
        self.assertEqual(vm.snapshot()["locals"]["result"], r"'\xe9'")

        engine = SericiteEngine(SericiteLimits(max_string_bytes=5))
        vm = engine.create_root("result = f\"{'é'!a}\"")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_ascii_allocation_uses_expanded_lengths(self):
        engine = SericiteEngine()
        checkpoints = []
        vm = engine.create_root(
            "value = make_value()\n"
            "checkpoint()\n"
            'result = f"pre{value!a}post"\n'
            "checkpoint()",
            functions={
                "make_value": lambda: "é",
                "checkpoint": lambda: checkpoints.append(
                    (
                        engine._contexts[0].instruction_count,
                        engine._contexts[0].alloc_bytes,
                    )
                ),
            },
        )
        vm.run()
        result = engine._contexts[0].frames[0].locals["result"]
        allocation = checkpoints[1][1] - checkpoints[0][1]
        self.assertEqual(result, r"pre'\xe9'post")
        self.assertEqual(allocation, len(r"'\xe9'") * 4 + len(result) * 4 + 8)

    def test_format_width_and_precision_limits(self):
        sources = (
            'result = f"{1:6d}"',
            'result = f"{1.0:.6f}"',
            'result = f"{1:999999999999999999999999d}"',
            'result = f"{1.0:.999999999999999999999999f}"',
            'width = 6\nresult = f"{1:{width}d}"',
            'precision = 6\nresult = f"{1.0:.{precision}f}"',
        )
        for source in sources:
            with self.subTest(source=source):
                engine = SericiteEngine(SericiteLimits(max_string_bytes=5))
                vm = engine.create_root(source)
                with self.assertRaises(SericiteError) as ctx:
                    vm.run()
                self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_format_result_size_boundary(self):
        engine = SericiteEngine(SericiteLimits(max_string_bytes=6))
        vm = engine.create_root('result = f"{255:#06x}"')
        vm.run()
        self.assertEqual(vm.snapshot()["locals"]["result"], "0x00ff")

        engine = SericiteEngine(SericiteLimits(max_string_bytes=5))
        vm = engine.create_root('result = f"{255:#06x}"')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_common_formats_fit_their_exact_result_limit(self):
        cases = (
            ('f"{1:d}"', "1"),
            ('f"{1.0:f}"', "1.000000"),
            ('f"{1:e}"', "1.000000e+00"),
            ('f"{1.25:.2}"', "1.2"),
            ('f"{0.00123:.0g}"', "0.001"),
        )
        for expression, expected in cases:
            with self.subTest(expression=expression):
                limits = SericiteLimits(max_string_bytes=len(expected))
                vm = SericiteEngine(limits).create_root(f"result = {expression}")
                vm.run()
                self.assertEqual(vm.snapshot()["locals"]["result"], expected)

    def test_format_work_and_allocation_scale_with_width(self):
        counts = {}
        for width in (10, 1000):
            engine = SericiteEngine()
            checkpoints = []
            vm = engine.create_root(
                "value = make_value()\n"
                "checkpoint()\n"
                f'result = f"{{value:{width}d}}"\n'
                "checkpoint()",
                functions={
                    "make_value": lambda: 255,
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
            counts[width] = work
            self.assertEqual(len(result), width)
            self.assertEqual(allocation, width * 8 + 8)
        self.assertGreater(counts[1000], counts[10])

    def test_dynamic_spec_construction_and_result_are_metered(self):
        counts = {}
        for width in (10, 1000):
            engine = SericiteEngine()
            checkpoints = []
            vm = engine.create_root(
                "value = make_value()\n"
                "width = make_width()\n"
                "checkpoint()\n"
                'result = f"{value:{width}d}"\n'
                "checkpoint()",
                functions={
                    "make_value": lambda: 255,
                    "make_width": lambda width=width: width,
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
            counts[width] = work
            self.assertEqual(len(result), width)
            spec_length = len(str(width)) + 1
            expected = len(str(width)) * 4 + spec_length * 4 + width * 8 + 8
            self.assertEqual(allocation, expected)
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
