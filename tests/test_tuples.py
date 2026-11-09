import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


def run(source, functions=None, limits=None):
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source, functions=functions)
    return vm.run()


def run_error(source, limits=None):
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source)
    with unittest.TestCase().assertRaises(SericiteError) as ctx:
        vm.run()
    return ctx.exception


class TupleValueTests(unittest.TestCase):
    def test_literals_and_safe_rendering(self):
        source = (
            "empty = ()\n"
            "single = (1,)\n"
            "pair = 1, 'x'\n"
            "nested = (empty, single, pair)\n"
            "print(empty, single, pair)\n"
            "print(repr(nested))\n"
            'print(f"{single!r} {pair!s}")\n'
        )
        self.assertEqual(
            run(source),
            "() (1,) (1, 'x')\n((), (1,), (1, 'x'))\n(1,) (1, 'x')\n",
        )

    def test_index_slice_iteration_len_truth_and_membership(self):
        source = (
            "value = (0, 1, 2, 3)\n"
            "print(len(value), value[0], value[-1], value[1:4:2], value[::-1])\n"
            "print(not (), not (0,), 2 in value, 9 not in value)\n"
            "for item in value:\n"
            "    print(item)\n"
        )
        self.assertEqual(
            run(source), "4 0 3 (1, 3) (3, 2, 1, 0)\nTrue False True True\n0\n1\n2\n3\n"
        )

    def test_concat_repeat_and_augmented_repeat(self):
        source = (
            "value = (1, 2)\n"
            "alias = value\n"
            "value *= 2\n"
            "print(value, alias)\n"
            "print((1,) + (2, 3), 2 * (4,), (1,) * 0, (1,) * -2)\n"
        )
        self.assertEqual(
            run(source),
            "(1, 2, 1, 2) (1, 2)\n(1, 2, 3) (4, 4) () ()\n",
        )

    def test_structural_equality_uses_nested_values(self):
        source = (
            "print((1, [2]) == (1, [2]))\n"
            "print((1, 2) == [1, 2], (1, 2) != (1, 3))\n"
            "n = float('nan')\n"
            "print((n,) == (n,))\n"
            "value = (n,)\n"
            "print(value == value)\n"
        )
        self.assertEqual(run(source), "True\nFalse True\nFalse\nTrue\n")

    def test_cycle_and_shared_tuple_rendering(self):
        source = (
            "items = []\n"
            "value = (items,)\n"
            "items.append(value)\n"
            "print(repr(value))\n"
            "shared = (1,)\n"
            "print(repr((shared, shared)))\n"
        )
        self.assertEqual(run(source), "([(...)],)\n((1,), (...))\n")

    def test_immutable_and_not_a_dict_key(self):
        sources = (
            "value = (1,)\nvalue[0] = 2",
            "value = (1,)\nvalue[0] += 2",
            "value = {}\nvalue[(1,)] = 2",
            "print({(1,): 2})",
            "print((1,) < (2,))",
            "print((1,) + [2])",
            "print((1,) * True)",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(run_error(source).kind, "type_error")

    def test_tuple_contract(self):
        source = (
            "def identity(value: tuple) -> tuple:\n"
            "    return value\n"
            "print(identity((1, 2)))\n"
        )
        self.assertEqual(run(source), "(1, 2)\n")
        self.assertEqual(run_error("value: tuple = []\n").kind, "contract_error")
        for source in ("tuple = ()", "value = tuple", "print(tuple())"):
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")


class TupleUnpackingTests(unittest.TestCase):
    def test_assignment_swap_nested_and_chain(self):
        source = (
            "a, b = (1, 2)\n"
            "a, b = b, a\n"
            "x, (y, z) = [3, (4, 5)]\n"
            "first = second, third = (6, 7)\n"
            "() = ()\n"
            "print(a, b, x, y, z, first, second, third)\n"
        )
        self.assertEqual(run(source), "2 1 3 4 5 (6, 7) 6 7\n")

    def test_rhs_is_evaluated_once(self):
        source = (
            "calls = []\n"
            "def value():\n"
            "    calls.append(1)\n"
            "    return (8, 9)\n"
            "a, b = value()\n"
            "print(a, b, len(calls))\n"
        )
        self.assertEqual(run(source), "8 9 1\n")

    def test_for_unpacking_and_all_iterable_rhs_types(self):
        source = (
            "a, b = 'xy'\n"
            "c, d = {'c': 1, 'd': 2}\n"
            "total = 0\n"
            "for first, (second, third) in [(1, (2, 3)), (4, (5, 6))]:\n"
            "    total += first + second + third\n"
            "print(a, b, c, d, total)\n"
        )
        self.assertEqual(run(source), "x y c d 21\n")

    def test_unpacking_updates_closure_cells(self):
        source = (
            "def outer():\n"
            "    value = 0\n"
            "    def read():\n"
            "        return value\n"
            "    (value,) = (7,)\n"
            "    return read\n"
            "print(outer()())\n"
        )
        self.assertEqual(run(source), "7\n")

    def test_length_mismatch_is_catchable_value_error(self):
        source = (
            "for value in [(1,), (1, 2, 3)]:\n"
            "    try:\n"
            "        a, b = value\n"
            "    except value_error as e:\n"
            "        print(e.kind)\n"
            "print('alive')\n"
        )
        self.assertEqual(run(source), "value_error\nvalue_error\nalive\n")

    def test_non_iterable_is_type_error(self):
        self.assertEqual(run_error("a, b = 1").kind, "type_error")

    def test_unsupported_targets_are_compile_time_errors(self):
        sources = (
            "[a, b] = (1, 2)",
            "a, *b = (1, 2, 3)",
            "values = [0]\nvalues[0], b = (1, 2)",
            "for [a, b] in [(1, 2)]:\n    pass",
            "a, b += (1, 2)",
        )
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_unpacking_clears_stale_record_labels(self):
        source = "class P:\n    x: int\nvalue = P(1)\n(value,) = (2,)\nvalue.x\n"
        error = run_error(source)
        self.assertEqual(error.kind, "type_error")
        self.assertNotIn("record P", error.message)


class TupleBoundaryTests(unittest.TestCase):
    def test_ffi_preserves_tuple_and_deep_copies_arguments(self):
        seen = []

        def take(value):
            seen.append(value)
            value[1].append(3)
            return value

        engine = SericiteEngine()
        vm = engine.create_root(
            "original = (1, [2])\nresult = take(original)\nprint(original, result)",
            functions={"take": take},
        )
        self.assertEqual(vm.run(), "(1, [2]) (1, [2, 3])\n")
        self.assertIsInstance(seen[0], tuple)
        self.assertIsInstance(seen[0][1], list)

    def test_ffi_return_tuple_is_copied(self):
        host_items = [2]

        def make():
            return (1, host_items)

        engine = SericiteEngine()
        vm = engine.create_root(
            "value = make()\nvalue[1].append(3)\nprint(value)",
            functions={"make": make},
        )
        self.assertEqual(vm.run(), "(1, [2, 3])\n")
        self.assertEqual(host_items, [2])

    def test_host_and_script_snapshots_preserve_tuples(self):
        engine = SericiteEngine()
        vm = engine.create_root("value = (1, ['x'])")
        vm.run()
        self.assertEqual(vm.snapshot()["locals"]["value"], (1, ["x"]))

        output = run(
            'sub = VM("value = (1, 2)")\n'
            "sub.run()\n"
            'print(sub.snapshot()["locals"]["value"])'
        )
        self.assertEqual(output, "(1, 2)\n")

    def test_granted_function_can_return_tuple_to_child(self):
        output = run(
            "def make():\n"
            "    return (1, [2])\n"
            'sub = VM("value = make()\\nprint(value)", functions={"make": make})\n'
            "print(sub.run(), end='')"
        )
        self.assertEqual(output, "(1, [2])\n")


class TupleUsabilityTests(unittest.TestCase):
    def test_dict_items_is_a_snapshot_of_pairs(self):
        source = (
            "mapping = {'a': 1, 'b': 2}\n"
            "items = mapping.items()\n"
            "mapping['c'] = 3\n"
            "items[0] = ('changed', 9)\n"
            "print(items, mapping)\n"
            "for key, value in mapping.items():\n"
            "    print(key, value)\n"
        )
        self.assertEqual(
            run(source),
            "[('changed', 9), ('b', 2)] {'a': 1, 'b': 2, 'c': 3}\na 1\nb 2\nc 3\n",
        )

    def test_dict_items_bound_method_and_arity(self):
        self.assertEqual(
            run("mapping = {'a': 1}\nitems = mapping.items\nprint(items())"),
            "[('a', 1)]\n",
        )
        self.assertEqual(
            run_error("mapping = {}\nmapping.items(1)").kind, "arity_error"
        )

    def test_dict_items_enforces_result_and_pair_limits(self):
        for source in (
            "mapping = {1: 2}\nmapping.items()",
            "mapping = {1: 2, 3: 4}\nmapping.items()",
        ):
            with self.subTest(source=source):
                error = run_error(source, SericiteLimits(max_list_size=1))
                self.assertEqual(error.kind, "resource_exhausted")
        self.assertEqual(
            run(
                "mapping = {}\nprint(mapping.items())",
                limits=SericiteLimits(max_list_size=0),
            ),
            "[]\n",
        )

    def test_dict_items_charges_list_and_tuple_slots(self):
        engine = SericiteEngine()
        checkpoints = []
        vm = engine.create_root(
            "mapping = {'a': 1, 'b': 2}\ncheckpoint()\n"
            "result = mapping.items()\ncheckpoint()",
            functions={
                "checkpoint": lambda: checkpoints.append(
                    engine._contexts[0].alloc_bytes
                )
            },
        )
        vm.run()
        self.assertEqual(checkpoints[1] - checkpoints[0], 2 * 24 + 8)

    def test_join_accepts_tuples(self):
        source = (
            "print(','.join(('a', 'b', 'c')))\n"
            "print('x'.join(()), 'x'.join(('only',)))\n"
            "join = '-'.join\nprint(join(('a', 'b')))\n"
        )
        self.assertEqual(run(source), "a,b,c\n only\na-b\n")
        self.assertEqual(run_error("print(','.join(('a', 1)))").kind, "type_error")

    def test_partition_and_rpartition(self):
        source = (
            "print('a=b=c'.partition('='))\n"
            "print('a=b=c'.rpartition('='))\n"
            "print('abc'.partition('x'), 'abc'.rpartition('x'))\n"
            "print(''.partition('x'), ''.rpartition('x'))\n"
            "partition = 'a=b'.partition\n"
            "print(partition('='))\n"
            "before, separator, after = 'a=b'.partition('=')\n"
            "print(before, separator, after)\n"
        )
        self.assertEqual(
            run(source),
            "('a', '=', 'b=c')\n"
            "('a=b', '=', 'c')\n"
            "('abc', '', '') ('', '', 'abc')\n"
            "('', '', '') ('', '', '')\n"
            "('a', '=', 'b')\n"
            "a = b\n",
        )

    def test_partition_validation_and_tuple_limit(self):
        cases = (
            ("'a'.partition()", "arity_error"),
            ("'a'.rpartition('x', 'y')", "arity_error"),
            ("'a'.partition(1)", "type_error"),
            ("'a'.rpartition('')", "type_error"),
        )
        for source, kind in cases:
            with self.subTest(source=source):
                self.assertEqual(run_error(source).kind, kind)
        for method in ("partition", "rpartition"):
            with self.subTest(method=method):
                error = run_error(
                    f"print('a=b'.{method}('='))", SericiteLimits(max_list_size=2)
                )
                self.assertEqual(error.kind, "resource_exhausted")

    def test_count_and_index_for_lists_and_tuples(self):
        source = (
            "print([1, [2], 1].count(1), (1, [2], 1).count(1))\n"
            "print([[2], [3]].count([2]), ([2], [3]).count([2]))\n"
            "print([0, 1, 2, 1].index(1), (0, 1, 2, 1).index(1))\n"
            "print([0, 1, 2, 1].index(1, 2), (0, 1, 2, 1).index(1, -1))\n"
            "print([0, 1, 2].index(0, None, 2), (0, 1, 2).index(2, 0, None))\n"
            "n = float('nan')\n"
            "print((n, n).count(n))\n"
        )
        self.assertEqual(run(source), "2 2\n1 1\n1 1\n3 3\n0 2\n0\n")

    def test_index_not_found_is_catchable_value_error(self):
        source = (
            "for value in ([1], (1,)):\n"
            "    try:\n"
            "        value.index(2)\n"
            "    except value_error as e:\n"
            "        print(e.kind)\n"
        )
        self.assertEqual(run(source), "value_error\nvalue_error\n")

    def test_sequence_method_validation_and_closed_attributes(self):
        cases = (
            ("[1].count()", "arity_error"),
            ("(1,).count(1, 2)", "arity_error"),
            ("[1].index()", "arity_error"),
            ("(1,).index(1, 0, 1, 2)", "arity_error"),
            ("[1].index(1, False)", "type_error"),
            ("(1,).index(1, 0, 'x')", "type_error"),
            ("(1,).append(2)", "attribute_error"),
            ("(1,).pop()", "attribute_error"),
        )
        for source, kind in cases:
            with self.subTest(source=source):
                self.assertEqual(run_error(source).kind, kind)

    def test_method_work_scales_with_sequence_and_string_size(self):
        cases = (
            ("sequence", "value.count(-1)"),
            ("sequence", "value.index(-1)"),
            ("string", "value.partition('x')"),
            ("string", "value.rpartition('x')"),
        )
        for kind, expression in cases:
            counts = {}
            for size in (100, 1000):
                engine = SericiteEngine()
                checkpoints = []
                vm = engine.create_root(
                    "value = make()\ncheckpoint()\n"
                    f"result = {expression}\ncheckpoint()",
                    functions={
                        "make": lambda kind=kind, size=size: (
                            "a" * size if kind == "string" else [0] * (size - 1) + [-1]
                        ),
                        "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                            checkpoints.append(engine._contexts[0].instruction_count)
                        ),
                    },
                )
                vm.run()
                counts[size] = checkpoints[1] - checkpoints[0]
            with self.subTest(expression=expression):
                self.assertGreater(counts[1000], counts[100])


class TupleAccountingTests(unittest.TestCase):
    def test_tuple_size_limit_for_all_result_construction(self):
        sources = (
            "value = (1, 2, 3)",
            "value = (1, 2) + (3,)",
            "value = (1, 2) * 2",
            "value = 2 * (1, 2)",
            "value = (1, 2, 3)[:]",
        )
        for source in sources:
            with self.subTest(source=source):
                error = run_error(source, SericiteLimits(max_list_size=2))
                self.assertEqual(error.kind, "resource_exhausted")

    def test_ffi_tuple_uses_sequence_size_limit(self):
        engine = SericiteEngine(SericiteLimits(max_list_size=1))
        vm = engine.create_root("value = make()", functions={"make": lambda: (1, 2)})
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "ffi_error")

    def test_copy_work_scales_with_result_size(self):
        for operation in ("value + value", "value * 2", "value[:]"):
            counts = {}
            for size in (10, 1000):
                engine = SericiteEngine()
                checkpoints = []
                vm = engine.create_root(
                    f"value = make()\ncheckpoint()\nresult = {operation}\ncheckpoint()",
                    functions={
                        "make": lambda size=size: tuple(range(size)),
                        "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                            checkpoints.append(engine._contexts[0].instruction_count)
                        ),
                    },
                )
                vm.run()
                counts[size] = checkpoints[1] - checkpoints[0]
            with self.subTest(operation=operation):
                self.assertGreater(counts[1000], counts[10])


class StaticExceptWithTuplesTests(unittest.TestCase):
    def test_dynamic_filter_and_group_elements_remain_invalid(self):
        sources = (
            (
                "kinds = ('name_error', 'type_error')\n"
                "try:\n    pass\nexcept kinds:\n    pass"
            ),
            (
                "kind = 'name_error'\n"
                "try:\n    pass\nexcept (kind, type_error):\n    pass"
            ),
            "try:\n    pass\nexcept (('name_error', 'type_error')):\n    pass",
            "try:\n    pass\nexcept ['name_error', 'type_error']:\n    pass",
        )
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_static_kind_group_still_catches(self):
        source = (
            "try:\n"
            "    a, b = (1,)\n"
            "except (type_error, value_error) as e:\n"
            "    print(e.kind)\n"
        )
        self.assertEqual(run(source), "value_error\n")


if __name__ == "__main__":
    unittest.main()
