import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


def run(source, inputs=None, limits=None, addons=None):
    if addons:
        source = f"from __addon__ import {', '.join(addons)}\n{source}"
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source, addons=addons)
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
            '    print("caught: " + e.message)\n'
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
            run("print(add(2, 3))\n", addons={"add": lambda a, b: a + b}),
            "5\n",
        )

    def test_structured_dict_result(self):
        def http_get(url):
            return {"status": 200, "body": "hello " + url, "tags": ["x", "y"]}

        source = (
            'r = http_get("example.com")\nprint(r["status"], r["body"], r["tags"][1])\n'
        )
        self.assertEqual(
            run(source, addons={"http_get": http_get}),
            "200 hello example.com y\n",
        )

    def test_result_is_deep_copied(self):
        shared = {"items": [1, 2]}

        def give():
            return shared

        source = 'a = give()\na["items"][0] = 99\nb = give()\nprint(b["items"][0])\n'
        self.assertEqual(run(source, addons={"give": give}), "1\n")
        self.assertEqual(shared, {"items": [1, 2]})

    def test_argument_is_deep_copied(self):
        seen = []

        def take(value):
            seen.append(list(value))
            value[0] = -1

        source = "a = [1, 2]\ntake(a)\nprint(a[0])\n"
        self.assertEqual(run(source, addons={"take": take}), "1\n")
        self.assertEqual(seen, [[1, 2]])

    def test_handle_cannot_cross_boundary(self):
        source = (
            'sub = VM("")\n'
            "try:\n"
            "    probe(sub)\n"
            "except addon_error:\n"
            '    print("blocked")\n'
        )
        self.assertEqual(run(source, addons={"probe": lambda value: None}), "blocked\n")

    def test_alien_result_rejected(self):
        source = 'try:\n    bad()\nexcept addon_error as e:\n    print("rejected")\n'
        self.assertEqual(run(source, addons={"bad": lambda: object()}), "rejected\n")

    def test_uncontracted_host_exception_kills_vm_with_host_error(self):
        def boom():
            raise ValueError("kaput /home/secret")

        # even a bare except cannot catch host_error: the VM dies and the
        # sanitized message (type name only) reaches the host
        engine = SericiteEngine()
        vm = engine.create_root(
            "from __addon__ import boom\ntry:\n    boom()\nexcept:\n    pass\n",
            addons={"boom": boom},
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        exc = ctx.exception
        self.assertEqual(exc.kind, "host_error")
        self.assertIn("ValueError", exc.message)
        self.assertIn("boom", exc.message)
        self.assertNotIn("kaput", exc.message)
        self.assertNotIn("/home/secret", exc.message)

    def test_host_system_exit_propagates(self):
        def exits():
            raise SystemExit(42)

        engine = SericiteEngine()
        vm = engine.create_root(
            "from __addon__ import exits\nexits()\n", addons={"exits": exits}
        )
        with self.assertRaises(SystemExit):
            vm.run()

    def test_host_keyboard_interrupt_propagates(self):
        def interrupts():
            raise KeyboardInterrupt

        engine = SericiteEngine()
        vm = engine.create_root(
            "from __addon__ import interrupts\ninterrupts()\n",
            addons={"interrupts": interrupts},
        )
        with self.assertRaises(KeyboardInterrupt):
            vm.run()

    def test_host_sericite_error_passes_through(self):
        def picky(value):
            raise SericiteError("host says no", kind="file_not_found")

        source = (
            'try:\n    picky(1)\nexcept file_not_found:\n    print("precise kind")\n'
        )
        self.assertEqual(run(source, addons={"picky": picky}), "precise kind\n")

    def test_addon_name_matching_builtin_requires_import_alias(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            "from __addon__ import len as host_len\nprint(host_len([1, 2]))\n",
            addons={"len": len},
        )
        self.assertEqual(vm.run(), "2\n")
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("from __addon__ import len\n", addons={"len": len})
        self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_addon_name_must_be_identifier(self):
        engine = SericiteEngine()
        for name in ("not a name", "__hidden"):
            with self.subTest(name=name), self.assertRaises(SericiteError) as ctx:
                engine.create_root("print(1)\n", addons={name: lambda: 0})
            self.assertEqual(ctx.exception.kind, "type_error")

    def test_grant_must_be_callable(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("print(1)\n", addons={"f": 42})
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_granted_function_respects_output_quota(self):
        limits = SericiteLimits(max_output_bytes=4)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(
            'from __addon__ import shout\nprint(shout("hello world"))\n',
            addons={"shout": lambda text: text.upper()},
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")


class ChildGrantTests(unittest.TestCase):
    def test_parent_grants_sericite_function(self):
        source = (
            "def double(x):\n"
            "    return x * 2\n"
            'sub = VM("from __addon__ import double\\nprint(double(21))\\n", addons={"double": double})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "42\n\n")

    def test_addon_does_not_enter_global_namespace(self):
        source = (
            "def double(x):\n"
            "    return x * 2\n"
            'sub = VM("try:\\n'
            "    print(double(21))\\n"
            "except name_error:\\n"
            "    print('not global')\", addons={'double': double})\n"
            "print(sub.run(), end='')\n"
        )
        self.assertEqual(run(source), "not global\n")

    def test_granted_function_sees_parent_globals(self):
        source = (
            "base = 100\n"
            "def add_base(x):\n"
            "    return x + base\n"
            'sub = VM("from __addon__ import add_base\\nprint(add_base(1))\\n", addons={"add_base": add_base})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "101\n\n")

    def test_granted_function_calls_parent_helpers(self):
        source = (
            "def helper(x):\n"
            "    return x + 1\n"
            "def outer(x):\n"
            "    return helper(x) * 10\n"
            'sub = VM("from __addon__ import outer\\nprint(outer(2))\\n", addons={"outer": outer})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "30\n\n")

    def test_granted_function_keeps_definition_granted_environment(self):
        child = (
            "from __addon__ import f\n"
            "def helper():\n"
            "    return 'child'\n"
            'grandchild = VM("from __addon__ import f\\nprint(f())\\n", '
            "addons={'f': f, 'helper': helper})\n"
            "print(grandchild.run())\n"
        )
        source = (
            "def f():\n"
            "    return helper()\n"
            "sub = VM(" + repr(child) + ", addons={'f': f})\n"
            "print(sub.run())\n"
        )
        output = run(source, addons={"helper": lambda: "parent"})
        self.assertEqual(output, "parent\n\n\n")

    def test_caller_granted_name_cannot_shadow_missing_definition_name(self):
        child = (
            "from __addon__ import f\n"
            "def helper():\n"
            "    return 'child'\n"
            'grandchild = VM("from __addon__ import f\\nprint(f())\\n", '
            "addons={'f': f, 'helper': helper})\n"
            "print(grandchild.run())\n"
        )
        source = (
            "def f():\n"
            "    try:\n"
            "        return helper()\n"
            "    except name_error:\n"
            "        return 'safe'\n"
            "sub = VM(" + repr(child) + ", addons={'f': f})\n"
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "safe\n\n\n")

    def test_child_globals_not_visible_to_granted_function(self):
        child = (
            "from __addon__ import read_base\n"
            "base = 5\n"
            "try:\n"
            "    print(read_base())\n"
            "except name_error:\n"
            "    print('no base')\n"
        )
        source = (
            "def read_base():\n"
            "    return base\n"
            "sub = VM(" + repr(child) + ", addons={'read_base': read_base})\n"
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "no base\n\n")

    def test_regrant_host_function_to_child(self):
        source = (
            'sub = VM("from __addon__ import host_add\\nprint(host_add(3, 4))\\n", '
            'addons={"host_add": host_add})\n'
            "print(sub.run())\n"
        )
        output = run(source, addons={"host_add": lambda a, b: a + b})
        self.assertEqual(output, "7\n\n")

    def test_regrant_across_two_levels(self):
        grandchild = "from __addon__ import host_add\nprint(host_add(1, 2))\n"
        child = (
            "from __addon__ import host_add\n"
            f"sub = VM({grandchild!r}, addons={{'host_add': host_add}})\n"
            "print(sub.run())\n"
        )
        source = (
            f"mid = VM({child!r}, addons={{'host_add': host_add}})\nprint(mid.run())\n"
        )
        output = run(source, addons={"host_add": lambda a, b: a + b})
        self.assertEqual(output, "3\n\n\n")

    def test_addons_option_must_be_dict(self):
        source = 'sub = VM("", addons=[1, 2])\n'
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_addons_option_rejects_non_function(self):
        source = 'sub = VM("", addons={"f": 42})\n'
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_old_functions_option_is_removed(self):
        vm = SericiteEngine().create_root('sub = VM("", functions={})\n')
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
            'sub = VM("from __addon__ import spin\\nprint(spin(100000))\\n", '
            'addons={"spin": spin}, max_instructions=200)\n'
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
            'sub = VM("from __addon__ import f\\ny = f(1)\\nprint(y)\\n", addons={"f": f})\n'
            "print(sub.run())\n"
        )
        self.assertEqual(vm.run(), "2\n\n")


if __name__ == "__main__":
    unittest.main()
