import unittest
from dataclasses import replace

from sericite import SericiteEngine, SericiteLimits
from sericite.errors import SericiteError


def run(source, *, limits=None, functions=None):
    engine = SericiteEngine(limits=limits)
    return engine.create_root(source, functions=functions).run()


def run_error(source, *, limits=None):
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source)
    with unittest.TestCase().assertRaises(SericiteError) as ctx:
        vm.run()
    return ctx.exception


class VariadicDefinitionTests(unittest.TestCase):
    def test_collects_positional_and_keyword_arguments(self):
        source = (
            "def collect(a, *args, **kwargs):\n"
            "    return [a, args, kwargs]\n"
            "print(collect(1))\n"
            "print(collect(1, 2, 3, x=4, y=5))\n"
        )
        self.assertEqual(
            run(source),
            "[1, (), {}]\n[1, (2, 3), {'x': 4, 'y': 5}]\n",
        )

    def test_defaults_and_explicit_keywords_still_bind(self):
        source = (
            "def f(a, b=2, *args, **kwargs):\n"
            "    return [a, b, args, kwargs]\n"
            "print(f(1))\n"
            "print(f(1, b=3, x=4))\n"
            "print(f(1, 5, 6, b=7))\n"
        )
        self.assertEqual(run_error(source).kind, "arity_error")
        self.assertEqual(
            run(source.rsplit("print(f(1, 5, 6, b=7))", 1)[0]),
            "[1, 2, (), {}]\n[1, 3, (), {'x': 4}]\n",
        )

    def test_variadic_parameters_can_be_captured(self):
        source = (
            "def outer(*args, **kwargs):\n"
            "    def read():\n"
            "        return [args, kwargs]\n"
            "    return read\n"
            "print(outer(1, 2, x=3)())\n"
        )
        self.assertEqual(run(source), "[(1, 2), {'x': 3}]\n")

    def test_variadic_container_annotations(self):
        source = (
            "def f(*args: tuple, **kwargs: dict) -> list:\n"
            "    return [args, kwargs]\n"
            "print(f(1, x=2))\n"
        )
        self.assertEqual(run(source), "[(1,), {'x': 2}]\n")

    def test_duplicate_variadic_parameter_names_rejected(self):
        for source in (
            "def f(x, *x):\n    pass\n",
            "def f(*x, **x):\n    pass\n",
            "def f(x, **x):\n    pass\n",
        ):
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")
                self.assertIn("duplicate parameter 'x'", ctx.exception.message)

    def test_keyword_only_and_positional_only_remain_rejected(self):
        for source in (
            "def f(*, x):\n    pass\n",
            "def f(x, /):\n    pass\n",
        ):
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")


class CallExpansionTests(unittest.TestCase):
    def test_expands_supported_iterables_and_dicts(self):
        source = (
            "def f(*args, **kwargs):\n"
            "    return [args, kwargs]\n"
            "print(f(*[1, 2], *(3, 4), *'ab', *{'x': 0}, **{'y': 5}))\n"
        )
        self.assertEqual(
            run(source),
            "[(1, 2, 3, 4, 'a', 'b', 'x'), {'y': 5}]\n",
        )

    def test_mixes_explicit_and_expanded_arguments(self):
        source = (
            "def f(a, b=2, *args, **kwargs):\n"
            "    return [a, b, args, kwargs]\n"
            "values = [3, 4]\n"
            "options = {'x': 5}\n"
            "print(f(1, *values, y=6, **options))\n"
        )
        self.assertEqual(run(source), "[1, 3, (4,), {'y': 6, 'x': 5}]\n")

    def test_evaluation_order(self):
        source = (
            "events = []\n"
            "def mark(name, value):\n"
            "    events.append(name)\n"
            "    return value\n"
            "def f(*args, **kwargs):\n"
            "    return [args, kwargs]\n"
            "result = f(mark('a', 1), *mark('star', [2]), "
            "x=mark('keyword', 3), **mark('double_star', {'y': 4}))\n"
            "print(events)\n"
            "print(result)\n"
        )
        self.assertEqual(
            run(source),
            "['a', 'star', 'keyword', 'double_star']\n[(1, 2), {'x': 3, 'y': 4}]\n",
        )

    def test_invalid_expansion_types(self):
        cases = (
            ("def f():\n    pass\nf(*1)\n", "type_error"),
            ("def f():\n    pass\nf(**[])\n", "type_error"),
            ("def f(**kwargs):\n    pass\nf(**{1: 2})\n", "type_error"),
        )
        for source, kind in cases:
            with self.subTest(source=source):
                self.assertEqual(run_error(source).kind, kind)

    def test_duplicate_expanded_keywords_are_arity_errors(self):
        for call in (
            "f(x=1, **{'x': 2})",
            "f(**{'x': 1}, **{'x': 2})",
        ):
            with self.subTest(call=call):
                source = f"def f(**kwargs):\n    return kwargs\n{call}\n"
                self.assertEqual(run_error(source).kind, "arity_error")

    def test_binding_errors_are_preserved(self):
        cases = (
            "def f(x):\n    return x\nf(*[1], x=2)\n",
            "def f(x):\n    return x\nf(**{'y': 2})\n",
            "def f(x):\n    return x\nf()\n",
            "def f(x):\n    return x\nf(*[1, 2])\n",
        )
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(run_error(source).kind, "arity_error")

    def test_expansion_works_for_records_and_native_functions(self):
        source = (
            "class Point:\n"
            "    x: int\n"
            "    y: int\n"
            "p = Point(*[1], **{'y': 2})\n"
            "print(p.x, p.y, *[3, 4], **{'sep': '-', 'end': '!'})"
        )
        self.assertEqual(run(source), "1-2-3-4!")

    def test_expansion_works_for_host_functions(self):
        def collect(*args, **kwargs):
            return [list(args), kwargs]

        self.assertEqual(
            run("print(f(*[1, 2], **{'x': 3}))\n", functions={"f": collect}),
            "[[1, 2], {'x': 3}]\n",
        )

    def test_granted_variadic_function(self):
        source = (
            "def f(a, *args, **kwargs):\n"
            "    return [a, args, kwargs]\n"
            "sub = VM(\"print(f(*[1, 2], **{'x': 3}))\\n\", functions={'f': f})\n"
            "print(sub.run(), end='')\n"
        )
        self.assertEqual(run(source), "[1, (2,), {'x': 3}]\n")


class VariadicDecoratorTests(unittest.TestCase):
    def test_transparent_decorator(self):
        source = (
            "def trace(func):\n"
            "    def wrapper(*args, **kwargs):\n"
            "        print('before', args, kwargs)\n"
            "        result = func(*args, **kwargs)\n"
            "        print('after')\n"
            "        return result\n"
            "    return wrapper\n"
            "@trace\n"
            "def add(a, b=2):\n"
            "    return a + b\n"
            "print(add(1, b=4))\n"
        )
        self.assertEqual(run(source), "before (1,) {'b': 4}\nafter\n5\n")

    def test_stacked_transparent_decorators(self):
        source = (
            "def wrap_with(label):\n"
            "    def decorate(func):\n"
            "        def wrapper(*args, **kwargs):\n"
            "            print(label)\n"
            "            return func(*args, **kwargs)\n"
            "        return wrapper\n"
            "    return decorate\n"
            "@wrap_with('outer')\n"
            "@wrap_with('inner')\n"
            "def f(x):\n"
            "    return x\n"
            "print(f(*[42]))\n"
        )
        self.assertEqual(run(source), "outer\ninner\n42\n")


class VariadicAccountingTests(unittest.TestCase):
    def test_collected_arguments_obey_container_limits(self):
        source = "def f(*args):\n    return args\nf(1, 2)\n"
        self.assertEqual(
            run_error(source, limits=SericiteLimits(max_list_size=1)).kind,
            "resource_exhausted",
        )
        source = "def f(**kwargs):\n    return kwargs\nf(x=1)\n"
        self.assertEqual(
            run_error(source, limits=SericiteLimits(max_dict_size=0)).kind,
            "resource_exhausted",
        )

    def test_expanded_arguments_obey_container_limits(self):
        source = "def f(*args):\n    return args\nf(*[1, 2])\n"
        self.assertEqual(
            run_error(source, limits=SericiteLimits(max_list_size=1)).kind,
            "resource_exhausted",
        )
        source = "def f(**kwargs):\n    return kwargs\nf(**{'x': 1})\n"
        self.assertEqual(
            run_error(source, limits=SericiteLimits(max_dict_size=0)).kind,
            "resource_exhausted",
        )

    def test_trailing_explicit_arguments_obey_final_limits(self):
        cases = (
            (
                "print(*[1], 2, end='')",
                SericiteLimits(max_list_size=1),
            ),
            (
                "print(**{'sep': ' '}, end='')",
                SericiteLimits(max_dict_size=1),
            ),
        )
        for source, limits in cases:
            with self.subTest(source=source):
                self.assertEqual(
                    run_error(source, limits=limits).kind,
                    "resource_exhausted",
                )

    def failed_expansion_allocation(self, size, *, duplicate=False):
        engine = SericiteEngine()
        checkpoints = []
        if duplicate:
            setup = "first = {'x': 1}\nsecond = {'x': 2}\n"
            call = "f(*values, **first, **second)"
            kind = "arity_error"
        else:
            setup = "options = {1: 'bad'}\n"
            call = "f(*values, **options)"
            kind = "type_error"
        source = (
            "def f(*args, **kwargs):\n"
            "    pass\n"
            f"values = {list(range(size))}\n"
            f"{setup}"
            "checkpoint()\n"
            "try:\n"
            f"    {call}\n"
            f"except {kind}:\n"
            "    pass\n"
            "checkpoint()\n"
        )
        engine.create_root(
            source,
            functions={
                "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                    checkpoints.append(engine._contexts[0].alloc_bytes)
                )
            },
        ).run()
        return checkpoints[1] - checkpoints[0]

    def test_invalid_key_charges_positional_growth_before_failure(self):
        empty = self.failed_expansion_allocation(0)
        expanded = self.failed_expansion_allocation(3)
        self.assertEqual(expanded - empty, 3 * 8)

    def test_duplicate_key_charges_growth_completed_before_failure(self):
        empty = self.failed_expansion_allocation(0, duplicate=True)
        expanded = self.failed_expansion_allocation(3, duplicate=True)
        self.assertEqual(expanded - empty, 3 * 8)

    def test_mid_expansion_memory_failure_retains_committed_charges(self):
        engine = SericiteEngine()
        checkpoints = []

        def prepare():
            context = engine._contexts[0]
            checkpoints.append(context.alloc_bytes)
            context.limits = replace(
                context.limits,
                max_total_bytes=context.alloc_bytes + 8 + 16,
            )

        vm = engine.create_root(
            "def f(**kwargs):\n"
            "    pass\n"
            "options = {'x': 1, 'y': 2}\n"
            "prepare()\n"
            "f(**options)\n",
            functions={"prepare": prepare},
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(engine._contexts[0].alloc_bytes, checkpoints[0] + 8 + 16)

    def test_variadic_collection_consumes_memory_quota(self):
        source = "def f(*args, **kwargs):\n    pass\nf(1, 2, x=3)\n"
        self.assertEqual(
            run_error(source, limits=SericiteLimits(max_total_bytes=0)).kind,
            "resource_exhausted",
        )
        self.assertEqual(run(source), "")


class DynamicKeyDiagnosticTests(unittest.TestCase):
    def diagnostic_delta(self, case, key_size):
        engine = SericiteEngine()
        checkpoints = []
        definitions = {
            "duplicate": "def f(**kwargs):\n    pass\n",
            "unexpected": "def f():\n    pass\n",
            "record": "class P:\n    x: int\n",
            "vm_option": "",
        }[case]
        setup = (
            "first = make_options()\nsecond = make_options()\n"
            if case == "duplicate"
            else "options = make_options()\n"
        )
        call = {
            "duplicate": "f(**first, **second)",
            "unexpected": "f(**options)",
            "record": "P(**options)",
            "vm_option": "VM('', **options)",
        }[case]
        kind = {
            "duplicate": "arity_error",
            "unexpected": "arity_error",
            "record": "contract_error",
            "vm_option": "type_error",
        }[case]
        source = (
            f"{definitions}{setup}"
            "checkpoint()\n"
            "try:\n"
            f"    {call}\n"
            f"except {kind} as error:\n"
            "    observed = len(error.message)\n"
            "checkpoint()\n"
        )
        vm = engine.create_root(
            source,
            functions={
                "make_options": lambda: {"k" * key_size: 1},
                "checkpoint": lambda: checkpoints.append(
                    (
                        engine._contexts[0].instruction_count,
                        engine._contexts[0].alloc_bytes,
                    )
                ),
            },
        )
        vm.run()
        observed = engine._contexts[0].frames[0].locals["observed"]
        return (
            checkpoints[1][0] - checkpoints[0][0],
            checkpoints[1][1] - checkpoints[0][1],
            observed,
        )

    def test_dynamic_key_diagnostics_charge_work_and_message_allocation(self):
        for case in ("duplicate", "unexpected", "record", "vm_option"):
            with self.subTest(case=case):
                small = self.diagnostic_delta(case, 10)
                large = self.diagnostic_delta(case, 1000)
                size_delta = 1000 - 10
                self.assertEqual(large[0] - small[0], size_delta)
                self.assertEqual(large[1] - small[1], size_delta * 4)
                self.assertEqual(large[2] - small[2], size_delta)


if __name__ == "__main__":
    unittest.main()
