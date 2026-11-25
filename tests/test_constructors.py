from __future__ import annotations

import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


def run(source, limits=None, addons=None):
    if addons:
        source = f"from __addon__ import {', '.join(addons)}\n{source}"
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source, addons=addons)
    return vm.run()


def run_error(source, limits=None):
    engine = SericiteEngine(limits=limits)
    with unittest.TestCase().assertRaises(SericiteError) as ctx:
        vm = engine.create_root(source)
        vm.run()
    return ctx.exception


class ConstructorValueTests(unittest.TestCase):
    def test_empty_constructors(self):
        self.assertEqual(
            run("print([int(), float(), str(), bool(), list(), tuple(), dict()])"),
            "[0, 0.0, '', False, [], (), {}]\n",
        )

    def test_existing_scalar_conversions_are_unchanged(self):
        self.assertEqual(
            run(
                "print(int('42'), int(3.9), int(True))\n"
                "print(float('0.5'), float(2), float(False))\n"
                "print(str(12), str(None), repr(str()))"
            ),
            "42 3 1\n0.5 2.0 0.0\n12 None ''\n",
        )

    def test_bool_uses_script_truthiness(self):
        source = (
            "values = [None, False, True, 0, 1, 0.0, 0.5, '', 'x', "
            "[], [0], (), (0,), {}, {'x': 1}]\n"
            "print([bool(value) for value in values])\n"
            "class Box:\n"
            "    pass\n"
            "print(bool(Box()))"
        )
        self.assertEqual(
            run(source),
            "[False, False, True, False, True, False, True, False, True, "
            "False, True, False, True, False, True]\nTrue\n",
        )

    def test_list_conversions_and_shallow_copy(self):
        source = (
            "nested = [1]\n"
            "original = [nested, 2]\n"
            "copied = list(original)\n"
            "copied.append(3)\n"
            "copied[0].append(4)\n"
            "print(original)\n"
            "print(copied)\n"
            "print(list((1, 2)), list('ab'), list({'a': 1, 'b': 2}))"
        )
        self.assertEqual(
            run(source),
            "[[1, 4], 2]\n[[1, 4], 2, 3]\n[1, 2] ['a', 'b'] ['a', 'b']\n",
        )

    def test_tuple_conversions_and_shallow_copy(self):
        source = (
            "nested = [1]\n"
            "value = tuple([nested])\n"
            "nested.append(2)\n"
            "print(value)\n"
            "print(tuple((1, 2)), tuple('ab'), tuple({'x': 1, 'y': 2}))"
        )
        self.assertEqual(
            run(source),
            "([1, 2],)\n(1, 2) ('a', 'b') ('x', 'y')\n",
        )

    def test_dict_conversions_and_shallow_copy(self):
        source = (
            "nested = [1]\n"
            "original = {'a': nested}\n"
            "copied = dict(original)\n"
            "copied['b'] = 2\n"
            "copied['a'].append(3)\n"
            "print(original)\n"
            "print(copied)\n"
            "print(dict([('a', 1), ['b', 2]]))\n"
            "print(dict((('x', 1), ('y', 2))))"
        )
        self.assertEqual(
            run(source),
            "{'a': [1, 3]}\n{'a': [1, 3], 'b': 2}\n"
            "{'a': 1, 'b': 2}\n"
            "{'x': 1, 'y': 2}\n",
        )

    def test_dict_duplicate_and_keyword_entries_overwrite_in_order(self):
        self.assertEqual(
            run(
                "print(dict(a=1, b=2))\n"
                "print(dict([('a', 1), ('a', 2), ('b', 0)], a=3, b=4))\n"
                "print(dict(value=1, entries=2))"
            ),
            "{'a': 1, 'b': 2}\n{'a': 3, 'b': 4}\n{'value': 1, 'entries': 2}\n",
        )

    def test_dict_accepts_former_internal_keyword_names_as_entries(self):
        self.assertEqual(
            run(
                "print(dict(_caller_context=1, _caller_meter=2, _allocation_permit=3))"
            ),
            "{'_caller_context': 1, '_caller_meter': 2, '_allocation_permit': 3}\n",
        )


class ConstructorContractTests(unittest.TestCase):
    def test_all_constructor_names_remain_annotation_contracts(self):
        source = (
            "def check(a: int, b: float, c: str, d: bool, e: list, "
            "f: dict, g: tuple) -> dict:\n"
            "    return {'a': a, 'b': b, 'c': c, 'd': d, 'e': e, 'f': f, 'g': g}\n"
            "print(check(1, 2.5, 'x', True, [1], {'k': 2}, (3,)))"
        )
        self.assertEqual(
            run(source),
            "{'a': 1, 'b': 2.5, 'c': 'x', 'd': True, 'e': [1], "
            "'f': {'k': 2}, 'g': (3,)}\n",
        )
        self.assertEqual(run_error("value: bool = 1").kind, "contract_error")
        self.assertEqual(run_error("value: list = {}").kind, "contract_error")
        self.assertEqual(run_error("value: tuple = []").kind, "contract_error")

    def test_any_remains_annotation_only(self):
        self.assertEqual(
            run(
                "def identity(value: any) -> any:\n    return value\nprint(identity(1))"
            ),
            "1\n",
        )
        self.assertEqual(run_error("any(1)").kind, "syntax_error")

    def test_builtins_remain_reserved_and_direct_call_only(self):
        for name in ("int", "float", "str", "bool", "list", "tuple", "dict"):
            for source in (f"value = {name}", f"{name} = 1"):
                with self.subTest(name=name, source=source):
                    self.assertEqual(run_error(source).kind, "syntax_error")
            with self.subTest(name=name, source="import"):
                self.assertEqual(
                    run_error(f"from __addon__ import {name}").kind, "syntax_error"
                )


class ConstructorErrorTests(unittest.TestCase):
    def test_explicit_none_is_not_an_omitted_container_argument(self):
        self.assertEqual(run("print(str(None), bool(None))"), "None False\n")
        for expression in (
            "int(None)",
            "float(None)",
            "list(None)",
            "tuple(None)",
            "dict(None)",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(run_error(expression).kind, "type_error")

    def test_sequence_constructor_rejects_non_iterable_values(self):
        for expression in ("list(1)", "tuple(1)", "dict(1)", "dict('ab')"):
            with self.subTest(expression=expression):
                self.assertEqual(run_error(expression).kind, "type_error")

    def test_dict_rejects_malformed_pairs(self):
        cases = {
            "dict([1])": "type_error",
            "dict(['ab'])": "type_error",
            "dict([('a',)])": "value_error",
            "dict([('a', 1, 2)])": "value_error",
            "dict([([], 1)])": "type_error",
        }
        for expression, kind in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(run_error(expression).kind, kind)

    def test_record_is_not_implicitly_unwrapped(self):
        source = "class Point:\n    x: int\npoint = Point(1)\n"
        self.assertEqual(run_error(source + "dict(point)").kind, "type_error")

    def test_wrong_arity_uses_native_argument_error(self):
        for expression in (
            "int(1, 2)",
            "float(1, 2)",
            "str(1, 2)",
            "str(1, 2, 3)",
            "str(*[1, 2])",
            "str(1, *[2])",
            "repr(1, 2)",
            "repr(1, 2, 3)",
            "repr(*[1, 2])",
            "bool(1, 2)",
            "list([], [])",
            "tuple([], [])",
            "dict({}, {})",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(run_error(expression).kind, "type_error")

    def test_string_native_argument_errors_are_catchable(self):
        for name in ("str", "repr"):
            with self.subTest(name=name):
                self.assertEqual(
                    run(
                        "try:\n"
                        f"    {name}(1, 2)\n"
                        "except type_error:\n"
                        "    print('caught')\n"
                        "print('alive')"
                    ),
                    "caught\nalive\n",
                )

    def test_literal_and_comprehension_unpacking_remain_rejected(self):
        for source in (
            "value = [1]\nresult = [*value]",
            "value = {'a': 1}\nresult = {**value}",
            "value = [[1]]\nresult = [*item for item in value]",
        ):
            with self.subTest(source=source):
                self.assertEqual(run_error(source).kind, "syntax_error")


class ConstructorResourceTests(unittest.TestCase):
    def test_empty_constructors_allow_zero_container_limits(self):
        limits = SericiteLimits(max_list_size=0, max_dict_size=0)
        self.assertEqual(run("print(list(), tuple(), dict())", limits), "[] () {}\n")

    def test_sequence_constructor_size_limits(self):
        limits = SericiteLimits(max_list_size=1)
        for expression in ("list('ab')", "tuple('ab')"):
            with self.subTest(expression=expression):
                self.assertEqual(
                    run_error(expression, limits).kind, "resource_exhausted"
                )

    def test_dict_constructor_size_limit(self):
        limits = SericiteLimits(max_dict_size=1)
        for expression in (
            "dict(a=1, b=2)",
            "dict([('a', 1), ('b', 2)])",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(
                    run_error(expression, limits).kind, "resource_exhausted"
                )

    def test_container_results_enforce_memory_limit(self):
        limits = SericiteLimits(max_total_bytes=0)
        for expression in ("list('x')", "tuple('x')", "dict(a=1)"):
            with self.subTest(expression=expression):
                self.assertEqual(
                    run_error(expression, limits).kind, "resource_exhausted"
                )

    def test_list_constructor_work_and_allocation_scale_with_input(self):
        deltas = {}
        for size in (10, 1000):
            engine = SericiteEngine()
            checkpoints = []
            vm = engine.create_root(
                "from __addon__ import make, checkpoint\n"
                "value = make()\n"
                "checkpoint()\n"
                "result = list(value)\n"
                "checkpoint()",
                addons={
                    "make": lambda size=size: "x" * size,
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
            deltas[size] = (
                checkpoints[1][0] - checkpoints[0][0],
                checkpoints[1][1] - checkpoints[0][1],
            )
        self.assertGreater(deltas[1000][0], deltas[10][0])
        self.assertGreaterEqual(deltas[10][1], 10 * 8)
        self.assertGreaterEqual(deltas[1000][1], 1000 * 8)

    def test_failed_dict_conversion_charges_long_key_scan(self):
        deltas = {}
        for size in (10, 1000):
            engine = SericiteEngine(SericiteLimits(max_dict_size=0))
            checkpoints = []
            vm = engine.create_root(
                "from __addon__ import make, checkpoint\n"
                "value = make()\n"
                "checkpoint()\n"
                "result = dict(value)",
                addons={
                    "make": lambda size=size: [["k" * size, 0]],
                    "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                        checkpoints.append(engine._contexts[0].instruction_count)
                    ),
                },
            )
            with self.assertRaises(SericiteError) as ctx:
                vm.run()
            self.assertEqual(ctx.exception.kind, "resource_exhausted")
            deltas[size] = engine._contexts[0].instruction_count - checkpoints[0]
        self.assertGreater(deltas[1000], deltas[10])

    def test_cross_vm_constructor_work_and_allocation_reach_caller(self):
        text = "x" * 1000
        source = (
            f"text = {text!r}\n"
            "def convert():\n"
            "    return list(text)\n"
            'sub = VM("from __addon__ import convert\\nvalue = convert()", '
            "addons={'convert': convert}, max_instructions=100, max_total_bytes=20000)\n"
            "sub.run()"
        )
        self.assertEqual(run_error(source).kind, "resource_exhausted")

        allocation_source = source.replace(
            "max_instructions=100, max_total_bytes=20000",
            "max_instructions=10000, max_total_bytes=4000",
        )
        self.assertEqual(run_error(allocation_source).kind, "resource_exhausted")
        self.assertEqual(
            run(
                source.replace(
                    "max_instructions=100, max_total_bytes=20000",
                    "max_instructions=10000, max_total_bytes=20000",
                )
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
