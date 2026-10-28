import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


def run(source, inputs=None):
    engine = SericiteEngine()
    vm = engine.create_root(source)
    return vm.run(inputs)


class ArithmeticTests(unittest.TestCase):
    def test_int_arithmetic(self):
        self.assertEqual(
            run("print(1 + 2 * 3)\nprint(7 - 10)\nprint(2 * 3)\n"),
            "7\n-3\n6\n",
        )

    def test_float_promotion_and_division(self):
        self.assertEqual(run("print(7 / 2)\n"), "3.5\n")
        self.assertEqual(run("print(1 + 0.5)\n"), "1.5\n")
        self.assertEqual(run("print(7 // 2)\nprint(7 % 2)\n"), "3\n1\n")

    def test_unary_minus_and_not(self):
        self.assertEqual(
            run("x = 5\nprint(-x)\nprint(not x)\nprint(not 0)\n"), "-5\nFalse\nTrue\n"
        )

    def test_string_concat(self):
        self.assertEqual(run('print("ab" + "cd")\n'), "abcd\n")

    def test_bool_not_a_number(self):
        with self.assertRaises(SericiteError) as ctx:
            run("print(True + 1)\n")
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_zero_division(self):
        with self.assertRaises(SericiteError) as ctx:
            run("print(1 / 0)\n")
        self.assertEqual(ctx.exception.kind, "zero_division")
        with self.assertRaises(SericiteError) as ctx:
            run("print(1 % 0)\n")
        self.assertEqual(ctx.exception.kind, "zero_division")


class AugmentedAssignmentTests(unittest.TestCase):
    def test_all_supported_operators(self):
        source = (
            "a = 1\na += 2\n"
            "b = 7\nb -= 10\n"
            "c = 3\nc *= 4\n"
            "d = 7\nd /= 2\n"
            "e = 7\ne //= 2\n"
            "f = 7\nf %= 4\n"
            "print(a, b, c, d, e, f)\n"
        )
        self.assertEqual(run(source), "3 -3 12 3.5 3 3\n")

    def test_string_and_list_concat(self):
        source = (
            'text = "a"\ntext += "bc"\n'
            "values = [1]\nalias = values\nvalues += [2, 3]\n"
            "print(text, values, alias)\n"
        )
        self.assertEqual(run(source), "abc [1, 2, 3] [1]\n")

    def test_subscript_attribute_and_closure_targets(self):
        source = (
            "values = [1]\nvalues[0] += 4\n"
            'mapping = {"n": 2}\nmapping["n"] *= 3\n'
            "class Box:\n    value: int\n"
            "box = Box(7)\nbox.value -= 1\n"
            "def outer():\n"
            "    x = 1\n"
            "    def read():\n"
            "        return x\n"
            "    x += 4\n"
            "    return read\n"
            "read = outer()\n"
            "print(values, mapping, box.value, read())\n"
        )
        self.assertEqual(run(source), "[5] {'n': 6} 6 5\n")

    def test_target_address_is_evaluated_once_before_rhs(self):
        source = (
            "class Box:\n    value: int\n"
            "values = [1]\nbox = Box(4)\n"
            "def get_values():\n"
            '    print("values")\n'
            "    return values\n"
            "def get_index():\n"
            '    print("index")\n'
            "    return 0\n"
            "def get_box():\n"
            '    print("box")\n'
            "    return box\n"
            "def rhs():\n"
            '    print("rhs")\n'
            "    return 2\n"
            "get_values()[get_index()] += rhs()\n"
            "get_box().value += rhs()\n"
            "print(values[0], box.value)\n"
        )
        self.assertEqual(run(source), "values\nindex\nrhs\nbox\nrhs\n3 6\n")

    def test_errors_match_plain_binary_operations(self):
        cases = (
            ("x = True\nx += 1\n", "type_error"),
            ("x = 1\nx /= 0\n", "zero_division"),
            ('x = "abc"\nx[0] += "z"\n', "type_error"),
            ("x = 1\nx **= 2\n", "syntax_error"),
            ("x = []\nx @= []\n", "syntax_error"),
            ("[x, y] += [1, 2]\n", "syntax_error"),
        )
        for source, kind in cases:
            with self.subTest(source=source):
                engine = SericiteEngine()
                with self.assertRaises(SericiteError) as ctx:
                    engine.create_root(source).run()
                self.assertEqual(ctx.exception.kind, kind)

    def test_failed_operation_or_store_preserves_target(self):
        source = (
            "class Box:\n    value: int\n"
            "box = Box(1)\nvalues = [2]\nmapping = {}\n"
            "try:\n"
            '    values[0] += "bad"\n'
            "except type_error:\n"
            "    pass\n"
            "try:\n"
            "    box.value += 0.5\n"
            "except contract_error:\n"
            "    pass\n"
            "try:\n"
            '    mapping["missing"] += 1\n'
            "except key_error:\n"
            "    pass\n"
            "print(values, box.value, 3 + 4)\n"
        )
        self.assertEqual(run(source), "[2] 1 7\n")

    def test_concat_charges_result_allocation(self):
        engine = SericiteEngine()
        checkpoints = []
        engine.create_root(
            'text = "a"\nvalues = [1]\ncheckpoint()\n'
            'text += "bc"\nvalues += [2, 3]\ncheckpoint()\n',
            functions={
                "checkpoint": lambda: checkpoints.append(
                    engine._contexts[0].alloc_bytes
                )
            },
        ).run()
        checkpoint_result_allocation = 8
        self.assertEqual(
            checkpoints[1] - checkpoints[0],
            3 * 4 + (2 + 3) * 8 + checkpoint_result_allocation,
        )

    def test_list_concat_charges_work_proportional_to_result_size(self):
        counts = {}
        for size in (2, 4):
            engine = SericiteEngine()
            checkpoints = []
            engine.create_root(
                f"values = {list(range(size - 1))!r}\n"
                "checkpoint()\nvalues += [99]\ncheckpoint()\n",
                functions={
                    "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                        checkpoints.append(engine._contexts[0].instruction_count)
                    )
                },
            ).run()
            counts[size] = checkpoints[1] - checkpoints[0]
        self.assertEqual(counts[4] - counts[2], 2)

    def test_concat_enforces_memory_quota(self):
        limits = SericiteLimits(max_total_bytes=1000)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(
            'text = "x"\ni = 0\nwhile i < 20:\n    text += text\n    i += 1\n'
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")


class CompareAndLogicTests(unittest.TestCase):
    def test_comparisons(self):
        self.assertEqual(
            run(
                "print(1 < 2)\nprint(2 <= 1)\nprint(1 == 1.0)\n"
                'print("a" < "b")\nprint(1 != 2)\n'
            ),
            "True\nFalse\nTrue\nTrue\nTrue\n",
        )

    def test_cross_type_equality(self):
        self.assertEqual(run('print(1 == "1")\nprint(None == None)\n'), "False\nTrue\n")

    def test_cross_type_ordering_rejected(self):
        with self.assertRaises(SericiteError) as ctx:
            run('print(1 < "2")\n')
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_short_circuit_and(self):
        self.assertEqual(
            run('x = 0 and missing\nprint(x)\ny = 1 and "yes"\nprint(y)\n'),
            "0\nyes\n",
        )

    def test_short_circuit_or(self):
        self.assertEqual(
            run('x = "" or "fallback"\nprint(x)\ny = "a" or missing\nprint(y)\n'),
            "fallback\na\n",
        )

    def test_truthiness(self):
        self.assertEqual(
            run(
                'print(not "")\nprint(not [])\nprint(not [0])\n'
                "print(not None)\nprint(not 0.0)\n"
            ),
            "True\nTrue\nFalse\nTrue\nTrue\n",
        )


class ControlFlowTests(unittest.TestCase):
    def test_if_elif_else(self):
        source = (
            "x = 5\n"
            "if x < 0:\n"
            '    print("neg")\n'
            "elif x < 10:\n"
            '    print("small")\n'
            "else:\n"
            '    print("big")\n'
        )
        self.assertEqual(run(source), "small\n")

    def test_while_loop(self):
        source = (
            "i = 0\n"
            "total = 0\n"
            "while i < 5:\n"
            "    total = total + i\n"
            "    i = i + 1\n"
            "print(total)\n"
        )
        self.assertEqual(run(source), "10\n")

    def test_break_and_continue(self):
        source = (
            "i = 0\n"
            "while True:\n"
            "    i = i + 1\n"
            "    if i % 2 == 0:\n"
            "        continue\n"
            "    if i > 5:\n"
            "        break\n"
            "    print(i)\n"
        )
        self.assertEqual(run(source), "1\n3\n5\n")

    def test_break_outside_loop_rejected(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("break\n")
        self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_return_outside_function_rejected(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("return 1\n")
        self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_loop_stepping_is_per_statement(self):
        engine = SericiteEngine()
        source = "i = 0\nwhile i < 3:\n    i = i + 1\nprint(i)\n"
        vm = engine.create_root(source)
        seen_i = []
        for _ in range(20):
            snap = vm.step()
            if "i" in snap["locals"]:
                value = snap["locals"]["i"]
                if not seen_i or seen_i[-1] != value:
                    seen_i.append(value)
            if snap["state"] == "done":
                break
        self.assertEqual(vm.snapshot()["state"], "done")
        self.assertEqual(vm.stdout(), "3\n")
        self.assertEqual(seen_i, [0, 1, 2, 3])


class FunctionTests(unittest.TestCase):
    def test_function_def_and_call(self):
        source = "def add(a, b):\n    return a + b\nprint(add(2, 3))\n"
        self.assertEqual(run(source), "5\n")

    def test_recursion_fib(self):
        source = (
            "def fib(n):\n"
            "    if n < 2:\n"
            "        return n\n"
            "    return fib(n - 1) + fib(n - 2)\n"
            "print(fib(10))\n"
        )
        self.assertEqual(run(source), "55\n")

    def test_implicit_none_return(self):
        self.assertEqual(run("def f():\n    x = 1\nprint(f())\n"), "None\n")

    def test_local_scope_isolated(self):
        source = "x = 1\ndef f():\n    x = 99\n    return x\nprint(f())\nprint(x)\n"
        self.assertEqual(run(source), "99\n1\n")

    def test_function_reads_module_globals(self):
        source = "g = 10\ndef f():\n    return g + 1\nprint(f())\n"
        self.assertEqual(run(source), "11\n")

    def test_arity_error(self):
        with self.assertRaises(SericiteError) as ctx:
            run("def f(a, b):\n    return a\nprint(f(1))\n")
        self.assertEqual(ctx.exception.kind, "arity_error")

    def test_recursion_limit(self):
        source = "def f():\n    return f()\nf()\n"
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(vm.snapshot()["state"], "resource_exhausted")


class ListTests(unittest.TestCase):
    def test_list_literal_and_index(self):
        self.assertEqual(run("x = [1, 2, 3]\nprint(x[0])\nprint(x[-1])\n"), "1\n3\n")

    def test_index_write(self):
        self.assertEqual(run("x = [1, 2, 3]\nx[1] = 99\nprint(x)\n"), "[1, 99, 3]\n")

    def test_list_concat(self):
        self.assertEqual(run("print([1] + [2, 3])\n"), "[1, 2, 3]\n")

    def test_string_index(self):
        self.assertEqual(run('print("abc"[1])\n'), "b\n")

    def test_index_out_of_range(self):
        with self.assertRaises(SericiteError) as ctx:
            run("x = [1]\nprint(x[5])\n")
        self.assertEqual(ctx.exception.kind, "index_error")

    def test_string_item_assignment_rejected(self):
        with self.assertRaises(SericiteError) as ctx:
            run('x = "abc"\nx[0] = "z"\n')
        self.assertEqual(ctx.exception.kind, "type_error")


class SliceTests(unittest.TestCase):
    def test_string_start_and_stop(self):
        source = (
            'text = "abcdef"\n'
            "print(text[1:4])\nprint(text[:3])\nprint(text[3:])\n"
            "print(text[-4:-1])\nprint(text[-100:100])\nprint(text[4:1])\n"
        )
        self.assertEqual(run(source), "bcd\nabc\ndef\ncde\nabcdef\n\n")

    def test_list_slices_are_independent_results(self):
        source = (
            "values = [0, 1, 2, 3, 4]\n"
            "result = values[1:4]\nresult[0] = 9\n"
            "copy = values[:]\ncopy[1] = 8\n"
            "print(result, copy)\nprint(values)\n"
        )
        self.assertEqual(run(source), "[9, 2, 3] [0, 8, 2, 3, 4]\n[0, 1, 2, 3, 4]\n")

    def test_positive_and_negative_steps(self):
        source = (
            'text = "abcdef"\nvalues = [0, 1, 2, 3, 4, 5]\n'
            "print(text[::2], text[1:6:2], text[::-1], text[5:1:-2])\n"
            "print(values[::2], values[::-1], values[1:4:-1])\n"
        )
        self.assertEqual(
            run(source),
            "ace bdf fedcba fd\n[0, 2, 4] [5, 4, 3, 2, 1, 0] []\n",
        )

    def test_slice_expressions_are_evaluated_once_in_order(self):
        source = (
            "def get_value():\n"
            '    print("value")\n'
            '    return "abcdef"\n'
            "def get_start():\n"
            '    print("start")\n'
            "    return 0\n"
            "def get_stop():\n"
            '    print("stop")\n'
            "    return 5\n"
            "def get_step():\n"
            '    print("step")\n'
            "    return 2\n"
            "print(get_value()[get_start():get_stop():get_step()])\n"
        )
        self.assertEqual(run(source), "value\nstart\nstop\nstep\nace\n")

    def test_invalid_slices_are_type_errors(self):
        cases = (
            'text = "abc"\nprint(text[::0])\n',
            'text = "abc"\nprint(text[0.0:1])\n',
            'text = "abc"\nprint(text[False:1])\n',
            'text = "abc"\nprint(text[::"x"])\n',
            "values = {1: 2}\nprint(values[0:1])\n",
        )
        for source in cases:
            with self.subTest(source=source):
                engine = SericiteEngine()
                vm = engine.create_root(source)
                with self.assertRaises(SericiteError) as ctx:
                    vm.run()
                self.assertEqual(ctx.exception.kind, "type_error")

    def test_slice_assignment_is_rejected_at_compile_time(self):
        for statement in ("values[0:1] = [3]", "values[0:1] += [3]"):
            with self.subTest(statement=statement):
                engine = SericiteEngine()
                with self.assertRaises(SericiteError) as ctx:
                    engine.create_root(f"values = [1, 2]\n{statement}\n")
                self.assertEqual(ctx.exception.kind, "syntax_error")
                self.assertIn("slice assignment", ctx.exception.message)

    def test_slices_charge_result_allocation(self):
        engine = SericiteEngine()
        checkpoints = []
        engine.create_root(
            'text = "abcdef"\nvalues = [0, 1, 2, 3]\ncheckpoint()\n'
            "a = text[1:5]\nb = values[1:3]\ncheckpoint()\n",
            functions={
                "checkpoint": lambda: checkpoints.append(
                    engine._contexts[0].alloc_bytes
                )
            },
        ).run()
        checkpoint_result_allocation = 8
        self.assertEqual(
            checkpoints[1] - checkpoints[0],
            4 * 4 + 2 * 8 + checkpoint_result_allocation,
        )

    def test_slices_charge_work_proportional_to_result_size(self):
        for kind in ("str", "list"):
            counts = {}
            for size in (100, 1000):
                engine = SericiteEngine()
                checkpoints = []
                engine.create_root(
                    "value = get()\ncheckpoint()\nresult = value[:]\ncheckpoint()\n",
                    functions={
                        "get": lambda kind=kind, size=size: (
                            "x" * size if kind == "str" else [0] * size
                        ),
                        "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                            checkpoints.append(engine._contexts[0].instruction_count)
                        ),
                    },
                ).run()
                counts[size] = checkpoints[1] - checkpoints[0]
            with self.subTest(kind=kind):
                self.assertGreater(counts[1000], counts[100])

    def test_repeated_slices_enforce_memory_quota(self):
        limits = SericiteLimits(max_total_bytes=2000)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(
            "values = range(100)\nwhile True:\n    values = values[:]\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")


class BuiltinTests(unittest.TestCase):
    def test_print_end(self):
        source = (
            'print("a")\nprint("b", end="")\nprint("c", "d", end="!")\nprint(end="?")\n'
        )
        self.assertEqual(run(source), "a\nbc d!?")

    def test_print_end_must_be_string(self):
        for value in ("None", "1", "[]"):
            with self.subTest(value=value):
                with self.assertRaises(SericiteError) as ctx:
                    run(f'print("x", end={value})\n')
                self.assertEqual(ctx.exception.kind, "type_error")

    def test_print_rejects_unknown_keyword(self):
        with self.assertRaises(SericiteError) as ctx:
            run('print("x", sep=" ")\n')
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_print_end_counts_toward_output_limit(self):
        limits = SericiteLimits(max_output_bytes=3)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root('print("ab", end="cd")')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_len(self):
        self.assertEqual(run('print(len("abcd"))\nprint(len([1, 2]))\n'), "4\n2\n")

    def test_int_float_str(self):
        self.assertEqual(
            run(
                'print(int("42"))\nprint(int(3.9))\nprint(float("0.5"))\n'
                "print(str(12))\nprint(str(None))\n"
            ),
            "42\n3\n0.5\n12\nNone\n",
        )

    def test_repr_strings_and_containers(self):
        text = 'first\nsecond\t\\"你好'
        self.assertEqual(run(f"print(repr({text!r}))"), f"{text!r}\n")
        self.assertEqual(
            run(f"print(repr([{text!r}, 1, True, None]))"),
            f"[{text!r}, 1, True, None]\n",
        )
        self.assertEqual(run("print(repr(42))\nprint(repr(None))"), "42\nNone\n")

    def test_repr_respects_result_size_limit(self):
        engine = SericiteEngine(SericiteLimits(max_string_bytes=3))
        vm = engine.create_root('result = repr("\\n")')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_repr_limit_includes_quotes_and_escapes(self):
        engine = SericiteEngine(SericiteLimits(max_string_bytes=10))
        vm = engine.create_root('result = repr("abcdefgh")')
        vm.run()
        self.assertEqual(vm.snapshot()["locals"]["result"], "'abcdefgh'")

        vm = engine.create_root('result = repr("abcdefghij")')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_repr_shared_containers_use_safe_placeholders(self):
        self.assertEqual(run("x = [1]\nprint(repr([x, x]))"), "[[1], [...]]\n")

    def test_repr_charges_scaled_work_and_result_allocation(self):
        counts = {}
        for size in (10, 1000):
            engine = SericiteEngine()
            checkpoints = []
            text = "\n" * size
            vm = engine.create_root(
                f"value = {text!r}\ncheckpoint()\nresult = repr(value)\ncheckpoint()",
                functions={
                    "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                        checkpoints.append(
                            (
                                engine._contexts[0].instruction_count,
                                engine._contexts[0].alloc_bytes,
                            )
                        )
                    )
                },
            )
            vm.run()
            result = engine._contexts[0].frames[0].locals["result"]
            work = checkpoints[1][0] - checkpoints[0][0]
            allocation = checkpoints[1][1] - checkpoints[0][1]
            counts[size] = work
            self.assertGreaterEqual(work, size // 64)
            self.assertEqual(allocation, len(result) * 4 + 8)
        self.assertGreater(counts[1000], counts[10])

    def test_conversion_error(self):
        with self.assertRaises(SericiteError) as ctx:
            run('print(int("abc"))\n')
        self.assertEqual(ctx.exception.kind, "conversion_error")

    def test_range(self):
        self.assertEqual(
            run("print(range(4))\nprint(range(1, 5))\nprint(range(0, 6, 2))\n"),
            "[0, 1, 2, 3]\n[1, 2, 3, 4]\n[0, 2, 4]\n",
        )

    def test_range_step_zero(self):
        with self.assertRaises(SericiteError):
            run("print(range(1, 5, 0))\n")


class ResourceLimitTests(unittest.TestCase):
    def test_instruction_limit_kills_infinite_loop(self):
        engine = SericiteEngine(limits=SericiteLimits(max_instructions=10_000))
        vm = engine.create_root("while True:\n    x = 1\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        snap = vm.snapshot()
        self.assertEqual(snap["state"], "resource_exhausted")
        self.assertEqual(snap["instruction_count"], 10_000)

    def test_output_limit(self):
        limits = SericiteLimits(max_output_bytes=10)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root('print("0123456789")\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(vm.snapshot()["state"], "resource_exhausted")

    def test_list_size_limit_via_range(self):
        limits = SericiteLimits(max_list_size=100)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root("x = range(101)\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_child_vm_limit(self):
        limits = SericiteLimits(max_child_vms=1)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root('a = VM("x = 1")\nb = VM("y = 2")\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_child_vm_shares_instruction_budget_independence(self):
        engine = SericiteEngine()
        vm = engine.create_root('sub = VM("while True:\\n    x = 1")\nsub.run()\n')
        with self.assertRaises(SericiteError):
            vm.run()
        self.assertEqual(vm.snapshot()["state"], "resource_exhausted")

    def test_terminate(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'sub = VM("while True:\\n    x = 1")\nsub.step()\nsub.terminate()\nprint("stopped")\n'
        )
        output = vm.run()
        self.assertEqual(output, "stopped\n")

    def test_instruction_count_visible_in_snapshot(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 1\ny = 2\n")
        vm.run()
        self.assertGreater(vm.snapshot()["instruction_count"], 0)


class ErrorReportingTests(unittest.TestCase):
    def test_error_carries_line(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 1\ny = missing\n")
        with self.assertRaises(SericiteError):
            vm.run()
        snap = vm.snapshot()
        self.assertEqual(snap["state"], "error")
        self.assertEqual(snap["error"]["kind"], "name_error")
        self.assertEqual(snap["error"]["line"], 2)

    def test_error_line_inside_loop(self):
        engine = SericiteEngine()
        vm = engine.create_root("i = 0\nwhile i < 3:\n    i = i + 1\n    x = 1 / 0\n")
        with self.assertRaises(SericiteError):
            vm.run()
        self.assertEqual(vm.snapshot()["error"]["line"], 4)

    def test_step_instruction_granularity(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 1 + 2\n")
        count = 0
        while vm.snapshot()["state"] == "ready":
            vm.step_instruction()
            count += 1
            if count > 100:
                self.fail("step_instruction did not terminate")
        self.assertEqual(vm.snapshot()["locals"]["x"], 3)
        self.assertGreater(count, 1)


if __name__ == "__main__":
    unittest.main()
