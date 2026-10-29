import unittest

from sericite import isa
from sericite.compiler import compile_source
from sericite.engine import SericiteEngine, SericiteLimits
from sericite.errors import SericiteError


def run(source, limits=None):
    engine = SericiteEngine(limits=limits)
    return engine.create_root(source).run()


class ClosureTests(unittest.TestCase):
    def test_decorator_with_explicit_application(self):
        source = (
            "def trace(func):\n"
            "    def wrapper(x):\n"
            "        print('before')\n"
            "        result = func(x)\n"
            "        print('after')\n"
            "        return result\n"
            "    return wrapper\n"
            "def double(x):\n"
            "    return x * 2\n"
            "traced = trace(double)\n"
            "print(traced(21))\n"
        )
        self.assertEqual(run(source), "before\nafter\n42\n")

    def test_reads_latest_outer_binding(self):
        source = (
            "def outer():\n"
            "    x = 1\n"
            "    def read():\n"
            "        return x\n"
            "    x = 2\n"
            "    return read\n"
            "print(outer()())\n"
        )
        self.assertEqual(run(source), "2\n")

    def test_sibling_closures_share_cells(self):
        source = (
            "def outer():\n"
            "    x = 1\n"
            "    def first():\n"
            "        return x\n"
            "    def second():\n"
            "        return x + 1\n"
            "    x = 10\n"
            "    return [first, second]\n"
            "functions = outer()\n"
            "print(functions[0](), functions[1]())\n"
        )
        self.assertEqual(run(source), "10 11\n")

    def test_separate_calls_have_independent_cells(self):
        source = (
            "def make(x):\n"
            "    def read():\n"
            "        return x\n"
            "    return read\n"
            "first = make(10)\n"
            "second = make(20)\n"
            "print(first(), second(), first())\n"
        )
        self.assertEqual(run(source), "10 20 10\n")

    def test_multilevel_capture_passes_through_middle(self):
        source = (
            "def outer():\n"
            "    x = 42\n"
            "    def middle():\n"
            "        def inner():\n"
            "            return x\n"
            "        return inner\n"
            "    return middle\n"
            "print(outer()()())\n"
        )
        self.assertEqual(run(source), "42\n")

    def test_loop_variable_is_late_bound(self):
        source = (
            "def make():\n"
            "    functions = []\n"
            "    for i in [1, 2, 3]:\n"
            "        def read():\n"
            "            return i\n"
            "        functions = functions + [read]\n"
            "    return functions\n"
            "functions = make()\n"
            "print(functions[0](), functions[1](), functions[2]())\n"
        )
        self.assertEqual(run(source), "3 3 3\n")

    def test_mutable_value_is_shared(self):
        source = (
            "def outer():\n"
            "    values = [1]\n"
            "    def read():\n"
            "        return values[0]\n"
            "    values[0] = 9\n"
            "    return read\n"
            "print(outer()())\n"
        )
        self.assertEqual(run(source), "9\n")

    def test_default_is_snapshot_while_closure_is_late_bound(self):
        source = (
            "def outer():\n"
            "    x = 1\n"
            "    def read(value=x):\n"
            "        return [value, x]\n"
            "    x = 2\n"
            "    return read\n"
            "print(outer()())\n"
        )
        self.assertEqual(run(source), "[1, 2]\n")

    def test_inner_assignment_shadows_outer_binding(self):
        source = (
            "def outer():\n"
            "    x = 1\n"
            "    def inner():\n"
            "        x = 2\n"
            "        return x\n"
            "    return [inner, x]\n"
            "result = outer()\n"
            "print(result[0](), result[1])\n"
        )
        self.assertEqual(run(source), "2 1\n")

    def test_unbound_local_does_not_fall_back_to_global(self):
        source = (
            "x = 10\n"
            "def f():\n"
            "    try:\n"
            "        print(x)\n"
            "    except name_error:\n"
            "        print('unbound')\n"
            "    x = 1\n"
            "f()\n"
        )
        self.assertEqual(run(source), "unbound\n")

    def test_unbound_free_variable_raises_name_error(self):
        source = (
            "def outer():\n"
            "    def read():\n"
            "        return x\n"
            "    try:\n"
            "        read()\n"
            "    except name_error:\n"
            "        print('unbound')\n"
            "    x = 1\n"
            "    print(read())\n"
            "outer()\n"
        )
        self.assertEqual(run(source), "unbound\n1\n")

    def test_nested_recursion(self):
        source = (
            "def outer():\n"
            "    def fib(n):\n"
            "        if n < 2:\n"
            "            return n\n"
            "        return fib(n - 1) + fib(n - 2)\n"
            "    return fib\n"
            "print(outer()(10))\n"
        )
        self.assertEqual(run(source), "55\n")

    def test_nested_mutual_recursion(self):
        source = (
            "def outer():\n"
            "    def even(n):\n"
            "        if n == 0:\n"
            "            return True\n"
            "        return odd(n - 1)\n"
            "    def odd(n):\n"
            "        if n == 0:\n"
            "            return False\n"
            "        return even(n - 1)\n"
            "    return even\n"
            "print(outer()(10))\n"
        )
        self.assertEqual(run(source), "True\n")

    def test_captures_except_binding(self):
        source = (
            "def outer():\n"
            "    try:\n"
            "        x = 1 / 0\n"
            "    except zero_division as error:\n"
            "        def read():\n"
            "            return error.message\n"
            "    return read\n"
            "print(outer()())\n"
        )
        self.assertEqual(run(source), "division by zero\n")


class ClosureGrantTests(unittest.TestCase):
    def test_granted_closure_keeps_definition_environment(self):
        child = "base = 1000\nx = 1000\nprint(f(2))\n"
        source = (
            "base = 10\n"
            "def make(x):\n"
            "    def add(y):\n"
            "        return base + x + y\n"
            "    return add\n"
            "f = make(5)\n"
            "sub = VM(" + repr(child) + ", functions={'f': f})\n"
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "17\n\n")

    def test_returned_closure_and_regrant_keep_original_globals(self):
        child = (
            "base = 1000\n"
            "f = make(5)\n"
            "print(f(2))\n"
            'grandchild = VM("print(f(3))\\n", functions={"f": f})\n'
            "print(grandchild.run())\n"
        )
        source = (
            "base = 10\n"
            "def make(x):\n"
            "    def add(y):\n"
            "        return base + x + y\n"
            "    return add\n"
            "sub = VM(" + repr(child) + ", functions={'make': make})\n"
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "17\n18\n\n\n")


class DecoratorTests(unittest.TestCase):
    def test_trace_decorator(self):
        source = (
            "def trace(func):\n"
            "    def wrapper(x):\n"
            "        print('before')\n"
            "        result = func(x)\n"
            "        print('after')\n"
            "        return result\n"
            "    return wrapper\n"
            "@trace\n"
            "def double(x):\n"
            "    return x * 2\n"
            "print(double(21))\n"
        )
        self.assertEqual(run(source), "before\nafter\n42\n")

    def test_decorator_evaluation_and_application_order(self):
        source = (
            "def make(name):\n"
            "    print('eval', name)\n"
            "    def decorate(func):\n"
            "        print('apply', name)\n"
            "        return func\n"
            "    return decorate\n"
            "@make('one')\n"
            "@make('two')\n"
            "def value():\n"
            "    return 42\n"
            "print(value())\n"
        )
        self.assertEqual(run(source), "eval one\neval two\napply two\napply one\n42\n")

    def test_decorator_expression_reads_closure_cell(self):
        source = (
            "def outer():\n"
            "    label = 'a'\n"
            "    def expose():\n"
            "        return label\n"
            "    def decorate(prefix):\n"
            "        def wrap_it(func):\n"
            "            def wrapped():\n"
            "                return prefix + func()\n"
            "            return wrapped\n"
            "        return wrap_it\n"
            "    @decorate(label)\n"
            "    def value():\n"
            "        return '1'\n"
            "    return [value, expose]\n"
            "result = outer()\n"
            "print(result[0](), result[1]())\n"
        )
        self.assertEqual(run(source), "a1 a\n")

    def test_decorated_nested_function_recurses_through_result(self):
        source = (
            "def outer():\n"
            "    calls = [0]\n"
            "    def counted(func):\n"
            "        def wrapped(n):\n"
            "            calls[0] = calls[0] + 1\n"
            "            return func(n)\n"
            "        return wrapped\n"
            "    @counted\n"
            "    def down(n):\n"
            "        if n == 0:\n"
            "            return 0\n"
            "        return down(n - 1)\n"
            "    def read_calls():\n"
            "        return calls[0]\n"
            "    return [down, read_calls]\n"
            "result = outer()\n"
            "print(result[0](3), result[1]())\n"
        )
        self.assertEqual(run(source), "0 4\n")


class ClosureRuntimeTests(unittest.TestCase):
    def test_snapshot_unwraps_cells(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            "def outer():\n"
            "    x = 1\n"
            "    def read():\n"
            "        return x\n"
            "    return read\n"
            "outer()\n"
        )
        for _ in range(20):
            snapshot = vm.step_instruction()
            if snapshot["locals"].get("x") == 1:
                break
        else:
            self.fail("did not reach the initialized closure cell")
        self.assertEqual(snapshot["locals"]["x"], 1)

    def test_finally_does_not_accumulate_function_code(self):
        source = (
            "def outer():\n"
            "    try:\n"
            "        x = 1\n"
            "    finally:\n"
            "        def read():\n"
            "            return x\n"
            "    return read\n"
        )
        module = compile_source(source, "<test>")
        outer = next(
            instr.arg[0] for instr in module.instrs if instr.op == isa.MAKE_FUNCTION
        )
        read_units = [
            instr.arg[0] for instr in outer.instrs if instr.op == isa.MAKE_FUNCTION
        ]
        self.assertTrue(read_units)
        for code in read_units:
            self.assertEqual(sum(instr.op == isa.RETURN for instr in code.instrs), 2)
        self.assertEqual(run(source + "print(outer()())\n"), "1\n")

    def test_cells_and_closure_environment_consume_memory_quota(self):
        source = (
            "def make():\n"
            "    x = 1\n"
            "    def read():\n"
            "        return x\n"
            "    return read\n"
            "f = make()\n"
        )
        engine = SericiteEngine(limits=SericiteLimits(max_total_bytes=135))
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

        engine = SericiteEngine(limits=SericiteLimits(max_total_bytes=136))
        self.assertEqual(engine.create_root(source).run(), "")


if __name__ == "__main__":
    unittest.main()
