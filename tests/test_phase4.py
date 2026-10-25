import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


def run(source, inputs=None, limits=None, functions=None):
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source, functions=functions)
    return vm.run(inputs)


class DictTests(unittest.TestCase):
    def test_literal_and_index(self):
        self.assertEqual(run('d = {"a": 1, "b": 2}\nprint(d["a"], d["b"])\n'), "1 2\n")

    def test_empty_dict(self):
        self.assertEqual(run("d = {}\nprint(len(d), d == {})\n"), "0 True\n")

    def test_store_new_key_and_overwrite(self):
        source = 'd = {"a": 1}\nd["b"] = 2\nd["a"] = 9\nprint(d["a"], d["b"])\n'
        self.assertEqual(run(source), "9 2\n")

    def test_missing_key_raises_key_error(self):
        source = (
            "d = {}\n"
            "try:\n"
            '    x = d["missing"]\n'
            "except key_error as e:\n"
            '    print("caught: " + e)\n'
        )
        self.assertEqual(run(source), "caught: missing key: missing\n")

    def test_unhashable_key_rejected(self):
        source = "d = {}\nd[[1]] = 2\n"
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_literal_unhashable_key_rejected(self):
        engine = SericiteEngine()
        vm = engine.create_root("d = {[1]: 2}\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_len_and_truthiness(self):
        source = (
            "d = {}\n"
            "if not d:\n"
            '    print("empty")\n'
            'd["x"] = 1\n'
            "if d:\n"
            '    print("full", len(d))\n'
        )
        self.assertEqual(run(source), "empty\nfull 1\n")

    def test_structural_equality(self):
        source = 'print({"a": [1, 2]} == {"a": [1, 2]}, {"a": 1} == {"a": 2})\n'
        self.assertEqual(run(source), "True False\n")

    def test_mixed_key_types(self):
        source = (
            'd = {"s": 1, 2: "two", True: "t", None: "n", 1.5: "f"}\n'
            'print(d["s"], d[2], d[True], d[None], d[1.5])\n'
        )
        self.assertEqual(run(source), "1 two t n f\n")

    def test_keys_method(self):
        self.assertEqual(run('d = {"b": 2, "a": 1}\nprint(d.keys())\n'), "['b', 'a']\n")

    def test_keys_is_no_longer_a_builtin(self):
        source = (
            "try:\n"
            "    keys({})\n"
            "except name_error:\n"
            '    print("not a builtin")\n'
            'keys = "ordinary name"\n'
            "print(keys)\n"
        )
        self.assertEqual(run(source), "not a builtin\nordinary name\n")

    def test_in_operator(self):
        source = (
            'print("a" in {"a": 1}, "z" in {"a": 1})\n'
            "print(2 in [1, 2], 9 not in [1, 2])\n"
            'print("sub" in "substring", "zz" not in "substring")\n'
        )
        self.assertEqual(run(source), "True False\nTrue True\nTrue True\n")

    def test_in_rejects_bad_operands(self):
        engine = SericiteEngine()
        vm = engine.create_root("print(1 in 2)\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_dict_size_limit_on_store(self):
        limits = SericiteLimits(max_dict_size=2)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root('d = {}\nd["a"] = 1\nd["b"] = 2\nd["c"] = 3\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_dict_size_limit_on_literal(self):
        limits = SericiteLimits(max_dict_size=1)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root('d = {"a": 1, "b": 2}\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_dict_option_via_child_vm(self):
        source = (
            'sub = VM("d = {}\\nd[\\"a\\"] = 1\\nd[\\"b\\"] = 2\\n", '
            "max_dict_size=1)\n"
            "sub.run()\n"
        )
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")


class HostFunctionTests(unittest.TestCase):
    def test_basic_roundtrip(self):
        self.assertEqual(
            run("print(add(2, 3))\n", functions={"add": lambda a, b: a + b}),
            "5\n",
        )

    def test_structured_dict_result(self):
        def http_get(url):
            return {"status": 200, "body": "hello " + url, "tags": ["x", "y"]}

        source = (
            'r = http_get("example.com")\nprint(r["status"], r["body"], r["tags"][1])\n'
        )
        self.assertEqual(
            run(source, functions={"http_get": http_get}),
            "200 hello example.com y\n",
        )

    def test_result_is_deep_copied(self):
        shared = {"items": [1, 2]}

        def give():
            return shared

        source = 'a = give()\na["items"][0] = 99\nb = give()\nprint(b["items"][0])\n'
        self.assertEqual(run(source, functions={"give": give}), "1\n")
        self.assertEqual(shared, {"items": [1, 2]})

    def test_argument_is_deep_copied(self):
        seen = []

        def take(value):
            seen.append(list(value))
            value[0] = -1

        source = "a = [1, 2]\ntake(a)\nprint(a[0])\n"
        self.assertEqual(run(source, functions={"take": take}), "1\n")
        self.assertEqual(seen, [[1, 2]])

    def test_handle_cannot_cross_boundary(self):
        source = (
            'sub = VM("")\n'
            "try:\n"
            "    probe(sub)\n"
            "except ffi_error:\n"
            '    print("blocked")\n'
        )
        self.assertEqual(
            run(source, functions={"probe": lambda value: None}), "blocked\n"
        )

    def test_alien_result_rejected(self):
        source = 'try:\n    bad()\nexcept ffi_error as e:\n    print("rejected")\n'
        self.assertEqual(run(source, functions={"bad": lambda: object()}), "rejected\n")

    def test_host_exception_becomes_ffi_error(self):
        def boom():
            raise ValueError("kaput /home/secret")

        source = 'try:\n    boom()\nexcept ffi_error as e:\n    print("caught: " + e)\n'
        output = run(source, functions={"boom": boom})
        # no host exception message (prevents leaking host internals), only the exception type name
        self.assertIn("ValueError", output)
        self.assertIn("boom", output)
        self.assertNotIn("kaput", output)
        self.assertNotIn("/home/secret", output)

    def test_host_sericite_error_passes_through(self):
        def picky(value):
            raise SericiteError("host says no", kind="file_not_found")

        source = (
            'try:\n    picky(1)\nexcept file_not_found:\n    print("precise kind")\n'
        )
        self.assertEqual(run(source, functions={"picky": picky}), "precise kind\n")

    def test_grant_name_conflicts_with_builtin(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("print(1)\n", functions={"len": lambda x: 0})
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_grant_name_must_be_identifier(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("print(1)\n", functions={"not a name": lambda: 0})
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_grant_must_be_callable(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("print(1)\n", functions={"f": 42})
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_granted_function_respects_output_quota(self):
        limits = SericiteLimits(max_output_bytes=4)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(
            'print(shout("hello world"))\n',
            functions={"shout": lambda text: text.upper()},
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")


class ChildGrantTests(unittest.TestCase):
    def test_parent_grants_sericite_function(self):
        source = (
            "def double(x):\n"
            "    return x * 2\n"
            'sub = VM("print(double(21))\\n", functions={"double": double})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "42\n\n")

    def test_granted_function_sees_parent_globals(self):
        source = (
            "base = 100\n"
            "def add_base(x):\n"
            "    return x + base\n"
            'sub = VM("print(add_base(1))\\n", functions={"add_base": add_base})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "101\n\n")

    def test_granted_function_calls_parent_helpers(self):
        source = (
            "def helper(x):\n"
            "    return x + 1\n"
            "def outer(x):\n"
            "    return helper(x) * 10\n"
            'sub = VM("print(outer(2))\\n", functions={"outer": outer})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "30\n\n")

    def test_granted_function_keeps_definition_granted_environment(self):
        child = (
            "def helper():\n"
            "    return 'child'\n"
            'grandchild = VM("print(f())\\n", '
            "functions={'f': f, 'helper': helper})\n"
            "print(grandchild.run())\n"
        )
        source = (
            "def f():\n"
            "    return helper()\n"
            "sub = VM(" + repr(child) + ", functions={'f': f})\n"
            "print(sub.run())\n"
        )
        output = run(source, functions={"helper": lambda: "parent"})
        self.assertEqual(output, "parent\n\n\n")

    def test_caller_granted_name_cannot_shadow_missing_definition_name(self):
        child = (
            "def helper():\n"
            "    return 'child'\n"
            'grandchild = VM("print(f())\\n", '
            "functions={'f': f, 'helper': helper})\n"
            "print(grandchild.run())\n"
        )
        source = (
            "def f():\n"
            "    try:\n"
            "        return helper()\n"
            "    except name_error:\n"
            "        return 'safe'\n"
            "sub = VM(" + repr(child) + ", functions={'f': f})\n"
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "safe\n\n\n")

    def test_child_globals_not_visible_to_granted_function(self):
        child = (
            "base = 5\n"
            "try:\n"
            "    print(read_base())\n"
            "except name_error:\n"
            "    print('no base')\n"
        )
        source = (
            "def read_base():\n"
            "    return base\n"
            "sub = VM(" + repr(child) + ", functions={'read_base': read_base})\n"
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "no base\n\n")

    def test_regrant_host_function_to_child(self):
        source = (
            'sub = VM("print(host_add(3, 4))\\n", '
            'functions={"host_add": host_add})\n'
            "print(sub.run())\n"
        )
        output = run(source, functions={"host_add": lambda a, b: a + b})
        self.assertEqual(output, "7\n\n")

    def test_regrant_across_two_levels(self):
        source = (
            'mid = VM("sub = VM(\\"print(host_add(1, 2))\\\\n\\", '
            'functions={\\"host_add\\": host_add})\\nprint(sub.run())\\n", '
            'functions={"host_add": host_add})\n'
            "print(mid.run())\n"
        )
        output = run(source, functions={"host_add": lambda a, b: a + b})
        self.assertEqual(output, "3\n\n\n")

    def test_functions_option_must_be_dict(self):
        source = 'sub = VM("", functions=[1, 2])\n'
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_functions_option_rejects_non_function(self):
        source = 'sub = VM("", functions={"f": 42})\n'
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_granted_call_counts_toward_child_quota(self):
        source = (
            "def spin(n):\n"
            "    i = 0\n"
            "    while i < n:\n"
            "        i = i + 1\n"
            "    return i\n"
            'sub = VM("print(spin(100000))\\n", '
            'functions={"spin": spin}, max_instructions=200)\n'
            "sub.run()\n"
        )
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_granted_sericite_function_step_debuggable(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            "def f(x):\n"
            "    return x + 1\n"
            'sub = VM("y = f(1)\\nprint(y)\\n", functions={"f": f})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(vm.run(), "2\n\n")


if __name__ == "__main__":
    unittest.main()
