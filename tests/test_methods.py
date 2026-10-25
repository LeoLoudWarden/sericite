import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits
from sericite.engine import VMHandle


def run(source, limits=None):
    engine = SericiteEngine(limits=limits)
    return engine.create_root(source).run()


def run_error(source, limits=None):
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source)
    with unittest.TestCase().assertRaises(SericiteError) as ctx:
        vm.run()
    return ctx.exception


class ListMethodTests(unittest.TestCase):
    def test_append_mutates_aliases_and_returns_none(self):
        source = "a = [1]\nb = a\nresult = b.append(2)\nprint(a, result)\n"
        self.assertEqual(run(source), "[1, 2] None\n")

    def test_pop_default_and_explicit_indices(self):
        source = "a = [1, 2, 3]\nprint(a.pop(), a.pop(0), a.pop(-1), a)\n"
        self.assertEqual(run(source), "3 1 2 []\n")

    def test_bound_methods_retain_their_receiver(self):
        source = "a = [1]\nappend = a.append\npop = a.pop\nappend(2)\nprint(pop(), a)\n"
        self.assertEqual(run(source), "2 [1]\n")

    def test_pop_empty_list_is_index_error(self):
        exc = run_error("a = []\na.pop()\n")
        self.assertEqual(exc.kind, "index_error")

    def test_pop_out_of_range_is_index_error(self):
        for index in (2, -2):
            with self.subTest(index=index):
                exc = run_error(f"a = [1]\na.pop({index})\n")
                self.assertEqual(exc.kind, "index_error")

    def test_pop_rejects_non_integer_index(self):
        exc = run_error('a = [1]\na.pop("0")\n')
        self.assertEqual(exc.kind, "type_error")

    def test_list_method_arity(self):
        sources = (
            "a = []\na.append()\n",
            "a = []\na.append(1, 2)\n",
            "a = [1]\na.pop(0, 1)\n",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(run_error(source).kind, "arity_error")

    def test_unknown_list_method_is_attribute_error(self):
        exc = run_error("a = []\na.clear()\n")
        self.assertEqual(exc.kind, "attribute_error")

    def test_append_enforces_list_size_limit(self):
        limits = SericiteLimits(max_list_size=1)
        exc = run_error("a = [1]\na.append(2)\n", limits=limits)
        self.assertEqual(exc.kind, "resource_exhausted")

    def test_append_charges_new_slot_allocation(self):
        limits = SericiteLimits(max_total_bytes=0)
        exc = run_error("a = []\na.append(1)\n", limits=limits)
        self.assertEqual(exc.kind, "resource_exhausted")


class ListPopChargeTests(unittest.TestCase):
    def test_pop_front_charges_work_proportional_to_shifted_items(self):
        counts = {}
        for size in (2, 4):
            engine = SericiteEngine()
            vm = engine.create_root(
                "items = make_list()\nitems.pop(0)\n",
                functions={"make_list": lambda size=size: list(range(size))},
            )
            vm.run()
            counts[size] = vm.snapshot()["instruction_count"]
        self.assertEqual(counts[4] - counts[2], 2)

    def test_pop_from_end_has_no_size_dependent_work(self):
        for call in ("items.pop()", "items.pop(-1)"):
            counts = []
            for size in (2, 100):
                engine = SericiteEngine()
                vm = engine.create_root(
                    f"items = make_list()\n{call}\n",
                    functions={"make_list": lambda size=size: list(range(size))},
                )
                vm.run()
                counts.append(vm.snapshot()["instruction_count"])
            self.assertEqual(counts[0], counts[1])

    def test_pop_front_enforces_instruction_limit(self):
        engine = SericiteEngine(limits=SericiteLimits(max_instructions=50))
        vm = engine.create_root(
            "items = make_list()\n"
            "i = 0\n"
            "while i < 10:\n"
            "    items.append(0)\n"
            "    items.pop(0)\n"
            "    i = i + 1\n",
            functions={"make_list": lambda: list(range(100))},
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_cross_vm_pop_front_mirrors_shift_work_to_caller(self):
        engine = SericiteEngine()
        source = (
            "items = make_list()\n"
            "bound = items.pop\n"
            "def leak():\n"
            "    return bound\n"
            'sub = VM("f = leak()\\nf(0)", functions={"leak": leak}, '
            "max_instructions=50)\n"
            "sub.run()\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root(
                source, functions={"make_list": lambda: list(range(100))}
            ).run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(engine._contexts[1].state, "resource_exhausted")


class DictMethodTests(unittest.TestCase):
    def test_keys_and_values_preserve_insertion_order(self):
        source = 'd = {"b": 2, "a": 1}\nprint(d.keys())\nprint(d.values())\n'
        self.assertEqual(run(source), "['b', 'a']\n[2, 1]\n")

    def test_keys_and_values_return_independent_lists(self):
        source = (
            'd = {"a": 1}\n'
            "names = d.keys()\n"
            "values = d.values()\n"
            'd["b"] = 2\n'
            'd["a"] = 9\n'
            "print(names, values)\n"
            "print(d.keys(), d.values())\n"
        )
        self.assertEqual(run(source), "['a'] [1]\n['a', 'b'] [9, 2]\n")

    def test_get_present_missing_and_default(self):
        source = (
            'd = {"a": 1, "none": None}\n'
            'print(d.get("a"), d.get("none"), d.get("x"), d.get("x", 9))\n'
        )
        self.assertEqual(run(source), "1 None None 9\n")

    def test_pop_present_and_missing_with_default(self):
        source = (
            'd = {"a": 1}\n'
            'print(d.pop("a"), d.pop("x", 9), d)\n'
            'print(d.pop("x", None))\n'
        )
        self.assertEqual(run(source), "1 9 {}\nNone\n")

    def test_pop_missing_without_default_is_key_error(self):
        exc = run_error("d = {}\nd.pop('x')\n")
        self.assertEqual(exc.kind, "key_error")

    def test_get_and_pop_reject_unhashable_keys(self):
        for method in ("get", "pop"):
            with self.subTest(method=method):
                exc = run_error(f"d = {{}}\nd.{method}([])\n")
                self.assertEqual(exc.kind, "type_error")

    def test_dict_method_arity(self):
        sources = (
            "d = {}\nd.keys(1)\n",
            "d = {}\nd.values(1)\n",
            "d = {}\nd.get()\n",
            "d = {}\nd.get(1, 2, 3)\n",
            "d = {}\nd.pop()\n",
            "d = {}\nd.pop(1, 2, 3)\n",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(run_error(source).kind, "arity_error")

    def test_method_names_do_not_shadow_dict_keys(self):
        source = (
            'd = {"keys": 1, "values": 2, "get": 3, "pop": 4}\n'
            'print(d["keys"], d["values"], d["get"], d["pop"])\n'
            "print(d.keys())\n"
        )
        self.assertEqual(run(source), "1 2 3 4\n['keys', 'values', 'get', 'pop']\n")

    def test_unknown_dict_method_is_attribute_error(self):
        exc = run_error("d = {}\nd.clear()\n")
        self.assertEqual(exc.kind, "attribute_error")

    def test_snapshots_enforce_list_size_limit(self):
        limits = SericiteLimits(max_list_size=1)
        for method in ("keys", "values"):
            with self.subTest(method=method):
                exc = run_error(f"d = {{1: 2, 3: 4}}\nd.{method}()\n", limits)
                self.assertEqual(exc.kind, "resource_exhausted")

    def test_snapshots_charge_list_allocation(self):
        limits = SericiteLimits(max_total_bytes=16)
        for method in ("keys", "values"):
            with self.subTest(method=method):
                exc = run_error(f"d = {{1: 2}}\nd.{method}()\n", limits)
                self.assertEqual(exc.kind, "resource_exhausted")

    def test_snapshots_charge_work_proportional_to_dict_size(self):
        counts = {}
        for method in ("keys", "values"):
            for size in (2, 4):
                vm = SericiteEngine().create_root(
                    f"d = make_dict()\nx = d.{method}()\n",
                    functions={
                        "make_dict": lambda size=size: {i: i for i in range(size)}
                    },
                )
                vm.run()
                counts[method, size] = vm.snapshot()["instruction_count"]
            self.assertEqual(counts[method, 4] - counts[method, 2], 2)


class VMHandleMethodChargeTests(unittest.TestCase):
    def test_read_file_charges_result_allocation(self):
        engine = SericiteEngine()
        checkpoints = []
        text = "x" * 1000
        source = (
            'sub = VM("")\n'
            "text = get_text()\n"
            'sub.write_file("/a.txt", text)\n'
            "checkpoint()\n"
            'sub.read_file("/a.txt")\n'
            "checkpoint()\n"
        )
        engine.create_root(
            source,
            functions={
                "get_text": lambda: text,
                "checkpoint": lambda: checkpoints.append(
                    engine._contexts[0].alloc_bytes
                ),
            },
        ).run()
        self.assertGreaterEqual(checkpoints[1] - checkpoints[0], len(text) * 4)

    def test_input_methods_charge_string_arguments(self):
        calls = (
            'sub.write_file("/a.txt", text)',
            'sub.write_file(path="/a.txt", text=text)',
            "sub.feed_input(text)",
            "sub.feed_input(value=text)",
            "sub.run([text])",
        )
        for call in calls:
            with self.subTest(call=call):
                engine = SericiteEngine()
                checkpoints = []
                text = "x" * 1000
                source = (
                    'sub = VM("")\n'
                    "text = get_text()\n"
                    "checkpoint()\n"
                    f"{call}\n"
                    "checkpoint()\n"
                )
                engine.create_root(
                    source,
                    functions={
                        "get_text": lambda text=text: text,
                        "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                            checkpoints.append(engine._contexts[0].alloc_bytes)
                        ),
                    },
                ).run()
                self.assertGreaterEqual(checkpoints[1] - checkpoints[0], len(text) * 4)

    def test_cross_vm_read_file_mirrors_result_allocation_to_caller(self):
        engine = SericiteEngine()
        text = "x" * 10_000
        source = (
            'sub = VM("")\n'
            "text = get_text()\n"
            'sub.write_file("/a.txt", text)\n'
            "bound = sub.read_file\n"
            "def leak():\n"
            "    return bound\n"
            'grand = VM("f = leak()\\ns = f(\'/a.txt\')", functions={"leak": leak})\n'
            "grand.run()\n"
        )
        engine.create_root(source, functions={"get_text": lambda: text}).run()
        self.assertGreaterEqual(engine._contexts[2].alloc_bytes, len(text) * 4)

    def test_cross_vm_step_mirrors_target_work_to_caller(self):
        engine = SericiteEngine()
        target_source = "value = 0" + " + 1" * 100
        source = (
            f"sub = VM({target_source!r})\n"
            "bound = sub.step\n"
            "def leak():\n"
            "    return bound\n"
            'grand = VM("f = leak()\\nf()", functions={"leak": leak})\n'
            "grand.run()\n"
        )
        engine.create_root(source).run()
        target = engine._contexts[1]
        caller = engine._contexts[2]
        self.assertGreater(target.instruction_count, 100)
        self.assertGreater(caller.instruction_count, target.instruction_count)

    def test_cross_vm_step_enforces_caller_instruction_limit(self):
        engine = SericiteEngine()
        target_source = "value = 0" + " + 1" * 100
        source = (
            f"sub = VM({target_source!r})\n"
            "bound = sub.step\n"
            "def leak():\n"
            "    return bound\n"
            'grand = VM("f = leak()\\nf()", functions={"leak": leak}, '
            "max_instructions=50)\n"
            "grand.run()\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root(source).run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(engine._contexts[2].state, "resource_exhausted")


class NativeCallExceptionMirrorTests(unittest.TestCase):
    def test_failed_vm_run_mirrors_target_work_before_exception(self):
        engine = SericiteEngine()
        target_source = (
            'i = 0\nwhile i < 200:\n    value = i + 1\n    i = i + 1\nraise "boom"\n'
        )
        attacker_source = "f = leak()\ntry:\n    f()\nexcept raise_error:\n    pass\n"
        source = (
            f"target = VM({target_source!r})\n"
            "bound = target.run\n"
            "def leak():\n"
            "    return bound\n"
            f"attacker = VM({attacker_source!r}, functions={{'leak': leak}}, "
            "max_instructions=300)\n"
            "attacker.run()\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root(source).run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertGreater(engine._contexts[1].instruction_count, 300)
        self.assertEqual(engine._contexts[2].state, "resource_exhausted")

    def test_failed_child_compilation_mirrors_work_before_exception(self):
        cases = (
            ("syntax_error", "x = (" * 1000),
            ("validation_error", "x = __class__\n" * 1000),
        )
        for kind, bad_source in cases:
            with self.subTest(kind=kind):
                engine = SericiteEngine()
                attacker_source = (
                    f"bad = get_bad()\ntry:\n    spawn(bad)\nexcept {kind}:\n    pass\n"
                )
                source = (
                    "def spawn(s):\n"
                    "    return VM(s)\n"
                    f"attacker = VM({attacker_source!r}, "
                    "functions={'spawn': spawn, 'get_bad': get_bad}, "
                    "max_instructions=100)\n"
                    "attacker.run()\n"
                )
                with self.assertRaises(SericiteError) as ctx:
                    engine.create_root(
                        source,
                        functions={"get_bad": lambda bad_source=bad_source: bad_source},
                    ).run()
                self.assertEqual(ctx.exception.kind, "resource_exhausted")
                self.assertEqual(engine._contexts[1].state, "resource_exhausted")

    def test_failed_input_methods_mirror_precharged_allocation(self):
        cases = (
            ("write_file", "b(None, s)", "type_error"),
            ("feed_input", "b(s, s)", "type_error"),
            ("run", "b([s, None])", "runtime_error"),
        )
        for method, call, error_kind in cases:
            with self.subTest(method=method):
                engine = SericiteEngine()
                text = "x" * 1000
                attacker_source = (
                    "b = leak()\n"
                    "s = text_fn()\n"
                    "try:\n"
                    f"    {call}\n"
                    f"except {error_kind}:\n"
                    "    pass\n"
                )
                source = (
                    "target = VM('')\n"
                    "text = get_text()\n"
                    f"bound = target.{method}\n"
                    "def leak():\n"
                    "    return bound\n"
                    "def text_fn():\n"
                    "    return text\n"
                    f"attacker = VM({attacker_source!r}, "
                    "functions={'leak': leak, 'text_fn': text_fn}, "
                    "max_total_bytes=3000)\n"
                    "attacker.run()\n"
                )
                with self.assertRaises(SericiteError) as ctx:
                    engine.create_root(
                        source, functions={"get_text": lambda text=text: text}
                    ).run()
                self.assertEqual(ctx.exception.kind, "resource_exhausted")
                attacker = engine._contexts[2]
                self.assertGreaterEqual(attacker.alloc_bytes, len(text) * 4)
                self.assertEqual(attacker.state, "resource_exhausted")

    def test_input_required_still_pauses_and_resumes_caller(self):
        engine = SericiteEngine()
        source = (
            "def read():\n"
            "    return input()\n"
            'attacker = VM("value = read()\\nprint(value)", '
            "functions={'read': read})\n"
            "attacker.run()\n"
        )
        root = engine.create_root(source)
        root.run()
        attacker = VMHandle(engine, 1)
        self.assertEqual(attacker.snapshot()["state"], "waiting_input")
        root.feed_input("ok")
        attacker.feed_input("")
        self.assertEqual(attacker.run(), "ok\n")
        self.assertEqual(attacker.snapshot()["state"], "done")


class EscapedBoundMethodTests(unittest.TestCase):
    def test_cross_vm_bound_method_mirrors_allocation_to_caller(self):
        # A bound method created in the parent scope escapes into a child via a
        # granted function. Its resource cost still belongs to the defining VM,
        # but must also be mirrored into the caller's quota (security.md §3.6),
        # so a tight-quota child cannot borrow the parent's world to run past its
        # own budget.
        engine = SericiteEngine()
        source = (
            "lst = []\n"
            "bound_append = lst.append\n"
            "def leak():\n"
            "    return bound_append\n"
            'sub = VM("""\n'
            "f = leak()\n"
            "i = 0\n"
            "while i < 100:\n"
            "    f(0)\n"
            "    i = i + 1\n"
            '""", functions={"leak": leak}, max_total_bytes=100)\n'
            "sub.run()\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root(source).run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        child = engine._contexts[1]
        self.assertEqual(child.state, "resource_exhausted")
        self.assertGreater(child.alloc_bytes, 0)

    def test_cross_vm_dict_keys_mirrors_work_and_allocation_to_caller(self):
        # An escaped dict.keys() snapshot charges O(len(dict)) work and allocation
        # to the defining VM; the causal mirror must charge the same to the child
        # caller rather than letting the child pay only its own ~1 instruction.
        engine = SericiteEngine()
        source = (
            "d = {}\n"
            "i = 0\n"
            "while i < 500:\n"
            "    d[i] = i\n"
            "    i = i + 1\n"
            "bound_keys = d.keys\n"
            "def leak():\n"
            "    return bound_keys\n"
            'sub = VM("f = leak()\\nr = f()\\nprint(len(r))", functions={"leak": leak})\n'
            "sub.run()\n"
        )
        engine.create_root(source).run()
        child = engine._contexts[1]
        self.assertEqual(child.alloc_bytes, 4000)  # 500 keys * 8 bytes, mirrored
        self.assertGreater(child.instruction_count, 500)  # 500 units of snapshot work

    def test_cross_vm_vm_method_mirrors_result_allocation_to_caller(self):
        # A VM-handle bound method (sub.stdout) created in the parent scope escapes
        # into a grandchild via a granted function. Its result-size allocation is
        # charged to the defining VM and must be mirrored into the caller's quota.
        engine = SericiteEngine()
        source = (
            "sub = VM(\"print('hello world')\")\n"
            "sub.run()\n"
            "bound = sub.stdout\n"
            "def leak():\n"
            "    return bound\n"
            'grand = VM("f = leak()\\ns = f()\\nprint(len(s))", functions={"leak": leak})\n'
            "grand.run()\n"
        )
        engine.create_root(source).run()
        grandchild = engine._contexts[2]
        self.assertGreater(grandchild.alloc_bytes, 0)  # stdout result size, mirrored


if __name__ == "__main__":
    unittest.main()
