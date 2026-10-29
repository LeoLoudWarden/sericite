import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


def run(source, inputs=None, limits=None):
    engine = SericiteEngine(limits=limits)
    vm = engine.create_root(source)
    return vm.run(inputs)


class TryExceptTests(unittest.TestCase):
    def test_catch_by_kind_with_message(self):
        source = (
            "try:\n"
            "    x = 1 / 0\n"
            "except zero_division as e:\n"
            '    print("caught: " + e.message)\n'
        )
        self.assertEqual(run(source), "caught: division by zero\n")

    def test_kind_filter_selects_matching_clause(self):
        source = (
            "try:\n"
            "    x = missing\n"
            "except zero_division:\n"
            '    print("wrong")\n'
            "except name_error:\n"
            '    print("right")\n'
            "except:\n"
            '    print("fallback")\n'
        )
        self.assertEqual(run(source), "right\n")

    def test_bare_except_catches_all(self):
        source = 'try:\n    x = int("abc")\nexcept:\n    print("caught")\n'
        self.assertEqual(run(source), "caught\n")

    def test_kind_group_catches_each_listed_kind(self):
        cases = (
            ("x = 1 / 0", "zero_division"),
            ("x = missing", "name_error"),
            ('x = int("bad")', "conversion_error"),
        )
        for operation, expected in cases:
            with self.subTest(expected=expected):
                source = (
                    "try:\n"
                    f"    {operation}\n"
                    "except (zero_division, name_error, conversion_error) as e:\n"
                    "    print(e.kind)\n"
                )
                self.assertEqual(run(source), expected + "\n")

    def test_wildcard_binds_fixed_error_record(self):
        source = (
            "try:\n"
            "    x = 1 / 0\n"
            "except ... as e:\n"
            "    print(unwrap(e))\n"
            "try:\n"
            '    int("bad")\n'
            "except (...) as e:\n"
            "    print(e.kind, e.message)\n"
        )
        self.assertEqual(
            run(source),
            "{'kind': 'zero_division', 'message': 'division by zero'}\n"
            "conversion_error cannot convert to int: 'bad'\n",
        )

    def test_invalid_kind_groups_rejected_at_compile_time(self):
        filters = (
            "()",
            "(name_error, zero_divsion)",
            "(name_error, resource_exhausted)",
            "(name_error, ...)",
            "(name_error, 1)",
        )
        for filter_source in filters:
            with self.subTest(filter_source=filter_source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(
                        f"try:\n    pass\nexcept {filter_source}:\n    pass\n"
                    )
                self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_group_and_wildcard_syntax_not_general_values(self):
        for source in ("value = (name_error, type_error)\n", "value = ...\n"):
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_non_matching_kind_propagates(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            "try:\n    x = missing\nexcept zero_division:\n    y = 1\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "name_error")

    def test_non_matching_kind_group_propagates(self):
        vm = SericiteEngine().create_root(
            "try:\n    x = missing\nexcept (zero_division, type_error):\n    pass\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "name_error")

    def test_unknown_except_kind_rejected_at_compile_time(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("try:\n    pass\nexcept e:\n    pass\n")
        exc = ctx.exception
        self.assertEqual(exc.kind, "syntax_error")
        self.assertIn("unknown error kind: 'e'", exc.message)
        self.assertIn("except <kind> as name", exc.message)
        self.assertIn("bare 'except:'", exc.message)
        self.assertEqual(exc.line, 3)
        self.assertEqual(exc.column, 8)

    def test_misspelled_except_kind_rejected_at_compile_time(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("try:\n    pass\nexcept zero_divsion:\n    pass\n")
        self.assertEqual(ctx.exception.kind, "syntax_error")
        self.assertIn("zero_divsion", ctx.exception.message)

    def test_all_catchable_except_kinds_are_accepted(self):
        # syntax_error stays accepted: nested-VM compilation raises it at runtime
        # when a child VM's source fails to parse or validate.
        kinds = (
            "arity_error",
            "attribute_error",
            "contract_error",
            "conversion_error",
            "ffi_error",
            "file_not_found",
            "index_error",
            "input_error",
            "is_directory",
            "key_error",
            "name_error",
            "not_directory",
            "raise_error",
            "runtime_error",
            "syntax_error",
            "type_error",
            "zero_division",
        )
        for kind in kinds:
            with self.subTest(kind=kind):
                SericiteEngine().create_root(
                    f"try:\n    pass\nexcept {kind}:\n    pass\n"
                )

    def test_uncatchable_except_kinds_rejected_at_compile_time(self):
        for kind in ("resource_exhausted", "internal_error", "host_error"):
            with self.subTest(kind=kind):
                engine = SericiteEngine()
                with self.assertRaises(SericiteError) as ctx:
                    engine.create_root(f"try:\n    pass\nexcept {kind}:\n    pass\n")
                self.assertEqual(ctx.exception.kind, "syntax_error")
                self.assertIn(kind, ctx.exception.message)

    def test_child_vm_unknown_except_kind_is_syntax_error(self):
        child = "try:\n    pass\nexcept unknown_kind:\n    pass\n"
        source = (
            "try:\n"
            f"    sub = VM({child!r})\n"
            "except syntax_error as e:\n"
            '    print("caught: " + e.message)\n'
        )
        self.assertIn("caught: unknown error kind: 'unknown_kind'", run(source))

    def test_exception_across_function_frames(self):
        source = (
            "def f():\n"
            "    return missing + 1\n"
            "try:\n"
            "    f()\n"
            "except name_error:\n"
            '    print("caught across frames")\n'
        )
        self.assertEqual(run(source), "caught across frames\n")

    def test_stack_sane_after_catch(self):
        source = (
            "caught = 0\n"
            "i = 0\n"
            "while i < 3:\n"
            "    try:\n"
            "        x = 1 / i\n"
            "    except zero_division:\n"
            "        caught = caught + 1\n"
            "    i = i + 1\n"
            "print(caught)\n"
            "print(1 + 2)\n"
        )
        self.assertEqual(run(source), "1\n3\n")

    def test_break_inside_try_in_loop(self):
        source = (
            "while True:\n"
            "    try:\n"
            "        x = 1 / 0\n"
            "    except zero_division:\n"
            "        break\n"
            'print("out")\n'
        )
        self.assertEqual(run(source), "out\n")

    def test_resource_exhausted_not_catchable_by_bare_except(self):
        limits = SericiteLimits(max_instructions=500)
        source = (
            "try:\n"
            "    while True:\n"
            "        x = 1\n"
            "except:\n"
            '    print("must not happen")\n'
        )
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertNotIn("must not happen", vm.stdout())

    def test_error_record_allocation_failure_is_terminal(self):
        engine = SericiteEngine(limits=SericiteLimits(max_total_bytes=1))
        vm = engine.create_root("try:\n    1 / 0\nexcept ... as e:\n    pass\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(vm.snapshot()["state"], "resource_exhausted")

    def test_child_vm_error_caught_by_parent(self):
        source = (
            'sub = VM("x = missing")\n'
            "try:\n"
            "    sub.run()\n"
            "except name_error as e:\n"
            '    print("parent caught: " + e.message)\n'
        )
        self.assertIn("parent caught:", run(source))

    def test_finally_runs_on_both_paths(self):
        source = (
            "try:\n"
            "    x = 1 / 0\n"
            "except zero_division:\n"
            '    print("caught")\n'
            "finally:\n"
            '    print("cleanup")\n'
            "try:\n"
            "    y = 1\n"
            "finally:\n"
            '    print("cleanup2")\n'
        )
        self.assertEqual(run(source), "caught\ncleanup\ncleanup2\n")


class KeywordCallTests(unittest.TestCase):
    def test_user_function_kwargs(self):
        source = (
            "def sub(a, b):\n"
            "    return a - b\n"
            "print(sub(b=1, a=5))\n"
            "print(sub(5, b=1))\n"
        )
        self.assertEqual(run(source), "4\n4\n")

    def test_unknown_kwarg(self):
        with self.assertRaises(SericiteError) as ctx:
            run("def f(a):\n    return a\nf(b=1)\n")
        self.assertEqual(ctx.exception.kind, "arity_error")

    def test_duplicate_argument(self):
        with self.assertRaises(SericiteError) as ctx:
            run("def f(a):\n    return a\nf(1, a=2)\n")
        self.assertEqual(ctx.exception.kind, "arity_error")


class NestedVMTests(unittest.TestCase):
    def test_vm_config_limits_child(self):
        source = (
            'sub = VM("while True:\\n    x = 1", max_instructions=100)\nsub.run()\n'
        )
        engine = SericiteEngine()
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_vm_config_clamped_to_parent(self):
        limits = SericiteLimits(max_instructions=300)
        source = (
            'sub = VM("while True:\\n    x = 1", max_instructions=999999)\nsub.run()\n'
        )
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError):
            vm.run()
        sub_handle = None
        for value in engine._contexts.values():
            if value.parent_id is not None:
                sub_handle = value
        self.assertIsNotNone(sub_handle)
        self.assertLessEqual(sub_handle.instruction_count, 301)

    def test_unknown_vm_option(self):
        with self.assertRaises(SericiteError) as ctx:
            run('sub = VM("x = 1", nope=1)\n')
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_vm_depth_limit(self):
        limits = SericiteLimits(max_vm_depth=2)
        level3 = "x = 1"
        level2 = f"sub = VM({level3!r})\nsub.run()"
        level1 = f"sub = VM({level2!r})\nsub.run()"
        source = f"sub = VM({level1!r})\nsub.run()\n"
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_ancestor_instruction_charging(self):
        child_src = "i = 0\nwhile i < 20:\n    i = i + 1\nprint(i)\n"
        engine = SericiteEngine()
        vm = engine.create_root(f"sub = VM({child_src!r})\nprint(sub.run())\n")
        vm.run()
        child = next(c for c in engine._contexts.values() if c.parent_id == 0)
        root_count = vm.snapshot()["instruction_count"]
        self.assertGreaterEqual(
            root_count,
            child.instruction_count,
            "root instruction count should include the child's consumption",
        )


class VFSTests(unittest.TestCase):
    def test_write_and_read(self):
        source = (
            'write_file("/notes/todo.txt", "buy milk")\n'
            'print(read_file("/notes/todo.txt"))\n'
        )
        self.assertEqual(run(source), "buy milk\n")

    def test_list_dir_sorted(self):
        source = (
            'write_file("/b.txt", "b")\n'
            'write_file("/a/x.txt", "x")\n'
            'write_file("/a/y.txt", "y")\n'
            'print(list_dir("/"))\n'
            'print(list_dir("/a"))\n'
        )
        self.assertEqual(run(source), "['a', 'b.txt']\n['x.txt', 'y.txt']\n")

    def test_path_exists(self):
        source = (
            'write_file("/a/b.txt", "x")\n'
            'print(path_exists("/a"))\n'
            'print(path_exists("/a/b.txt"))\n'
            'print(path_exists("/nope"))\n'
        )
        self.assertEqual(run(source), "True\nTrue\nFalse\n")

    def test_path_normalization_no_escape(self):
        source = (
            'write_file("/a/../b.txt", "x")\n'
            'print(read_file("b.txt"))\n'
            'print(path_exists("../../b.txt"))\n'
        )
        self.assertEqual(run(source), "x\nTrue\n")

    def test_read_missing_file(self):
        source = (
            "try:\n"
            '    read_file("/missing.txt")\n'
            "except file_not_found as e:\n"
            '    print("caught: " + e.message)\n'
        )
        self.assertEqual(run(source), "caught: no such file: /missing.txt\n")

    def test_directory_errors(self):
        source = (
            'write_file("/d/f.txt", "x")\n'
            "try:\n"
            '    read_file("/d")\n'
            "except is_directory:\n"
            '    print("is dir")\n'
            "try:\n"
            '    write_file("/d", "x")\n'
            "except is_directory:\n"
            '    print("is dir 2")\n'
            "try:\n"
            '    list_dir("/d/f.txt")\n'
            "except not_directory:\n"
            '    print("not dir")\n'
        )
        self.assertEqual(run(source), "is dir\nis dir 2\nnot dir\n")

    def test_file_count_limit(self):
        limits = SericiteLimits(max_fs_files=2)
        source = 'write_file("/a", "1")\nwrite_file("/b", "2")\nwrite_file("/c", "3")\n'
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_file_size_limit(self):
        limits = SericiteLimits(max_fs_file_bytes=5)
        engine = SericiteEngine(limits=limits)
        vm = engine.create_root('write_file("/a", "123456")\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_child_fs_isolated(self):
        source = (
            'write_file("/secret.txt", "parent data")\n'
            'sub = VM("print(path_exists(\\"/secret.txt\\"))")\n'
            "sub.run()\n"
        )
        engine = SericiteEngine()
        vm = engine.create_root(source)
        vm.run()
        child = next(c for c in engine._contexts.values() if c.parent_id == 0)
        self.assertFalse(child.fs.path_exists("/secret.txt"))

    def test_parent_presets_child_files(self):
        source = (
            'sub = VM("print(read_file(\\"/config.txt\\"))")\n'
            'sub.write_file("/config.txt", "preset")\n'
            "print(sub.run())\n"
        )
        self.assertEqual(run(source), "preset\n\n")

    def test_parent_reads_child_output_file(self):
        source = (
            'sub = VM("write_file(\\"/result.txt\\", \\"done\\")")\n'
            "sub.run()\n"
            'print(sub.read_file("/result.txt"))\n'
        )
        self.assertEqual(run(source), "done\n")

    def test_host_presets_and_inspects(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'content = read_file("/input.txt")\n'
            'write_file("/output.txt", content + "!")\n'
        )
        vm.write_file("/input.txt", "hello")
        vm.run()
        self.assertEqual(vm.read_file("/output.txt"), "hello!")


if __name__ == "__main__":
    unittest.main()
