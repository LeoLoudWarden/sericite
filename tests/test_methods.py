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
            checkpoints = []
            engine.create_root(
                f"items = {list(range(size))!r}\n"
                "checkpoint()\nitems.pop(0)\ncheckpoint()\n",
                functions={
                    "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                        checkpoints.append(engine._contexts[0].instruction_count)
                    )
                },
            ).run()
            counts[size] = checkpoints[1] - checkpoints[0]
        self.assertEqual(counts[4] - counts[2], 2)

    def test_pop_from_end_has_no_size_dependent_work(self):
        for call in ("items.pop()", "items.pop(-1)"):
            counts = []
            for size in (2, 100):
                engine = SericiteEngine()
                checkpoints = []
                engine.create_root(
                    f"items = {list(range(size))!r}\n"
                    f"checkpoint()\n{call}\ncheckpoint()\n",
                    functions={
                        "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                            checkpoints.append(engine._contexts[0].instruction_count)
                        )
                    },
                ).run()
                counts.append(checkpoints[1] - checkpoints[0])
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

    def test_cross_vm_pop_front_charges_shift_work_to_caller(self):
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
                data = {i: i for i in range(size)}
                engine = SericiteEngine()
                checkpoints = []
                engine.create_root(
                    f"d = {data!r}\ncheckpoint()\nx = d.{method}()\ncheckpoint()\n",
                    functions={
                        "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                            checkpoints.append(engine._contexts[0].instruction_count)
                        )
                    },
                ).run()
                counts[method, size] = checkpoints[1] - checkpoints[0]
            self.assertEqual(counts[method, 4] - counts[method, 2], 2)


class DictKeyChargeTests(unittest.TestCase):
    def run_key_probe(self, size: int, setup: str, body: str) -> int:
        limits = SericiteLimits(max_instructions=10_000_000)
        engine = SericiteEngine(limits=limits)
        keys = ["x" * size for _ in range(8)]
        checkpoints = []
        engine.create_root(
            setup + "checkpoint()\n"
            "i = 0\n"
            "while i < 8:\n"
            "    key = fresh()\n"
            f"{body}\n"
            "    i = i + 1\n"
            "checkpoint()\n",
            functions={
                "initial": lambda size=size: "x" * size,
                "fresh": keys.pop,
                "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                    checkpoints.append(engine._contexts[0].instruction_count)
                ),
            },
        ).run()
        return checkpoints[1] - checkpoints[0]

    def test_index_read_charges_fresh_string_key_length(self):
        counts = {}
        for size in (1000, 100_000):
            counts[size] = self.run_key_probe(
                size, "mapping = {initial(): 1}\n", "    result = mapping[key]"
            )
        self.assertGreaterEqual(counts[100_000] - counts[1000], 8 * 90_000)

    def test_index_write_charges_fresh_string_key_length(self):
        counts = {}
        for size in (1000, 100_000):
            counts[size] = self.run_key_probe(
                size, "mapping = {}\n", "    mapping[key] = 1"
            )
        self.assertGreaterEqual(counts[100_000] - counts[1000], 8 * 90_000)

    def test_dict_literal_charges_fresh_string_key_length(self):
        counts = {}
        for size in (1000, 100_000):
            counts[size] = self.run_key_probe(size, "", "    mapping = {key: 1}")
        self.assertGreaterEqual(counts[100_000] - counts[1000], 8 * 90_000)


class StringMethodTests(unittest.TestCase):
    def test_strip_variants_with_whitespace_and_chars(self):
        source = (
            'text = "  alpha beta  "\n'
            "print(text.strip())\nprint(text.lstrip())\nprint(text.rstrip())\n"
            'print("abba".strip("ab"), "abba".lstrip("ab"), "abba".rstrip("ab"))\n'
            'print("abc".strip(""), "abc".strip("xyz"))\n'
        )
        self.assertEqual(
            run(source),
            "alpha beta\nalpha beta  \n  alpha beta\n  \nabc abc\n",
        )

    def test_split_with_separator_and_whitespace(self):
        source = (
            'print("a,b,,c".split(","))\n'
            'print("  a  b  ".split())\n'
            'print("  a  b  ".split(None, 1))\n'
            'print("  a  ".split(None, 0))\n'
            'print("".split(), "   ".split(), "".split(","))\n'
        )
        self.assertEqual(
            run(source),
            "['a', 'b', '', 'c']\n['a', 'b']\n['a', 'b  ']\n['a  ']\n[] [] ['']\n",
        )

    def test_split_respects_maxsplit(self):
        source = (
            'print("a,b,c".split(",", 0))\n'
            'print("a,b,c".split(",", 1))\n'
            'print("a,b,c".split(",", -1))\n'
        )
        self.assertEqual(run(source), "['a,b,c']\n['a', 'b,c']\n['a', 'b', 'c']\n")

    def test_splitlines_boundaries_and_keepends(self):
        source = (
            'text = "a\\nb\\r\\nc\\vd\\fe\\x1cf\\x1dg\\x1eh\\x85i\\u2028j\\u2029k"\n'
            "print(text.splitlines())\n"
            'print("a\\nb\\r\\nc".splitlines(True))\n'
            'print("".splitlines(), "\\n".splitlines())\n'
        )
        self.assertEqual(
            run(source),
            "['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k']\n"
            "['a\\n', 'b\\r\\n', 'c']\n[] ['']\n",
        )

    def test_join_with_list_dict_and_string(self):
        source = (
            'print("-".join(["a", "b", "c"]))\n'
            'print(",".join({"a": 1, "b": 2}))\n'
            'print("-".join("abc"))\n'
            'print("x".join([]), "x".join(["only"]))\n'
        )
        self.assertEqual(run(source), "a-b-c\na,b\na-b-c\n only\n")

    def test_find_with_bounds_and_empty_needle(self):
        source = (
            'text = "abcabc"\n'
            'print(text.find("bc"), text.find("x"), text.find("bc", 2))\n'
            'print(text.find("bc", 0, 2), text.find("", 100), text.find("", -100))\n'
        )
        self.assertEqual(run(source), "1 -1 4\n-1 -1 0\n")

    def test_replace_with_count_and_empty_old(self):
        source = (
            'print("aaa".replace("a", "xy"))\n'
            'print("aaa".replace("a", "xy", 2))\n'
            'print("ab".replace("", "-"), "ab".replace("", "-", 2))\n'
            'print("abc".replace("x", "y"), "abc".replace("a", "x", 0))\n'
        )
        self.assertEqual(run(source), "xyxyxy\nxyxya\n-a-b- -a-b\nabc abc\n")

    def test_replace_accepts_counts_beyond_ssize_t(self):
        source = (
            'print("aaa".replace("a", "b", 9223372036854775808))\n'
            'print("aaa".replace("a", "b", -9223372036854775809))\n'
            'print("ab".replace("", "-", 9223372036854775808))\n'
        )
        self.assertEqual(run(source), "bbb\nbbb\n-a-b-\n")

    def test_bound_string_methods_retain_receiver(self):
        source = (
            'strip = "  a  ".strip\njoin = ",".join\nprint(strip(), join(["a", "b"]))\n'
        )
        self.assertEqual(run(source), "a a,b\n")

    def test_string_method_arity(self):
        sources = (
            '"a".strip(1, 2)',
            '"a".lstrip(1, 2)',
            '"a".rstrip(1, 2)',
            '"a".split(",", 1, 2)',
            '"a".splitlines(True, False)',
            '"a".join()',
            '"a".join([], [])',
            '"a".find()',
            '"a".find("a", 0, 1, 2)',
            '"a".replace("a")',
            '"a".replace("a", "b", 1, 2)',
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(run_error(source + "\n").kind, "arity_error")

    def test_string_method_argument_types(self):
        sources = (
            '"a".strip(1)',
            '"a".split(1)',
            '"a".split("")',
            '"a".split(None, True)',
            '"a".splitlines(1)',
            '"a".join(1)',
            '"a".join(["a", 1])',
            '"a".find(1)',
            '"a".find("a", False)',
            '"a".replace(1, "x")',
            '"a".replace("a", 1)',
            '"a".replace("a", "b", False)',
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(run_error(source + "\n").kind, "type_error")

    def test_unknown_string_method_is_attribute_error(self):
        self.assertEqual(run_error('"a".upper()\n').kind, "attribute_error")


class StringMethodChargeTests(unittest.TestCase):
    def allocation_delta(self, expression):
        engine = SericiteEngine()
        checkpoints = []
        engine.create_root(
            f"checkpoint()\nresult = {expression}\ncheckpoint()\n",
            functions={
                "checkpoint": lambda: checkpoints.append(
                    engine._contexts[0].alloc_bytes
                )
            },
        ).run()
        checkpoint_result_allocation = 8
        return checkpoints[1] - checkpoints[0] - checkpoint_result_allocation

    def test_result_allocations(self):
        cases = (
            ("'  a  '.strip()", 4),
            ("'a,b'.split(',')", 2 * 8 + 2 * 4),
            ("'a\\nb'.splitlines()", 2 * 8 + 2 * 4),
            ("'--'.join('ab')", 4 * 4),
            ("'aaa'.replace('a', 'xy', 2)", 5 * 4),
            ("'abc'.find('b')", 0),
        )
        for expression, expected in cases:
            with self.subTest(expression=expression):
                self.assertEqual(self.allocation_delta(expression), expected)

    def instruction_delta(self, expression, size):
        engine = SericiteEngine()
        checkpoints = []
        value = [""] * size if "join" in expression else None
        if expression == "value.strip()":
            value = " " * size
        elif value is None:
            value = "a" * size
        engine.create_root(
            f"value = get()\ncheckpoint()\nresult = {expression}\ncheckpoint()\n",
            functions={
                "get": lambda: value,
                "checkpoint": lambda: checkpoints.append(
                    engine._contexts[0].instruction_count
                ),
            },
        ).run()
        return checkpoints[1] - checkpoints[0]

    def test_scanning_work_scales_with_input_size(self):
        expressions = (
            "value.strip()",
            "value.split(',')",
            "value.split()",
            "value.splitlines()",
            "value.find('x')",
            "value.replace('x', 'y')",
            "''.join(value)",
        )
        for expression in expressions:
            counts = {
                size: self.instruction_delta(expression, size) for size in (100, 1000)
            }
            with self.subTest(expression=expression):
                self.assertGreater(counts[1000] - counts[100], 500)

    def test_custom_strip_chars_charge_membership_scan(self):
        counts = {}
        for size in (100, 1000):
            engine = SericiteEngine()
            checkpoints = []
            chars = "a" * (size - 1) + "b"
            engine.create_root(
                'value = "b"\nchars = get()\ncheckpoint()\n'
                "result = value.strip(chars)\ncheckpoint()\n",
                functions={
                    "get": lambda chars=chars: chars,
                    "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                        checkpoints.append(engine._contexts[0].instruction_count)
                    ),
                },
            ).run()
            counts[size] = checkpoints[1] - checkpoints[0]
        self.assertGreaterEqual(counts[1000] - counts[100], 900)

    def test_split_enforces_result_list_limit(self):
        for call in ('"a,b".split(",")', '"a\\nb".splitlines()'):
            with self.subTest(call=call):
                exc = run_error(f"result = {call}\n", SericiteLimits(max_list_size=1))
                self.assertEqual(exc.kind, "resource_exhausted")

    def test_join_and_replace_enforce_result_string_limit(self):
        for call in ('"-".join(["ab", "cd"])', '"aa".replace("a", "xyz")'):
            with self.subTest(call=call):
                exc = run_error(
                    f"result = {call}\n", SericiteLimits(max_string_bytes=4)
                )
                self.assertEqual(exc.kind, "resource_exhausted")

    def test_find_enforces_instruction_limit(self):
        text = "a" * 10_000
        exc = run_error(
            f"value = {text!r}\nresult = value.find('x')\n",
            SericiteLimits(max_instructions=100),
        )
        self.assertEqual(exc.kind, "resource_exhausted")

    def test_cross_vm_bound_replace_charges_caller(self):
        engine = SericiteEngine()
        source = (
            "text = get_text()\n"
            "bound = text.replace\n"
            "def leak():\n"
            "    return bound\n"
            "sub = VM(\"f = leak()\\nresult = f('a', 'b')\", "
            "functions={'leak': leak}, max_instructions=100)\n"
            "sub.run()\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root(
                source, functions={"get_text": lambda: "a" * 10_000}
            ).run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(engine._contexts[1].state, "resource_exhausted")


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
                "checkpoint": lambda engine=engine, checkpoints=checkpoints: (
                    checkpoints.append(engine._contexts[0].alloc_bytes)
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

    def test_run_empty_inputs_charge_work_and_queue_slots_on_done_vm(self):
        engine = SericiteEngine()
        checkpoints = []
        vm = engine.create_root(
            'sub = VM("")\nvalues = inputs()\ncheckpoint()\n'
            "sub.run(values)\ncheckpoint()\n",
            functions={
                "inputs": lambda: [""] * 1000,
                "checkpoint": lambda: checkpoints.append(
                    (
                        engine._contexts[0].instruction_count,
                        engine._contexts[0].alloc_bytes,
                    )
                ),
            },
        )
        vm.run()
        target = engine._contexts[1]
        self.assertEqual(target.state, "done")
        self.assertEqual(target.io.buffered_input_count, 1000)
        self.assertGreaterEqual(checkpoints[1][0] - checkpoints[0][0], 1000)
        self.assertGreaterEqual(checkpoints[1][1] - checkpoints[0][1], 8000)

    def test_run_inputs_rejects_partial_invalid_batch_atomically(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'sub = VM("")\n'
            "try:\n"
            "    sub.run(inputs())\n"
            "except runtime_error:\n"
            "    pass\n",
            functions={"inputs": lambda: ["accepted", None]},
        )
        vm.run()
        self.assertEqual(engine._contexts[1].io.buffered_input_count, 0)

    def test_run_empty_inputs_enforce_memory_quota_before_queue_mutation(self):
        engine = SericiteEngine(SericiteLimits(max_total_bytes=1000))
        vm = engine.create_root(
            'sub = VM("")\nsub.run(inputs())\n',
            functions={"inputs": lambda: [""] * 100},
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(engine._contexts[1].io.buffered_input_count, 0)

    def test_run_empty_inputs_enforce_instruction_quota_before_queue_mutation(self):
        engine = SericiteEngine(SericiteLimits(max_instructions=150))
        vm = engine.create_root(
            'sub = VM("")\nsub.run(inputs())\n',
            functions={"inputs": lambda: [""] * 100},
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(engine._contexts[1].io.buffered_input_count, 0)

    def test_cross_vm_read_file_charges_result_allocation_to_caller(self):
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

    def test_cross_vm_step_charges_target_work_to_caller(self):
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


class VfsChargeTests(unittest.TestCase):
    def test_directory_index_tracks_nested_files(self):
        engine = SericiteEngine()
        engine.create_root(
            'write_file("/a/b/file.txt", "x")\nwrite_file("/a/other.txt", "y")\n'
        ).run()
        fs = engine._contexts[0].fs
        self.assertEqual(fs.list_dir("/"), ["a"])
        self.assertEqual(fs.list_dir("/a"), ["b", "other.txt"])
        self.assertEqual(fs.list_dir("/a/b"), ["file.txt"])

    def test_deep_path_allocation_covers_each_new_directory(self):
        engine = SericiteEngine()
        engine.create_root("")
        fs = engine._contexts[0].fs
        depth = 100
        path = "/" + "/".join(["a"] * depth) + "/file.txt"
        base = 64 + len(path) * 4
        self.assertGreaterEqual(fs.write_allocation(path, ""), base + depth * 64)

    def test_list_dir_charges_sort_work_and_result_allocation(self):
        counts = {}
        for size in (100, 1000):
            limits = SericiteLimits(max_fs_files=2000)
            engine = SericiteEngine(limits)
            checkpoints = []
            vm = engine.create_root(
                "checkpoint()\nresult = list_dir('/')\ncheckpoint()\n",
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
            fs = engine._contexts[0].fs
            for index in range(size):
                fs.write_file_trusted(f"/f{index}.txt", "")
            vm.run()
            counts[size] = (
                checkpoints[1][0] - checkpoints[0][0],
                checkpoints[1][1] - checkpoints[0][1],
            )
        self.assertGreater(counts[1000][0] - counts[100][0], 900)
        self.assertGreaterEqual(counts[100][1], 100 * 8)
        self.assertGreaterEqual(counts[1000][1], 1000 * 8)

    def test_list_dir_enforces_instruction_quota_before_enumeration(self):
        limits = SericiteLimits(max_instructions=100, max_fs_files=2000)
        engine = SericiteEngine(limits)
        vm = engine.create_root("result = list_dir('/')\n")
        fs = engine._contexts[0].fs
        for index in range(1000):
            fs.write_file_trusted(f"/f{index}.txt", "")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_list_dir_enforces_result_memory_quota(self):
        limits = SericiteLimits(max_total_bytes=400, max_fs_files=200)
        engine = SericiteEngine(limits)
        vm = engine.create_root("result = list_dir('/')\n")
        fs = engine._contexts[0].fs
        for index in range(100):
            fs.write_file_trusted(f"/f{index}.txt", "")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_cross_vm_list_dir_charges_work_to_caller(self):
        source = (
            'target = VM("")\n'
            "i = 0\n"
            "while i < 1000:\n"
            '    target.write_file("/f" + str(i), "")\n'
            "    i = i + 1\n"
            "bound = target.list_dir\n"
            "def leak():\n"
            "    return bound\n"
            "attacker = VM(\"f = leak()\\nresult = f('/')\", "
            "functions={'leak': leak}, max_instructions=100)\n"
            "attacker.run()\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            SericiteEngine().create_root(source).run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")


class CrossVmResultEstimationTests(unittest.TestCase):
    @staticmethod
    def make_engine(**kwargs: object) -> SericiteEngine:
        defaults = {
            "max_instructions": 10_000_000,
            "max_total_bytes": 100_000_000,
            "max_fs_files": 30_000,
        }
        return SericiteEngine(SericiteLimits(**(defaults | kwargs)))

    @staticmethod
    def populate(engine: SericiteEngine, vm: VMHandle, count: int) -> None:
        vm.step()  # create the child VM
        fs = engine._contexts[1].fs
        for index in range(count):
            fs.write_file_trusted(f"/{index:06d}", "")

    def test_result_beyond_former_node_cap_is_fully_charged(self):
        engine = self.make_engine()
        checkpoints = []
        vm = engine.create_root(
            "target = VM('')\n"
            "checkpoint()\n"
            "result = target.list_dir('/')\n"
            "checkpoint()\n",
            functions={
                "checkpoint": lambda: checkpoints.append(
                    (
                        engine._contexts[0].instruction_count,
                        engine._contexts[0].alloc_bytes,
                    )
                )
            },
        )
        self.populate(engine, vm, 20_000)
        vm.run()
        work, allocation = (
            checkpoints[1][0] - checkpoints[0][0],
            checkpoints[1][1] - checkpoints[0][1],
        )
        self.assertGreaterEqual(work, 20_001)
        self.assertGreaterEqual(allocation, 20_000 * 8 + 20_000 * 6 * 4)

    def test_result_that_exceeds_memory_quota_is_not_delivered(self):
        engine = self.make_engine(max_total_bytes=400_000)
        delivered = []
        vm = engine.create_root(
            "target = VM('')\nresult = target.list_dir('/')\ndelivered()\n",
            functions={"delivered": lambda: delivered.append(True)},
        )
        self.populate(engine, vm, 20_000)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(delivered, [])


class NativeCallExceptionRouteTests(unittest.TestCase):
    def test_failed_vm_run_charges_target_work_before_exception(self):
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
        self.assertGreater(engine._contexts[1].instruction_count, 250)
        self.assertLessEqual(engine._contexts[1].instruction_count, 300)
        self.assertEqual(engine._contexts[2].state, "resource_exhausted")

    def test_failed_child_compilation_charges_work_before_exception(self):
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

    def test_failed_input_methods_do_not_commit_rejected_reservation(self):
        cases = (
            ("write_file", "b(None, s)", "type_error", 0),
            ("feed_input", "b(s, s)", "type_error", 0),
            ("run", "b([s, None])", "runtime_error", 16),
        )
        for method, call, error_kind, baseline_allocation in cases:
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
                self.assertEqual(attacker.alloc_bytes, baseline_allocation)
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
    def test_cross_vm_bound_method_charges_allocation_to_caller(self):
        # A bound method created in the parent scope escapes into a child via a
        # granted function. Its resource cost still belongs to the defining VM,
        # but must also enter the caller's causal route (security.md §3.6),
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

    def test_cross_vm_dict_keys_charges_work_and_allocation_to_caller(self):
        # An escaped dict.keys() snapshot charges O(len(dict)) work and allocation
        # to the defining VM; the causal route must charge the same to the child
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
        self.assertEqual(child.alloc_bytes, 4000)  # 500 keys * 8 bytes, charged
        self.assertGreater(child.instruction_count, 500)  # 500 units of snapshot work

    def test_cross_vm_vm_method_charges_result_allocation_to_caller(self):
        # A VM-handle bound method (sub.stdout) created in the parent scope escapes
        # into a grandchild via a granted function. Its result-size allocation is
        # charged to the defining VM and must be charged into the caller's quota.
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
        self.assertGreater(grandchild.alloc_bytes, 0)  # stdout result size, charged


if __name__ == "__main__":
    unittest.main()
