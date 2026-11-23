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


class GlobalTests(unittest.TestCase):
    def test_global_counter_reads_and_writes_module_binding(self):
        source = (
            "count = 0\n"
            "def increment():\n"
            "    global count\n"
            "    count += 1\n"
            "    return count\n"
            "print(increment(), increment(), count)\n"
        )
        self.assertEqual(run(source), "1 2 2\n")

    def test_global_does_not_capture_same_named_outer_local(self):
        source = (
            "value = 'module'\n"
            "def outer():\n"
            "    value = 'outer'\n"
            "    def change():\n"
            "        global value\n"
            "        value = 'changed'\n"
            "    def read():\n"
            "        return value\n"
            "    change()\n"
            "    return [value, read()]\n"
            "result = outer()\n"
            "print(result[0], result[1], value)\n"
        )
        self.assertEqual(run(source), "outer outer changed\n")

    def test_module_level_global_is_allowed(self):
        source = (
            "global value\n"
            "value = 1\n"
            "def read():\n"
            "    global value\n"
            "    return value\n"
            "print(read())\n"
        )
        self.assertEqual(run(source), "1\n")

    def test_global_loop_unpack_and_function_bindings(self):
        source = (
            "first = 0\n"
            "second = 0\n"
            "def bind():\n"
            "    global first, second, generated\n"
            "    for first in [1]:\n"
            "        (first, second) = (2, 3)\n"
            "    def generated():\n"
            "        return 4\n"
            "bind()\n"
            "print(first, second, generated())\n"
        )
        self.assertEqual(run(source), "2 3 4\n")

    def test_global_except_binding_writes_module(self):
        source = (
            "error = None\n"
            "def capture():\n"
            "    global error\n"
            "    try:\n"
            "        1 / 0\n"
            "    except zero_division as error:\n"
            "        pass\n"
            "capture()\n"
            "print(error.kind)\n"
        )
        self.assertEqual(run(source), "zero_division\n")

    def test_global_import_and_imported_module_globals_are_independent(self):
        engine = SericiteEngine()
        fs = engine.create_vfs()
        fs.write_file(
            "/helper.sericite",
            "value = 1\ndef increment():\n    global value\n    value += 1\n",
        )
        root = engine.create_root(
            "value = 100\n"
            "def load():\n"
            "    import helper\n"
            "    global helper\n"
            "load()\n"
            "helper.increment()\n"
            "print(value, helper.value)\n",
            fs=fs,
        )
        self.assertEqual(root.run(), "100 2\n")


class NonlocalTests(unittest.TestCase):
    def test_nonlocal_binds_nearest_outer_function(self):
        source = (
            "def outer():\n"
            "    value = 'outer'\n"
            "    def middle():\n"
            "        value = 'middle'\n"
            "        def inner():\n"
            "            nonlocal value\n"
            "            value = 'changed'\n"
            "        inner()\n"
            "        return value\n"
            "    def read():\n"
            "        return value\n"
            "    return [middle(), read()]\n"
            "result = outer()\n"
            "print(result[0], result[1])\n"
        )
        self.assertEqual(run(source), "changed outer\n")

    def test_nonlocal_passes_through_middle_scope(self):
        source = (
            "def outer():\n"
            "    value = 1\n"
            "    def middle():\n"
            "        def inner():\n"
            "            nonlocal value\n"
            "            value += 1\n"
            "            return value\n"
            "        return inner\n"
            "    return middle\n"
            "inner = outer()()\n"
            "print(inner(), inner())\n"
        )
        self.assertEqual(run(source), "2 3\n")

    def test_nonlocal_sibling_closures_share_binding(self):
        source = (
            "def outer():\n"
            "    value = 0\n"
            "    def increment():\n"
            "        nonlocal value\n"
            "        value += 1\n"
            "    def read():\n"
            "        return value\n"
            "    return [increment, read]\n"
            "functions = outer()\n"
            "functions[0]()\n"
            "functions[0]()\n"
            "print(functions[1]())\n"
        )
        self.assertEqual(run(source), "2\n")

    def test_nonlocal_calls_have_independent_bindings(self):
        source = (
            "def make():\n"
            "    value = 0\n"
            "    def increment():\n"
            "        nonlocal value\n"
            "        value += 1\n"
            "        return value\n"
            "    return increment\n"
            "first = make()\n"
            "second = make()\n"
            "print(first(), first(), second(), first())\n"
        )
        self.assertEqual(run(source), "1 2 1 3\n")

    def test_nonlocal_loop_unpack_and_function_bindings(self):
        source = (
            "def outer():\n"
            "    first = 0\n"
            "    second = 0\n"
            "    generated = None\n"
            "    def bind():\n"
            "        nonlocal first, second, generated\n"
            "        for first in [1]:\n"
            "            (first, second) = (2, 3)\n"
            "        def generated():\n"
            "            return 4\n"
            "    bind()\n"
            "    return [first, second, generated]\n"
            "result = outer()\n"
            "print(result[0], result[1], result[2]())\n"
        )
        self.assertEqual(run(source), "2 3 4\n")

    def test_nonlocal_except_binding_writes_outer_cell(self):
        source = (
            "def outer():\n"
            "    error = None\n"
            "    def capture():\n"
            "        nonlocal error\n"
            "        try:\n"
            "            1 / 0\n"
            "        except zero_division as error:\n"
            "            pass\n"
            "    capture()\n"
            "    return error\n"
            "print(outer().kind)\n"
        )
        self.assertEqual(run(source), "zero_division\n")

    def test_nonlocal_import_may_precede_declaration(self):
        engine = SericiteEngine()
        fs = engine.create_vfs()
        fs.write_file("/helper.sericite", "value = 9\n")
        root = engine.create_root(
            "def outer():\n"
            "    helper = None\n"
            "    def inner():\n"
            "        import helper\n"
            "        nonlocal helper\n"
            "        return helper.value\n"
            "    return inner\n"
            "print(outer()())\n",
            fs=fs,
        )
        self.assertEqual(root.run(), "9\n")

    def test_nonlocal_decorator_shares_call_count(self):
        source = (
            "def outer():\n"
            "    calls = 0\n"
            "    def counted(func):\n"
            "        def wrapped(*args, **kwargs):\n"
            "            nonlocal calls\n"
            "            calls += 1\n"
            "            return func(*args, **kwargs)\n"
            "        return wrapped\n"
            "    @counted\n"
            "    def add(a, b=0):\n"
            "        return a + b\n"
            "    def read_calls():\n"
            "        return calls\n"
            "    return [add, read_calls]\n"
            "result = outer()\n"
            "print(result[0](2, b=3), result[1]())\n"
        )
        self.assertEqual(run(source), "5 1\n")


class ScopeDeclarationValidationTests(unittest.TestCase):
    def test_invalid_declarations_are_compile_errors(self):
        cases = (
            "nonlocal value\n",
            "value = 1\ndef f():\n    nonlocal value\n",
            "def f(value):\n    global value\n",
            "def outer():\n    value = 1\n    def f(value):\n        nonlocal value\n",
            "def f():\n    global value\n    nonlocal value\n",
            "def f():\n    value = 1\n    global value\n",
            "value = None\nimport value\nglobal value\n",
            "import value\nvalue = None\nglobal value\n",
            "def f():\n    print(value)\n    global value\n",
            "def f():\n    global value\n    value: int = 1\n",
            "def outer():\n    value = 1\n    def f():\n        nonlocal value\n        value: int = 2\n",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_dunder_declarations_are_rejected(self):
        cases = (
            "global __hidden\n",
            "nonlocal __hidden\n",
            "def f():\n    global __hidden\n",
            "def f():\n    nonlocal __hidden\n",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")
                self.assertIn("dunder names are not available", ctx.exception.message)

    def test_import_forms_may_precede_declarations(self):
        cases = (
            "import helper\nglobal helper\n",
            "from package import helper\nglobal helper\n",
            "import package.helper as alias\nglobal alias\n",
            (
                "def outer():\n"
                "    helper = None\n"
                "    def inner():\n"
                "        from package import helper\n"
                "        nonlocal helper\n"
            ),
            (
                "def outer():\n"
                "    alias = None\n"
                "    def inner():\n"
                "        from package import helper as alias\n"
                "        nonlocal alias\n"
            ),
        )
        for source in cases:
            with self.subTest(source=source):
                compile_source(source, "<test>")

    def test_nonlocal_cannot_skip_an_intermediate_global_declaration(self):
        source = (
            "value = 0\n"
            "def outer():\n"
            "    value = 1\n"
            "    def middle():\n"
            "        global value\n"
            "        def inner():\n"
            "            nonlocal value\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            SericiteEngine().create_root(source)
        self.assertEqual(ctx.exception.kind, "syntax_error")
        self.assertIn("no binding for nonlocal 'value'", ctx.exception.message)


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

    def test_granted_global_writes_definition_module(self):
        child = "value = 100\nf()\nprint(value)\n"
        source = (
            "value = 1\n"
            "def set_value():\n"
            "    global value\n"
            "    value = 7\n"
            "sub = VM(" + repr(child) + ", functions={'f': set_value})\n"
            "print(sub.run())\n"
            "print(value)\n"
        )
        self.assertEqual(run(source), "100\n\n7\n")

    def test_granted_nonlocal_closures_keep_shared_cells(self):
        child = "increment()\nincrement()\nprint(read())\n"
        source = (
            "def outer():\n"
            "    value = 0\n"
            "    def increment():\n"
            "        nonlocal value\n"
            "        value += 1\n"
            "    def read():\n"
            "        return value\n"
            "    return [increment, read]\n"
            "functions = outer()\n"
            "sub = VM("
            + repr(child)
            + ", functions={'increment': functions[0], 'read': functions[1]})\n"
            "print(sub.run())\n"
            "functions[0]()\n"
            "print(functions[1]())\n"
        )
        self.assertEqual(run(source), "2\n\n3\n")

    def test_granted_global_name_error_stays_redacted(self):
        child = "try:\n    f()\nexcept name_error as error:\n    print(error.message)\n"
        source = (
            "def fail():\n"
            "    global definition_only_name\n"
            "    return definition_only_name\n"
            "sub = VM(" + repr(child) + ", functions={'f': fail})\n"
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "name is not defined\n\n")


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
