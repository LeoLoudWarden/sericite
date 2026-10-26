import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


def run(source, inputs=None, limits=None, functions=None):
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source, functions=functions)
    return vm.run(inputs)


class SecurityQuotaTests(unittest.TestCase):
    def test_string_concat_size_limit(self):
        source = 's = "x"\ni = 0\nwhile i < 30:\n    s = s + s\n    i = i + 1\n'
        with self.assertRaises(SericiteError) as ctx:
            run(source)
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_str_builtin_size_limit(self):
        limits = SericiteLimits(max_string_bytes=100)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root("x = str(range(50))\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_int_growth_limit(self):
        source = "x = 2\ni = 0\nwhile i < 20:\n    x = x * x\n    i = i + 1\n"
        with self.assertRaises(SericiteError) as ctx:
            run(source)
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_int_constant_limit(self):
        limits = SericiteLimits(max_int_bits=32)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root("x = 99999999999\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_int_conversion_limit(self):
        limits = SericiteLimits(max_int_bits=32)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root('x = int("99999999999")\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_ordered_string_comparison_charges_potential_scan(self):
        counts = {}
        for size in (100, 1000):
            engine = SericiteEngine()
            vm = engine.create_root(
                "result = left() < right()\n",
                functions={
                    "left": lambda size=size: "a" * size + "x",
                    "right": lambda size=size: "a" * size + "y",
                },
            )
            vm.run()
            counts[size] = vm.snapshot()["instruction_count"]
        self.assertGreaterEqual(counts[1000] - counts[100], 900)

    def test_ordered_string_comparison_enforces_tight_instruction_limit(self):
        limits = SericiteLimits(max_instructions=100)
        with self.assertRaises(SericiteError) as ctx:
            run(
                "result = left() < right()\n",
                limits=limits,
                functions={
                    "left": lambda: "a" * 10_000 + "x",
                    "right": lambda: "a" * 10_000 + "y",
                },
            )
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_string_and_dict_iterator_creation_charges_copy_work(self):
        for kind in ("str", "dict"):
            counts = {}
            for size in (100, 1000):
                engine = SericiteEngine()
                vm = engine.create_root(
                    "value = get()\nfor item in value:\n    break\n",
                    functions={
                        "get": lambda kind=kind, size=size: (
                            "x" * size if kind == "str" else {i: i for i in range(size)}
                        )
                    },
                )
                vm.run()
                counts[size] = vm.snapshot()["instruction_count"]
            with self.subTest(kind=kind):
                self.assertGreaterEqual(counts[1000] - counts[100], 900)

    def test_iterator_creation_enforces_limit_before_copy(self):
        limits = SericiteLimits(max_instructions=100)
        for kind in ("str", "dict"):
            with self.subTest(kind=kind):
                with self.assertRaises(SericiteError) as ctx:
                    run(
                        "value = get()\nfor item in value:\n    break\n",
                        limits=limits,
                        functions={
                            "get": lambda kind=kind: (
                                "x" * 10_000
                                if kind == "str"
                                else {i: i for i in range(10_000)}
                            )
                        },
                    )
                self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_deep_expression_is_validation_error(self):
        source = "x = " + "1+1" * 5000 + "\n"
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root(source)
        self.assertEqual(ctx.exception.kind, "validation_error")

    def test_cyclic_list_prints_safely(self):
        source = "l = [None]\nl[0] = l\nprint(l)\nprint(l == l)\n"
        self.assertEqual(run(source), "[[...]]\nTrue\n")

    def test_cyclic_list_snapshot_safe(self):
        engine = SericiteEngine()
        vm = engine.create_root("l = [None]\nl[0] = l\nx = 1\n")
        vm.run()
        snapshot = vm.snapshot()
        self.assertEqual(snapshot["locals"]["l"], ["[...]"])

    def test_cyclic_foreign_equality_contained(self):
        # cyclic-structure comparison converges via (id, id) memoization to a coinductive equality, no longer exhausting recursion
        source = "a = [None]\na[0] = a\nb = [None]\nb[0] = b\nprint(a == b)\n"
        self.assertEqual(run(source), "True\n")

    def test_dict_equality_charges_key_scan_before_early_value_mismatch(self):
        counts = {}
        for size in (100, 1000):
            engine = SericiteEngine()
            vm = engine.create_root(
                "result = left() == right()\n",
                functions={
                    "left": lambda size=size: {i: 0 for i in range(size)},
                    "right": lambda size=size: {i: 1 for i in range(size)},
                },
            )
            vm.run()
            counts[size] = vm.snapshot()["instruction_count"]
        self.assertGreaterEqual(counts[1000] - counts[100], 900)

    def test_dict_key_scan_enforces_limit_before_comparison(self):
        limits = SericiteLimits(max_instructions=100)
        for source in (
            "result = left() == right()\n",
            "result = [left()] == [right()]\n",
        ):
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    run(
                        source,
                        limits=limits,
                        functions={
                            "left": lambda: {i: 0 for i in range(10_000)},
                            "right": lambda: {i: 1 for i in range(10_000)},
                        },
                    )
                self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_float_string_conversion_charges_input_scan(self):
        counts = {}
        for size in (100, 1000):
            engine = SericiteEngine()
            vm = engine.create_root(
                "result = float(text())\n",
                functions={"text": lambda size=size: "0." + "1" * size},
            )
            vm.run()
            counts[size] = vm.snapshot()["instruction_count"]
        self.assertGreaterEqual(counts[1000] - counts[100], 900)

    def test_float_string_conversion_enforces_limit_before_parsing(self):
        limits = SericiteLimits(max_instructions=100)
        with self.assertRaises(SericiteError) as ctx:
            run(
                "result = float(text())\n",
                limits=limits,
                functions={"text": lambda: "0." + "1" * 10_000},
            )
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_float_conversion_error_truncates_long_input(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            "try:\n"
            "    float(text())\n"
            "except conversion_error as error:\n"
            "    result = error\n",
            functions={"text": lambda: "x" * 10_000},
        )
        vm.run()
        message = vm.snapshot()["locals"]["result"]
        self.assertLess(len(message), 200)
        self.assertIn("...", message)

    def test_ffi_deeply_nested_argument_rejected(self):
        value = 1
        for _ in range(100):
            value = [value]
        nested_repr = "[" * 100 + "1" + "]" * 100
        source = f"probe({nested_repr})\n"
        with self.assertRaises(SericiteError) as ctx:
            run(source, functions={"probe": lambda v: None})
        self.assertEqual(ctx.exception.kind, "ffi_error")

    def test_ffi_huge_string_result_rejected(self):
        source = 'try:\n    big()\nexcept ffi_error:\n    print("blocked")\n'
        output = run(source, functions={"big": lambda: "x" * 10_000_000})
        self.assertEqual(output, "blocked\n")

    def test_shared_dag_snapshot_is_bounded(self):
        source = (
            "value = [0]\n"
            "i = 0\n"
            "while i < 20:\n"
            "    value = [value, value]\n"
            "    i = i + 1\n"
        )
        vm = SericiteEngine().create_root(source)
        vm.run()
        rendered = str(vm.snapshot()["locals"]["value"])
        self.assertLess(len(rendered), 1000)
        self.assertIn("[...]", rendered)

    def test_shared_dag_print_is_bounded(self):
        source = (
            "value = [0]\n"
            "i = 0\n"
            "while i < 20:\n"
            "    value = [value, value]\n"
            "    i = i + 1\n"
            "print(value)\n"
        )
        output = run(source)
        self.assertLess(len(output), 1000)
        self.assertIn("[...]", output)

    def test_shared_dag_print_checks_output_quota_during_rendering(self):
        source = (
            "value = [0]\n"
            "i = 0\n"
            "while i < 20:\n"
            "    value = [value, value]\n"
            "    i = i + 1\n"
            "print(value)\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            run(source, limits=SericiteLimits(max_output_bytes=1))
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_snapshot_node_budget_covers_distinct_nodes(self):
        vm = SericiteEngine().create_root("value = range(10001)\n")
        vm.run()
        rendered = str(vm.snapshot()["locals"]["value"])
        self.assertLess(len(rendered), 100_000)
        self.assertIn("<max nodes>", rendered)

    def test_ffi_result_enforces_list_size(self):
        limits = SericiteLimits(max_list_size=2)
        with self.assertRaises(SericiteError) as ctx:
            run(
                "value = get()\n",
                limits=limits,
                functions={"get": lambda: list(range(10))},
            )
        self.assertEqual(ctx.exception.kind, "ffi_error")

    def test_ffi_result_enforces_dict_size(self):
        limits = SericiteLimits(max_dict_size=2)
        with self.assertRaises(SericiteError) as ctx:
            run(
                "value = get()\n",
                limits=limits,
                functions={"get": lambda: {i: i for i in range(10)}},
            )
        self.assertEqual(ctx.exception.kind, "ffi_error")

    def test_ffi_result_enforces_integer_bits(self):
        limits = SericiteLimits(max_int_bits=64)
        with self.assertRaises(SericiteError) as ctx:
            run("value = get()\n", limits=limits, functions={"get": lambda: 1 << 1000})
        self.assertEqual(ctx.exception.kind, "ffi_error")

    def test_ffi_result_string_charges_actual_memory(self):
        limits = SericiteLimits(max_total_bytes=1000)
        with self.assertRaises(SericiteError) as ctx:
            run("value = get()\n", limits=limits, functions={"get": lambda: "x" * 1000})
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_ffi_result_allocation_uses_container_and_key_sizes(self):
        cases = (("abc", 12), ([1, 2], 32), ({"a": 1}, 28))
        for value, expected in cases:
            with self.subTest(value=value):
                engine = SericiteEngine()
                engine.create_root(
                    "value = get()\n", functions={"get": lambda value=value: value}
                ).run()
                self.assertEqual(engine._contexts[0].alloc_bytes, expected)

    def test_deep_structure_snapshot_no_recursion_leak(self):
        source = "x = 1\ni = 0\nwhile i < 2000:\n    x = [x]\n    i = i + 1\nprint(1)\n"
        engine = SericiteEngine()
        vm = engine.create_root(source)
        self.assertEqual(vm.run(), "1\n")
        snapshot = vm.snapshot()
        self.assertIn("<max depth>", str(snapshot["locals"]["x"]))

    def test_parse_level_deep_chain_is_validation_error(self):
        source = "x = " + "1+" * 50000 + "1\n"
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root(source)
        self.assertEqual(ctx.exception.kind, "validation_error")

    def test_total_memory_accounting(self):
        limits = SericiteLimits(max_total_bytes=200_000)
        engine = SericiteEngine(limits=limits)
        source = (
            'pad = "a"\n'
            "i = 0\n"
            "while i < 12:\n"
            "    pad = pad + pad\n"
            "    i = i + 1\n"
            "d = {}\n"
            "j = 0\n"
            "while j < 100:\n"
            "    d[str(j)] = pad + str(j)\n"
            "    j = j + 1\n"
        )
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_overflow_becomes_catchable_conversion_error(self):
        limits = SericiteLimits(max_int_bits=10000)
        source = (
            "x = 2\n"
            "for i in range(13):\n"
            "    x = x * x\n"
            "try:\n"
            "    y = x / 1\n"
            "except conversion_error:\n"
            '    print("overflow caught")\n'
        )
        engine = SericiteEngine(limits=limits)
        self.assertEqual(engine.create_root(source).run(), "overflow caught\n")

    def test_input_length_limited(self):
        limits = SericiteLimits(max_string_bytes=10)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root("x = input()\n", inputs=["x" * 100])
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_source_length_limited(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("x = 1\n" + "# pad\n" * 800_000)
        self.assertEqual(ctx.exception.kind, "validation_error")

    def test_alloc_charges_ancestors(self):
        child = 's = "a"\nfor i in range(16):\n    s = s + s\n'
        source = (
            "sub = VM(" + repr(child) + ", max_total_bytes=10_000_000)\nsub.run()\n"
        )
        limits = SericiteLimits(max_total_bytes=100_000)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")


class ForLoopTests(unittest.TestCase):
    def test_for_over_list(self):
        source = "t = 0\nfor x in [1, 2, 3]:\n    t = t + x\nprint(t)\n"
        self.assertEqual(run(source), "6\n")

    def test_for_over_dict_keys(self):
        source = 'for k in {"a": 1, "b": 2}:\n    print(k)\n'
        self.assertEqual(run(source), "a\nb\n")

    def test_for_over_string(self):
        source = 'for ch in "ab":\n    print(ch)\n'
        self.assertEqual(run(source), "a\nb\n")

    def test_for_over_range(self):
        source = "for i in range(3):\n    print(i)\n"
        self.assertEqual(run(source), "0\n1\n2\n")

    def test_for_else_without_break(self):
        source = 'for i in range(2):\n    print(i)\nelse:\n    print("done")\n'
        self.assertEqual(run(source), "0\n1\ndone\n")

    def test_for_else_with_break(self):
        source = (
            "for i in range(5):\n"
            "    if i == 1:\n"
            "        break\n"
            "else:\n"
            '    print("done")\n'
            'print("after")\n'
        )
        self.assertEqual(run(source), "after\n")

    def test_for_continue(self):
        source = (
            "for i in range(4):\n    if i % 2 == 0:\n        continue\n    print(i)\n"
        )
        self.assertEqual(run(source), "1\n3\n")

    def test_nested_for(self):
        source = "for a in [1, 2]:\n    for b in [10, 20]:\n        print(a + b)\n"
        self.assertEqual(run(source), "11\n21\n12\n22\n")

    def test_for_not_iterable(self):
        engine = SericiteEngine()
        vm = engine.create_root("for x in 5:\n    print(x)\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_for_tuple_target_rejected(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("for a, b in [1]:\n    pass\n")
        self.assertEqual(ctx.exception.kind, "validation_error")

    def test_while_else(self):
        source = 'i = 0\nwhile i < 2:\n    i = i + 1\nelse:\n    print("done")\n'
        self.assertEqual(run(source), "done\n")

    def test_while_else_skipped_by_break(self):
        source = 'while True:\n    break\nelse:\n    print("done")\nprint("after")\n'
        self.assertEqual(run(source), "after\n")

    def test_snapshot_hides_for_internals(self):
        engine = SericiteEngine()
        vm = engine.create_root("for x in [1]:\n    y = x\n")
        vm.step()
        vm.step()
        for name in vm.snapshot()["locals"]:
            self.assertFalse(name.startswith("$"))


class FinallyTests(unittest.TestCase):
    def test_finally_on_normal_path(self):
        source = 'try:\n    x = 1\nfinally:\n    print("f")\n'
        self.assertEqual(run(source), "f\n")

    def test_finally_on_exception(self):
        source = (
            "try:\n"
            "    try:\n"
            "        x = 1 / 0\n"
            "    finally:\n"
            '        print("f")\n'
            "except zero_division:\n"
            '    print("caught")\n'
        )
        self.assertEqual(run(source), "f\ncaught\n")

    def test_finally_with_return(self):
        source = (
            "def f():\n"
            "    try:\n"
            '        return "inner"\n'
            "    finally:\n"
            '        print("cleanup")\n'
            "print(f())\n"
        )
        self.assertEqual(run(source), "cleanup\ninner\n")

    def test_finally_with_break_and_continue(self):
        source = (
            "for i in range(5):\n"
            "    try:\n"
            "        if i == 1:\n"
            "            continue\n"
            "        if i == 3:\n"
            "            break\n"
            "    finally:\n"
            "        print(i)\n"
        )
        self.assertEqual(run(source), "0\n1\n2\n3\n")

    def test_finally_reraises_original_kind(self):
        engine = SericiteEngine()
        vm = engine.create_root("try:\n    x = missing\nfinally:\n    y = 1\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "name_error")

    def test_try_except_else(self):
        source = (
            "try:\n"
            "    x = 1\n"
            "except:\n"
            '    print("caught")\n'
            "else:\n"
            '    print("no error")\n'
            "finally:\n"
            '    print("f")\n'
        )
        self.assertEqual(run(source), "no error\nf\n")

    def test_nested_finally_order(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            "try:\n"
            "    try:\n"
            '        raise "x"\n'
            "    finally:\n"
            '        print("inner")\n'
            "finally:\n"
            '    print("outer")\n'
        )
        with self.assertRaises(SericiteError):
            vm.run()
        self.assertEqual(vm.stdout(), "inner\nouter\n")


class RaiseTests(unittest.TestCase):
    def test_raise_message_catchable(self):
        source = (
            "try:\n"
            '    raise "custom boom"\n'
            "except raise_error as e:\n"
            '    print("caught: " + e)\n'
        )
        self.assertEqual(run(source), "caught: custom boom\n")

    def test_bare_raise_reraises(self):
        source = (
            "try:\n"
            "    try:\n"
            '        raise "inner"\n'
            "    except raise_error:\n"
            "        raise\n"
            "except raise_error as e:\n"
            '    print("got: " + e)\n'
        )
        self.assertEqual(run(source), "got: inner\n")

    def test_raise_non_string_rejected(self):
        engine = SericiteEngine()
        vm = engine.create_root("raise 42\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_bare_raise_without_active_error(self):
        engine = SericiteEngine()
        vm = engine.create_root("raise\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "raise_error")

    def test_raise_crosses_functions(self):
        source = (
            "def f():\n"
            '    raise "from f"\n'
            "try:\n"
            "    f()\n"
            "except raise_error as e:\n"
            "    print(e)\n"
        )
        self.assertEqual(run(source), "from f\n")


class DefaultParamTests(unittest.TestCase):
    def test_defaults(self):
        source = (
            "def f(a, b=2, c=3):\n"
            "    return a * 100 + b * 10 + c\n"
            "print(f(1))\n"
            "print(f(1, 5))\n"
            "print(f(1, 5, 9))\n"
            "print(f(1, c=7))\n"
        )
        self.assertEqual(run(source), "123\n153\n159\n127\n")

    def test_missing_required_still_arity_error(self):
        engine = SericiteEngine()
        vm = engine.create_root("def f(a, b=2):\n    return a\nprint(f())\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "arity_error")

    def test_defaults_evaluated_at_def_time(self):
        source = "x = 10\ndef f(a=x):\n    return a\nx = 20\nprint(f())\n"
        self.assertEqual(run(source), "10\n")

    def test_granted_function_with_defaults(self):
        source = (
            "def f(a, b=5):\n"
            "    return a + b\n"
            'sub = VM("print(f(1))\\nprint(f(1, 10))\\n", functions={"f": f})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "6\n11\n\n")


class PassTests(unittest.TestCase):
    def test_pass_everywhere(self):
        source = (
            "def f():\n"
            "    pass\n"
            "f()\n"
            "if True:\n"
            "    pass\n"
            "while False:\n"
            "    pass\n"
            'print("ok")\n'
        )
        self.assertEqual(run(source), "ok\n")


class TernaryTests(unittest.TestCase):
    def test_basic(self):
        source = "x = 1 if True else 2\ny = 1 if False else 2\nprint(x, y)\n"
        self.assertEqual(run(source), "1 2\n")

    def test_short_circuit(self):
        source = (
            "def boom():\n"
            '    print("boom")\n'
            "    return 0\n"
            "a = 1 if True else boom()\n"
            "b = boom() if False else 2\n"
            "print(a, b)\n"
        )
        self.assertEqual(run(source), "1 2\n")

    def test_nested_and_in_call(self):
        source = (
            "def f(n):\n"
            '    return "neg" if n < 0 else ("zero" if n == 0 else "pos")\n'
            "print(f(-1), f(0), f(3))\n"
            "d = {}\n"
            'print(d["k"] if "k" in d else "default")\n'
        )
        self.assertEqual(run(source), "neg zero pos\ndefault\n")


class ExternalAuditTests(unittest.TestCase):
    """Regression tests for items adopted from the external security audit."""

    def test_container_membership_charges_work(self):
        source = (
            "big = range(100000)\n"
            "for i in range(20):\n"
            "    if 99999 in big:\n"
            "        pass\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            run(source)
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_container_equality_charges_work(self):
        source = (
            "a = range(100000)\n"
            "b = range(100000)\n"
            "for i in range(20):\n"
            "    if a == b:\n"
            "        pass\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            run(source)
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_compile_work_charged_to_parent(self):
        big_source = "x = 1\n" * 100000
        source = "sub = VM(" + repr(big_source) + ")\n"
        limits = SericiteLimits(max_instructions=100)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_total_vms_limit(self):
        limits = SericiteLimits(max_total_vms=3)
        engine = SericiteEngine(limits=limits)
        source = 'for i in range(10):\n    sub = VM("x = 1\\n")\n'
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_child_source_compilation_is_charged_near_linearly(self):
        limits = SericiteLimits(max_instructions=100)
        engine = SericiteEngine(limits=limits)
        inner = "pass\n" * 100
        vm = engine.create_root("sub = VM(" + repr(inner) + ")\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_vfs_write_charges_alloc(self):
        limits = SericiteLimits(max_total_bytes=1000)
        engine = SericiteEngine(limits=limits)
        text = "x" * 200
        vm = engine.create_root(f'write_file("/a.txt", "{text}")\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_string_constant_size_checked(self):
        limits = SericiteLimits(max_string_bytes=10)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root('x = "this string is way too long"\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_stdout_method_charges_caller(self):
        limits = SericiteLimits(max_total_bytes=1000)
        engine = SericiteEngine(limits=limits)
        source = (
            'sub = VM("print(123)")\n'
            "sub.run()\n"
            "i = 0\n"
            "while i < 200:\n"
            "    s = sub.stdout()\n"
            "    i = i + 1\n"
        )
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_for_over_string_charges_alloc(self):
        limits = SericiteLimits(max_total_bytes=10_000)
        engine = SericiteEngine(limits=limits)
        source = 's = "x"\nfor i in range(10):\n    s = s + s\nfor c in s:\n    pass\n'
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_nan_to_int_is_conversion_error(self):
        source = (
            "try:\n"
            '    x = int(float("nan"))\n'
            "except conversion_error:\n"
            '    print("caught")\n'
        )
        self.assertEqual(run(source), "caught\n")

    def test_reentrancy_guard(self):
        engine = SericiteEngine()
        holder = {}

        def provider():
            holder["vm"].step()
            return "x"

        vm = engine.create_root("x = input()\n", input_provider=provider)
        holder["vm"] = vm
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertIn("already running", str(ctx.exception))

    def test_def_cannot_shadow_builtin(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("def print():\n    pass\n")
        self.assertEqual(ctx.exception.kind, "validation_error")

    def test_multibyte_source_measured_in_bytes(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("x = 1\n" + "# 汉\n" * 1_500_000)
        self.assertEqual(ctx.exception.kind, "validation_error")


if __name__ == "__main__":
    unittest.main()
