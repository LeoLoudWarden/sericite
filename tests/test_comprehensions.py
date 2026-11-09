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


class ComprehensionTests(unittest.TestCase):
    def test_list_comprehension_with_filter(self):
        source = (
            "print([x * x for x in range(6) if x % 2])\n"
            "print([x for x in []])\n"
            "print([x for x in range(4) if x if x > 1])\n"
        )
        self.assertEqual(run(source), "[1, 9, 25]\n[]\n[2, 3]\n")

    def test_dict_comprehension_with_tuple_unpacking(self):
        source = (
            "pairs = [('a', 1), ('b', 2)]\n"
            "print({key: value for key, value in pairs})\n"
            "mapping = {'a': 1, 'b': 2}\n"
            "print({value: key for key, value in mapping.items()})\n"
            "print({key: value * 2 for key, (value, other) in [('a', (2, 0))]})\n"
        )
        self.assertEqual(
            run(source),
            "{'a': 1, 'b': 2}\n{1: 'a', 2: 'b'}\n{'a': 4}\n",
        )

    def test_multiple_generators_and_filters(self):
        source = (
            "result = [\n"
            "    (x, y)\n"
            "    for x in [1, 2, 3]\n"
            "    if x > 1\n"
            "    for y in [3, 4]\n"
            "    if x + y > 4\n"
            "    if y != 4\n"
            "]\n"
            "print(result)\n"
        )
        self.assertEqual(run(source), "[(2, 3), (3, 3)]\n")

    def test_dict_duplicate_keys_overwrite_without_reordering(self):
        source = (
            "result = {key: value for key, value in [('a', 1), ('b', 2), ('a', 3)]}\n"
            "print(result)\n"
        )
        self.assertEqual(run(source), "{'a': 3, 'b': 2}\n")

    def test_tuple_and_string_sources(self):
        source = (
            "print([x for x in (1, 2)])\n"
            "print({char: char for char in 'ab'})\n"
            "print([key for key in {'a': 1, 'b': 2}])\n"
        )
        self.assertEqual(run(source), "[1, 2]\n{'a': 'a', 'b': 'b'}\n['a', 'b']\n")


class ComprehensionScopeTests(unittest.TestCase):
    def test_target_does_not_leak_or_overwrite_outer_name(self):
        source = (
            "x = 9\n"
            "result = [x for x in [1, 2]]\n"
            "other = {x: x for x in [3]}\n"
            "print(result, other, x)\n"
        )
        self.assertEqual(run(source), "[1, 2] {3: 3} 9\n")

    def test_outermost_iterable_is_evaluated_in_outer_scope(self):
        source = (
            "x = [3, 4]\n"
            "result = [x for x in x]\n"
            "print(result, x)\n"
            "def f():\n"
            "    value = [5, 6]\n"
            "    return [value for value in value]\n"
            "print(f())\n"
        )
        self.assertEqual(run(source), "[3, 4] [3, 4]\n[5, 6]\n")

    def test_later_iterable_and_filter_see_current_targets(self):
        source = (
            "result = [(x, y) for x in [[1, 2], [3]] for y in x if y > 1]\n"
            "print(result)\n"
        )
        self.assertEqual(run(source), "[([1, 2], 2), ([3], 3)]\n")

    def test_comprehension_captures_function_locals(self):
        source = (
            "def make(factor):\n"
            "    return [x * factor for x in [1, 2]]\n"
            "print(make(3))\n"
        )
        self.assertEqual(run(source), "[3, 6]\n")

    def test_nested_comprehension_captures_outer_comprehension_target(self):
        source = (
            "result = [[x * y for y in [1, 2]] for x in [3, 4]]\n"
            "print(result)\n"
            "lookup = {x: {y: x + y for y in [1, 2]} for x in [3, 4]}\n"
            "print(lookup)\n"
        )
        self.assertEqual(
            run(source),
            "[[3, 6], [4, 8]]\n{3: {1: 4, 2: 5}, 4: {1: 5, 2: 6}}\n",
        )

    def test_nested_comprehension_in_outer_iterable(self):
        source = "print([x * 2 for x in [y for y in [1, 2]]])\n"
        self.assertEqual(run(source), "[2, 4]\n")


class ComprehensionEvaluationTests(unittest.TestCase):
    def test_list_order_and_single_outer_iterable_evaluation(self):
        source = (
            "log = []\n"
            "def mark(name, value):\n"
            "    log.append(name)\n"
            "    return value\n"
            "result = [\n"
            "    mark('elt', x)\n"
            "    for x in mark('iter', [1, 2])\n"
            "    if mark('if', True)\n"
            "]\n"
            "print(result, log)\n"
        )
        self.assertEqual(run(source), "[1, 2] ['iter', 'if', 'elt', 'if', 'elt']\n")

    def test_nested_generator_order(self):
        source = (
            "log = []\n"
            "def mark(name, value):\n"
            "    log.append(name)\n"
            "    return value\n"
            "result = [\n"
            "    mark('elt', (x, y))\n"
            "    for x in mark('outer', [1, 2])\n"
            "    for y in mark('inner', [x])\n"
            "]\n"
            "print(result, log)\n"
        )
        self.assertEqual(
            run(source),
            "[(1, 1), (2, 2)] ['outer', 'inner', 'elt', 'inner', 'elt']\n",
        )

    def test_dict_key_is_evaluated_before_value(self):
        source = (
            "log = []\n"
            "def mark(name, value):\n"
            "    log.append(name)\n"
            "    return value\n"
            "result = {\n"
            "    mark('key', key): mark('value', value)\n"
            "    for key, value in [('a', 1), ('b', 2)]\n"
            "}\n"
            "print(result, log)\n"
        )
        self.assertEqual(
            run(source),
            "{'a': 1, 'b': 2} ['key', 'value', 'key', 'value']\n",
        )

    def test_list_source_remains_a_live_view(self):
        source = (
            "values = [1, 2]\n"
            "result = [\n"
            "    x\n"
            "    for x in values\n"
            "    if len(values) > 2 or values.append(3)\n"
            "]\n"
            "print(result, values)\n"
        )
        self.assertEqual(run(source), "[2, 3] [1, 2, 3]\n")

    def test_dict_source_uses_key_snapshot(self):
        source = (
            "mapping = {1: 2}\n"
            "result = [\n"
            "    key\n"
            "    for key in mapping\n"
            "    if len(mapping) > 1 or mapping.pop(1)\n"
            "]\n"
            "print(result, mapping)\n"
        )
        self.assertEqual(run(source), "[1] {}\n")


class ComprehensionErrorTests(unittest.TestCase):
    def test_exceptions_unwind_to_outer_handler_and_execution_continues(self):
        source = (
            "for values in ([0], [1]):\n"
            "    try:\n"
            "        result = [1 / x for x in values]\n"
            "    except zero_division as e:\n"
            "        print(e.kind)\n"
            "try:\n"
            "    result = {[]: 1 for x in [1]}\n"
            "except type_error as e:\n"
            "    print(e.kind)\n"
            "print('alive')\n"
        )
        self.assertEqual(run(source), "zero_division\ntype_error\nalive\n")

    def test_unpacking_error_is_catchable(self):
        source = (
            "try:\n"
            "    result = [x for x, y in [(1, 2), (3,)]]\n"
            "except value_error as e:\n"
            "    print(e.kind)\n"
        )
        self.assertEqual(run(source), "value_error\n")

    def test_set_generator_and_invalid_targets_remain_rejected(self):
        sources = (
            "{x for x in [1]}",
            "(x for x in [1])",
            "[x for [x] in [[1]]]",
            "[x for x, *y in [(1, 2)]]",
            "{x: 1 for values[0] in [[1]]}",
        )
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_comprehension_works_inside_child_vm(self):
        source = (
            "sub = VM(\"print([x * 2 for x in range(3)])\")\nprint(sub.run(), end='')"
        )
        self.assertEqual(run(source), "[0, 2, 4]\n")

    def test_statement_stepping_hides_comprehension_internals(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 0\nresult = [x for x in [1, 2]]\n")
        vm.step()
        snapshot = vm.step()
        self.assertEqual(snapshot["state"], "done")
        self.assertEqual(snapshot["locals"]["result"], [1, 2])
        self.assertEqual(snapshot["locals"]["x"], 0)
        self.assertFalse(any(name.startswith("$") for name in snapshot["locals"]))


class ComprehensionAccountingTests(unittest.TestCase):
    def test_list_result_size_limit(self):
        error = run_error(
            "result = [x for x in range(3)]", SericiteLimits(max_list_size=2)
        )
        self.assertEqual(error.kind, "resource_exhausted")
        self.assertEqual(
            run(
                "result = [x for x in 'abc' if False]\nprint(result)",
                limits=SericiteLimits(max_list_size=0),
            ),
            "[]\n",
        )

    def test_dict_result_size_limit_and_duplicate_keys(self):
        error = run_error(
            "result = {x: x for x in [1, 2]}", SericiteLimits(max_dict_size=1)
        )
        self.assertEqual(error.kind, "resource_exhausted")
        self.assertEqual(
            run(
                "result = {1: x for x in [1, 2, 3]}\nprint(result)",
                limits=SericiteLimits(max_dict_size=1),
            ),
            "{1: 3}\n",
        )

    def test_iteration_and_result_growth_charge_allocation(self):
        engine = SericiteEngine()
        checkpoints = []
        vm = engine.create_root(
            "values = [1, 2, 3]\ncheckpoint()\n"
            "result = [x for x in values]\ncheckpoint()",
            functions={
                "checkpoint": lambda: checkpoints.append(
                    engine._contexts[0].alloc_bytes
                )
            },
        )
        vm.run()
        self.assertEqual(checkpoints[1] - checkpoints[0], 2 * 3 * 8 + 8)

    def test_iteration_and_result_work_scale_with_input_size(self):
        for expression in ("[x for x in value]", "{x: x for x in value}"):
            counts = {}
            for size in (10, 1000):
                engine = SericiteEngine()
                checkpoints = []
                vm = engine.create_root(
                    "value = make()\ncheckpoint()\n"
                    f"result = {expression}\ncheckpoint()",
                    functions={
                        "make": lambda size=size: list(range(size)),
                        "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                            checkpoints.append(engine._contexts[0].instruction_count)
                        ),
                    },
                )
                vm.run()
                counts[size] = checkpoints[1] - checkpoints[0]
            with self.subTest(expression=expression):
                self.assertGreater(counts[1000], counts[10])


if __name__ == "__main__":
    unittest.main()
