import unittest
from dataclasses import replace

from sericite import (
    SericiteEngine,
    SericiteError,
    SericiteFrame,
    SericiteLimits,
    VMHandle,
)

ADD_PROGRAM = """\
a = input()
b = input()
c = a + b
print(c)
"""

SUB_VM_PROGRAM = """\
vm_code = \"\"\"
a = input()
b = input()
c = a + b
print(c)
\"\"\"
sub = VM(vm_code)
sub_output = sub.run(["2", "3"])
print(sub_output)
"""


class RootVMTests(unittest.TestCase):
    def test_run(self):
        engine = SericiteEngine()
        vm = engine.create_root(ADD_PROGRAM)
        output = vm.run(["2", "3"])
        self.assertEqual(output, "23\n")
        self.assertEqual(vm.snapshot()["state"], "done")

    def test_step_by_step(self):
        engine = SericiteEngine()
        vm = engine.create_root(ADD_PROGRAM, inputs=["2", "3"])

        snap = vm.step()
        self.assertEqual(snap["state"], "ready")
        self.assertEqual(snap["locals"], {"argv": [], "a": "2"})
        self.assertEqual(snap["last_line"], 1)
        self.assertEqual(snap["next_line"], 2)

        snap = vm.step()
        self.assertEqual(snap["locals"], {"argv": [], "a": "2", "b": "3"})

        snap = vm.step()
        self.assertEqual(snap["locals"]["c"], "23")

        snap = vm.step()
        self.assertEqual(snap["state"], "done")
        self.assertEqual(snap["stdout"], "23\n")

        snap = vm.step()
        self.assertEqual(snap["state"], "done")

    def test_waiting_input_and_resume(self):
        engine = SericiteEngine()
        vm = engine.create_root(ADD_PROGRAM)

        snap = vm.step()
        self.assertEqual(snap["state"], "waiting_input")
        self.assertEqual(snap["locals"], {"argv": []})

        vm.feed_input("2")
        snap = vm.step()
        self.assertEqual(snap["state"], "ready")
        self.assertEqual(snap["locals"], {"argv": [], "a": "2"})

        vm.feed_input("3")
        output = vm.run()
        self.assertEqual(output, "23\n")

    def test_empty_program_is_done(self):
        engine = SericiteEngine()
        vm = engine.create_root("")
        self.assertEqual(vm.snapshot()["state"], "done")
        self.assertEqual(vm.run(), "")

    def test_root_argv_defaults_to_empty_list(self):
        vm = SericiteEngine().create_root("print(argv)")
        self.assertEqual(vm.run(), "[]\n")

    def test_root_argv_is_copied_and_persists_across_exec(self):
        host_argv = ["app.sericite", "first"]
        vm = SericiteEngine().create_root("", argv=host_argv)
        host_argv.append("host-only")
        self.assertEqual(vm.exec("argv.append('second')"), "")
        self.assertEqual(
            vm.exec("print(argv)"), "['app.sericite', 'first', 'second']\n"
        )

    def test_root_argv_is_not_inherited_by_child_vms(self):
        vm = SericiteEngine().create_root(
            "sub = VM('print(argv)')\n"
            "try:\n"
            "    sub.run()\n"
            "except name_error:\n"
            "    print('isolated')",
            argv=["root-only"],
        )
        self.assertEqual(vm.run(), "isolated\n")

    def test_root_argv_rejects_non_string_values(self):
        engine = SericiteEngine()
        for value in ("app", 42, ["app", 1]):
            with self.subTest(value=value), self.assertRaises(SericiteError) as ctx:
                engine.create_root("", argv=value)
            self.assertEqual(ctx.exception.kind, "type_error")

    def test_root_argv_cannot_be_shadowed_by_a_host_function(self):
        with self.assertRaises(SericiteError) as ctx:
            SericiteEngine().create_root("", functions={"argv": list})
        self.assertEqual(ctx.exception.kind, "type_error")


class SubVMTests(unittest.TestCase):
    def test_sub_vm_io_isolated(self):
        engine = SericiteEngine()
        vm = engine.create_root(SUB_VM_PROGRAM)
        output = vm.run()
        self.assertEqual(output, "23\n\n")

    def test_handle_repr_shows_state_without_engine_counter(self):
        engine = SericiteEngine()
        vm = engine.create_root(SUB_VM_PROGRAM)
        vm.step()
        vm.step()
        sub = vm.snapshot()["locals"]["sub"]
        self.assertEqual(sub, "<VM state=ready>")
        self.assertNotIn("id=", sub)

    def test_nested_vm_creation(self):
        mid_src = "inner = VM(\"print('deep')\")\nprint(inner.run())\n"
        engine = SericiteEngine()
        vm = engine.create_root(f"sub = VM({mid_src!r})\nprint(sub.run())\n")
        self.assertEqual(vm.run(), "deep\n\n\n")

    def test_debug_sub_vm_from_root(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'sub = VM("a = input()\\nprint(a)")\n'
            "first = sub.step()\n"
            'sub.feed_input("hi")\n'
            "sub.step()\n"
            "last = sub.step()\n"
            "print(sub.stdout())\n"
        )
        output = vm.run()
        self.assertEqual(output, "hi\n\n")

    def test_layer1_can_create_vm(self):
        mid_src = 'inner = VM("x = 1")\nprint(inner.snapshot())\n'
        engine = SericiteEngine()
        vm = engine.create_root(f"sub = VM({mid_src!r})\nprint(sub.run())\n")
        output = vm.run()
        self.assertIn("'state': 'ready'", output)

    def test_child_vm_stdout_does_not_leak_to_parent(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'sub = VM("print(\\"inner\\")")\nsub.run()\nprint("outer")\n'
        )
        output = vm.run()
        self.assertEqual(output, "outer\n")


class SnapshotViewTests(unittest.TestCase):
    def test_host_snapshot_includes_diagnostics(self):
        engine = SericiteEngine()
        vm = engine.create_root('sub = VM("inner = VM(\\"x = 1\\")")\nsub.run()\n')
        vm.run()
        root = vm.snapshot()
        self.assertEqual(root["vm_id"], 0)
        self.assertIsNone(root["parent_id"])
        self.assertEqual(root["depth"], 0)
        self.assertEqual(root["child_count"], 1)
        sub = VMHandle(engine, 1).snapshot()
        self.assertEqual(sub["vm_id"], 1)
        self.assertEqual(sub["parent_id"], 0)
        self.assertEqual(sub["depth"], 1)
        self.assertEqual(sub["child_count"], 1)
        inner = VMHandle(engine, 2).snapshot()
        self.assertEqual(inner["parent_id"], 1)
        self.assertEqual(inner["depth"], 2)
        self.assertEqual(inner["child_count"], 0)

    def test_host_step_and_step_instruction_include_diagnostics(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 1\n")
        for snap in (vm.step(), vm.step_instruction()):
            self.assertEqual(snap["vm_id"], 0)
            self.assertEqual(snap["depth"], 0)
            self.assertEqual(snap["child_count"], 0)

    def test_script_snapshot_never_includes_diagnostics(self):
        engine = SericiteEngine()
        source = (
            'sub = VM("x = 1")\n'
            "snap = sub.snapshot()\n"
            "print(len(snap))\n"
            'print("vm_id" in snap)\n'
            'print("parent_id" in snap)\n'
            'print("depth" in snap)\n'
            'print("child_count" in snap)\n'
            "after_step = sub.step()\n"
            "print(len(after_step))\n"
            'print("vm_id" in after_step)\n'
            'print("state" in after_step)\n'
        )
        output = engine.create_root(source).run()
        self.assertEqual(
            output,
            "7\nFalse\nFalse\nFalse\nFalse\n7\nFalse\nTrue\n",
        )

    def test_vm_repr_hides_engine_counter(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'sub = VM("x = 1")\nprint(sub)\nprint(sub.snapshot())\n'
        )
        output = vm.run()
        lines = output.splitlines()
        self.assertEqual(lines[0], "<VM state=ready>")
        self.assertNotIn("vm_id", output)
        self.assertEqual(repr(VMHandle(engine, 1)), "<VM state=ready>")

    def test_child_count_counts_created_children_not_attempts(self):
        engine = SericiteEngine()
        source = (
            "i = 0\n"
            "while i < 5:\n"
            "    try:\n"
            '        VM("def broken(:")\n'
            "    except syntax_error:\n"
            "        pass\n"
            "    i += 1\n"
            'sub = VM("x = 1")\n'
        )
        vm = engine.create_root(source)
        vm.run()
        self.assertEqual(vm.snapshot()["child_count"], 1)
        self.assertEqual(len(engine._contexts), 2)

    def test_failed_child_creation_does_not_consume_child_quota(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            "try:\n"
            '    VM("def broken(:")\n'
            "except syntax_error:\n"
            "    pass\n"
            'sub = VM("print(1)")\n'
            "print(sub.run())\n",
            limits=SericiteLimits(max_child_vms=1),
        )
        self.assertEqual(vm.run(), "1\n\n")

    def test_failed_const_allocation_leaves_no_orphan_context(self):
        engine = SericiteEngine()
        source = (
            's = "a"\n'
            "i = 0\n"
            "while i < 12:\n"
            "    s = s + s\n"
            "    i += 1\n"
            'src = "x = \\"" + s + "\\""\n'
            "try:\n"
            "    sub = VM(src, max_total_bytes=2048)\n"
            "except resource_exhausted:\n"
            '    print("must not happen")\n'
        )
        vm = engine.create_root(source)
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertNotIn("must not happen", vm.stdout())
        self.assertEqual(len(engine._contexts), 1)
        self.assertEqual(vm.snapshot()["child_count"], 0)
        second = engine.create_root("print(1)\n")
        self.assertEqual(second.snapshot()["vm_id"], 1)

    def test_error_views_never_expose_engine_filename(self):
        engine = SericiteEngine()
        source = (
            "try:\n"
            '    VM("def broken(:")\n'
            "except syntax_error as e:\n"
            '    print("compile:", e.message)\n'
            'sub = VM("raise \\"boom\\"")\n'
            "try:\n"
            "    sub.run()\n"
            "except raise_error as e:\n"
            '    print("runtime:", e.message)\n'
        )
        output = engine.create_root(source).run()
        self.assertEqual(output, "compile: invalid syntax\nruntime: boom\n")
        self.assertNotIn("sericite", output)
        error = VMHandle(engine, 1).snapshot()["error"]
        self.assertEqual(
            set(error.keys()), {"kind", "message", "line", "column", "frames"}
        )
        self.assertNotIn("sericite", error["message"])
        self.assertNotIn("sericite:vm", repr(error["frames"]))

    def test_uncaught_error_frames_survive_unwinding(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            "def inner():\n"
            "    return missing + 1\n\n"
            "def outer():\n"
            "    return inner()\n\n"
            "outer()\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        expected = [("<module>", 7), ("outer", 5), ("inner", 2)]
        self.assertEqual(
            [(frame.function, frame.line) for frame in ctx.exception.frames],
            expected,
        )
        self.assertEqual(
            vm.snapshot()["error"]["frames"],
            [{"function": function, "line": line} for function, line in expected],
        )
        self.assertTrue(
            all(isinstance(frame, SericiteFrame) for frame in ctx.exception.frames)
        )

    def test_traceback_uses_call_line_in_multiline_expressions(self):
        cases = {
            "assignment": (
                ("def f():\n    return 1 / 0\n\nx = (\n    f()\n)\n"),
                5,
            ),
            "print_argument": (
                ('def f():\n    return 1 / 0\n\nprint(\n    "before",\n    f(),\n)\n'),
                6,
            ),
        }
        for name, (source, call_line) in cases.items():
            with self.subTest(name=name):
                vm = SericiteEngine().create_root(source)
                with self.assertRaises(SericiteError) as ctx:
                    vm.run()
                self.assertEqual(ctx.exception.line, 2)
                self.assertEqual(
                    [(frame.function, frame.line) for frame in ctx.exception.frames],
                    [("<module>", call_line), ("f", 2)],
                )

    def test_traceback_uses_each_call_line_across_nested_calls(self):
        vm = SericiteEngine().create_root(
            "def inner():\n"
            "    return 1 / 0\n\n"
            "def middle():\n"
            "    return inner()\n\n"
            "def outer():\n"
            "    return middle(\n"
            "    )\n\n"
            "result = outer(\n"
            ")\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.line, 2)
        self.assertEqual(
            [(frame.function, frame.line) for frame in ctx.exception.frames],
            [("<module>", 11), ("outer", 8), ("middle", 5), ("inner", 2)],
        )

    def test_native_and_host_errors_keep_the_call_site_line(self):
        def boom():
            raise ValueError("secret")

        cases = {
            "native": (SericiteEngine().create_root("value = len(\n    1,\n)\n"), None),
            "host": (
                SericiteEngine().create_root(
                    "value = boom(\n)\n", functions={"boom": boom}
                ),
                "host_error",
            ),
        }
        for name, (vm, kind) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(SericiteError) as ctx:
                    vm.run()
                if kind is not None:
                    self.assertEqual(ctx.exception.kind, kind)
                self.assertEqual(ctx.exception.line, 1)
                self.assertEqual(
                    [(frame.function, frame.line) for frame in ctx.exception.frames],
                    [("<module>", 1)],
                )

    def test_trace_capture_preserves_internal_error_on_quota_failure(self):
        engine = SericiteEngine(limits=SericiteLimits(max_total_bytes=0))
        engine.create_root("pass\n")
        error = SericiteError("internal bug", kind="internal_error")
        engine._capture_error(engine._contexts[0], error, 1)
        self.assertEqual(error.kind, "internal_error")
        self.assertEqual(error.frames, ())

    def test_trace_capture_tolerates_invalid_caller_pc(self):
        engine = SericiteEngine()
        engine.create_root("pass\n")
        context = engine._contexts[0]
        context.frames.append(replace(context.frames[0]))
        context.frames[0].pc = len(context.frames[0].code.instrs)
        error = SericiteError("damaged frame", kind="internal_error")
        engine._capture_error(context, error, 1)
        self.assertIsNone(error.frames[0].line)
        self.assertEqual(error.frames[1].line, 1)


class ValidationTests(unittest.TestCase):
    def test_syntax_error(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("a = = 1\n")
        self.assertEqual(ctx.exception.kind, "syntax_error")

    def test_unsupported_syntax_rejected(self):
        engine = SericiteEngine()
        for source in ("import os\n", "del x\n"):
            with self.assertRaises(SericiteError, msg=source):
                engine.create_root(source)

    def test_dunder_names_rejected(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError):
            engine.create_root("x = __builtins__\n")
        with self.assertRaises(SericiteError):
            engine.create_root('sub = VM("x = 1")\nsub.__class__()\n')

    def test_reserved_names_call_only(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError):
            engine.create_root("f = input\n")
        with self.assertRaises(SericiteError):
            engine.create_root("x = VM\n")

    def test_unsupported_attribute_rejected(self):
        engine = SericiteEngine()
        vm = engine.create_root('sub = VM("x = 1")\nsub.evil()\n')
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "attribute_error")

    def test_duplicate_parameters_rejected_at_compile_time(self):
        cases = {
            "simple": ("def f(x, x):\n    return x\n", 1),
            "default": ("def f(x, x=1):\n    return x\n", 1),
            "nested": (
                "def outer():\n    def inner(x, y, x):\n        return x\n",
                2,
            ),
        }
        for name, (source, line) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                error = ctx.exception
                self.assertEqual(error.kind, "syntax_error")
                self.assertIn("duplicate parameter 'x'", error.message)
                self.assertEqual(error.line, line)
                self.assertEqual(
                    error.column, source.splitlines()[line - 1].rindex("x") + 1
                )

    def test_duplicate_keywords_rejected_for_functions_and_records(self):
        cases = {
            "function": (
                "def f(x):\n    return x\nf(x=1, x=2)\n",
                3,
                "x=2",
            ),
            "record": ("class P:\n    x: int\nP(x=1, x=2)\n", 3, "x=2"),
        }
        for name, (source, line, marker) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                error = ctx.exception
                self.assertEqual(error.kind, "syntax_error")
                self.assertIn("duplicate keyword argument 'x'", error.message)
                self.assertEqual(error.line, line)
                self.assertEqual(
                    error.column, source.splitlines()[line - 1].index(marker) + 1
                )

    def test_explicit_none_annotations_rejected_at_compile_time(self):
        cases = {
            "parameter": ("def f(x: None):\n    return x\n", 1),
            "return": ("def f() -> None:\n    return 1\n", 1),
            "field": ("class P:\n    x: None\n", 2),
            "assignment": ("x: None = 1\n", 1),
        }
        for name, (source, line) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteEngine().create_root(source)
                error = ctx.exception
                self.assertEqual(error.kind, "syntax_error")
                self.assertEqual(
                    error.message, "None is not a contract; omit the annotation"
                )
                self.assertEqual(error.line, line)
                self.assertEqual(
                    error.column, source.splitlines()[line - 1].index("None") + 1
                )

    def test_none_values_and_omitted_annotations_remain_valid(self):
        output = (
            SericiteEngine()
            .create_root(
                "def identity(x):\n"
                "    return x\n"
                "def default(x=None):\n"
                "    return x\n"
                "def nothing():\n"
                "    return None\n"
                "class P:\n"
                "    x\n"
                "print(identity(1), identity(None), default(), nothing(), P(None).x)\n"
            )
            .run()
        )
        self.assertEqual(output, "1 None None None None\n")

    def test_runtime_error_reported(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = missing\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertIn("missing", ctx.exception.message)
        self.assertEqual(vm.snapshot()["state"], "error")
        self.assertIsNotNone(vm.snapshot()["error"])

    def test_bad_add_operands(self):
        engine = SericiteEngine()
        vm = engine.create_root('x = "a" + 1\n')
        with self.assertRaises(SericiteError):
            vm.run()


class ExecSourceTests(unittest.TestCase):
    def test_module_scope_persists_across_exec(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 41")
        vm.run()
        self.assertEqual(vm.exec("x += 1\ndef answer():\n    return x"), "")
        self.assertEqual(vm.exec("print(answer())"), "42\n")

    def test_old_functions_see_new_module_bindings(self):
        engine = SericiteEngine()
        vm = engine.create_root("def get():\n    return later")
        vm.run()
        self.assertEqual(vm.exec("later = 7\nprint(get())"), "7\n")

    def test_vfs_persists_across_exec(self):
        engine = SericiteEngine()
        vm = engine.create_root("")
        vm.exec("write_file('/note.txt', 'hello')")
        self.assertEqual(vm.exec("print(read_file('/note.txt'))"), "hello\n")

    def test_exec_returns_only_new_output(self):
        engine = SericiteEngine()
        vm = engine.create_root("print('first')")
        self.assertEqual(vm.run(), "first\n")
        self.assertEqual(vm.exec("print('second')"), "second\n")
        self.assertEqual(vm.stdout(), "first\nsecond\n")

    def test_exec_recovers_from_runtime_error(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 5")
        vm.run()
        with self.assertRaises(SericiteError) as ctx:
            vm.exec('raise "boom"')
        self.assertEqual(ctx.exception.kind, "raise_error")
        self.assertEqual(vm.snapshot()["state"], "error")
        self.assertEqual(vm.exec("print(x)"), "5\n")
        self.assertEqual(vm.snapshot()["state"], "done")

    def test_exec_compile_failure_leaves_vm_untouched(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 9")
        vm.run()
        with self.assertRaises(SericiteError) as ctx:
            vm.exec("def broken(:")
        self.assertEqual(ctx.exception.kind, "syntax_error")
        self.assertEqual(vm.snapshot()["state"], "done")
        self.assertEqual(vm.exec("print(x)"), "9\n")

    def test_exec_validation_failure_is_syntax_error_and_leaves_vm_untouched(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 9")
        vm.run()
        with self.assertRaises(SericiteError) as ctx:
            vm.exec("x = __class__")
        self.assertEqual(ctx.exception.kind, "syntax_error")
        self.assertEqual(vm.snapshot()["state"], "done")
        self.assertEqual(vm.exec("print(x)"), "9\n")

    def test_exec_rejects_terminated_vm(self):
        engine = SericiteEngine()
        vm = engine.create_root("x = 1")
        vm.terminate()
        with self.assertRaises(SericiteError) as ctx:
            vm.exec("print(1)")
        self.assertEqual(ctx.exception.kind, "runtime_error")

    def test_exec_rejects_non_string_source(self):
        engine = SericiteEngine()
        vm = engine.create_root("")
        with self.assertRaises(SericiteError) as ctx:
            vm.exec(42)
        self.assertEqual(ctx.exception.kind, "type_error")

    def test_exec_replaces_pending_program(self):
        engine = SericiteEngine()
        vm = engine.create_root("print('never ran')\nx = 1")
        self.assertEqual(vm.exec("print('replacement')"), "replacement\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.exec("print(x)")
        self.assertEqual(ctx.exception.kind, "name_error")
        self.assertEqual(vm.stdout(), "replacement\n")

    def test_script_level_exec_keeps_child_alive(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'sub = VM("")\n'
            'print(sub.exec("y = 10"))\n'
            'print(sub.exec("y += 5\\nprint(y)"))\n'
            "try:\n"
            '    sub.exec("raise \\"x\\"")\n'
            "except:\n"
            '    print("recovered")\n'
            'print(sub.exec("print(y + 1)"))\n'
        )
        self.assertEqual(vm.run(), "\n15\n\nrecovered\n16\n\n")

    def test_script_level_exec_shares_vfs_with_handle_methods(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'sub = VM("")\n'
            'sub.write_file("/seed.txt", "seed")\n'
            "print(sub.exec(\"write_file('/made.txt', read_file('/seed.txt'))\"))\n"
            'print(sub.read_file("/made.txt"))\n'
        )
        self.assertEqual(vm.run(), "\nseed\n")

    def test_exec_counts_against_vm_quotas(self):
        engine = SericiteEngine()
        vm = engine.create_root("", limits=None)
        before = vm.snapshot()["instruction_count"]
        vm.exec("print('metered')")
        after = vm.snapshot()["instruction_count"]
        self.assertGreater(after, before)


CUMULATIVE_OPTIONS = {
    "max_instructions",
    "max_output_bytes",
    "max_child_vms",
    "max_total_bytes",
    "max_total_vms",
}
STRUCTURAL_OPTIONS = {
    "max_frames",
    "max_list_size",
    "max_dict_size",
    "max_string_bytes",
    "max_int_bits",
    "max_vm_depth",
    "max_fs_files",
    "max_fs_file_bytes",
}


def unlimited_limits():
    return SericiteLimits(**{name: -1 for name in CUMULATIVE_OPTIONS})


class UnlimitedLimitTests(unittest.TestCase):
    def test_host_limit_validation(self):
        for name in CUMULATIVE_OPTIONS:
            with self.subTest(name=name):
                self.assertEqual(
                    getattr(SericiteLimits(**{name: -1}), name),
                    -1,
                )
        for name in CUMULATIVE_OPTIONS | STRUCTURAL_OPTIONS:
            for value in (-2, True, 1.5, "1"):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(SericiteError) as ctx:
                        SericiteLimits(**{name: value})
                    self.assertEqual(ctx.exception.kind, "type_error")
        for name in STRUCTURAL_OPTIONS:
            with self.subTest(name=name, value=-1):
                with self.assertRaises(SericiteError) as ctx:
                    SericiteLimits(**{name: -1})
                self.assertEqual(ctx.exception.kind, "type_error")

    def test_script_limit_validation(self):
        engine = SericiteEngine(unlimited_limits())
        options = ", ".join(f"{name}=-1" for name in sorted(CUMULATIVE_OPTIONS))
        vm = engine.create_root(f'sub = VM("", {options})\nsub.dispose()')
        self.assertEqual(vm.run(), "")
        for name in STRUCTURAL_OPTIONS:
            with self.subTest(name=name):
                vm = SericiteEngine().create_root(f'sub = VM("", {name}=-1)')
                with self.assertRaises(SericiteError) as ctx:
                    vm.run()
                self.assertEqual(ctx.exception.kind, "type_error")
        for value in ("-2", "True", "1.5"):
            with self.subTest(value=value):
                vm = SericiteEngine().create_root(
                    f'sub = VM("", max_instructions={value})'
                )
                with self.assertRaises(SericiteError) as ctx:
                    vm.run()
                self.assertEqual(ctx.exception.kind, "type_error")

    def test_unlimited_limits_still_accumulate_ledgers(self):
        engine = SericiteEngine(unlimited_limits())
        vm = engine.create_root(
            "values = range(2)\ni = 0\nwhile i < 20:\n    i += 1\nprint(i)"
        )
        self.assertEqual(vm.run(), "20\n")
        self.assertGreater(vm.snapshot()["instruction_count"], 20)
        self.assertGreater(engine._contexts[0].alloc_bytes, 0)
        self.assertIsNone(engine._contexts[0].io.remaining_output_bytes)

    def test_unlimited_child_cannot_bypass_finite_parent(self):
        engine = SericiteEngine(SericiteLimits(max_instructions=100))
        vm = engine.create_root(
            'sub = VM("while True:\\n    pass", max_instructions=-1)\nsub.run()'
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")

    def test_finite_child_still_bounded_under_unlimited_parent(self):
        engine = SericiteEngine(unlimited_limits())
        vm = engine.create_root(
            'sub = VM("while True:\\n    pass", max_instructions=50)\nsub.run()'
        )
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertLessEqual(engine._contexts[1].instruction_count, 51)

    def test_granted_spawn_preserves_finite_caller_ceiling(self):
        engine = SericiteEngine(unlimited_limits())
        vm = engine.create_root(
            "def spawn():\n"
            "    return VM('', max_instructions=-1)\n"
            "sub = VM('grandchild = spawn()', functions={'spawn': spawn}, "
            "max_instructions=100)\n"
            "sub.run()"
        )
        vm.run()
        self.assertEqual(engine._contexts[2].limits.max_instructions, 100)

    def test_unlimited_vm_creation_with_dispose(self):
        engine = SericiteEngine(unlimited_limits())
        vm = engine.create_root(
            'for i in range(1001):\n    sub = VM("")\n    sub.dispose()'
        )
        vm.run()
        self.assertEqual(vm.snapshot()["child_count"], 1001)
        self.assertEqual(engine._next_vm_id, 1002)
        self.assertEqual(set(engine._contexts), {0})


class DisposeTests(unittest.TestCase):
    def test_host_dispose_is_idempotent_and_invalidates_handle(self):
        engine = SericiteEngine()
        vm = engine.create_root("")
        vm.dispose()
        vm.dispose()
        self.assertEqual(repr(vm), "<VM state=disposed>")
        self.assertEqual(engine._contexts, {})
        calls = (
            lambda: vm.run(),
            lambda: vm.exec("pass"),
            lambda: vm.snapshot(),
            lambda: vm.stdout(),
            lambda: vm.terminate(),
            lambda: vm.read_file("/x"),
        )
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(SericiteError) as ctx:
                    call()
                self.assertEqual(ctx.exception.kind, "runtime_error")

    def test_script_dispose_is_idempotent_and_stale_methods_fail(self):
        engine = SericiteEngine()
        vm = engine.create_root(
            'sub = VM("x = 1")\n'
            "sub.run()\n"
            "sub.dispose()\n"
            "sub.dispose()\n"
            "print(sub)\n"
            "try:\n"
            "    sub.snapshot()\n"
            "except runtime_error:\n"
            '    print("stale rejected")'
        )
        self.assertEqual(
            vm.run(),
            "<VM state=disposed>\nstale rejected\n",
        )
        self.assertEqual(vm.snapshot()["child_count"], 1)
        self.assertEqual(set(engine._contexts), {0})

    def test_dispose_requires_terminal_state(self):
        engine = SericiteEngine()
        ready = engine.create_root("x = 1")
        with self.assertRaises(SericiteError) as ctx:
            ready.dispose()
        self.assertEqual(ctx.exception.kind, "runtime_error")
        waiting = engine.create_root("input()")
        waiting.step()
        self.assertEqual(waiting.snapshot()["state"], "waiting_input")
        with self.assertRaises(SericiteError) as ctx:
            waiting.dispose()
        self.assertEqual(ctx.exception.kind, "runtime_error")
        waiting.terminate()
        waiting.dispose()

        failed = engine.create_root("1 / 0")
        with self.assertRaises(SericiteError):
            failed.run()
        self.assertEqual(failed.snapshot()["state"], "error")
        failed.dispose()

        exhausted = engine.create_root(
            "while True:\n    pass",
            limits=SericiteLimits(max_instructions=10),
        )
        with self.assertRaises(SericiteError):
            exhausted.run()
        self.assertEqual(exhausted.snapshot()["state"], "resource_exhausted")
        exhausted.dispose()

    def test_dispose_requires_child_first_order(self):
        engine = SericiteEngine()
        root = engine.create_root('sub = VM("inner = VM(\\"\\")")\nsub.run()')
        root.run()
        child = VMHandle(engine, 1)
        grandchild = VMHandle(engine, 2)
        for handle in (root, child):
            with self.subTest(handle=handle):
                with self.assertRaises(SericiteError) as ctx:
                    handle.dispose()
                self.assertEqual(ctx.exception.kind, "runtime_error")
        grandchild.dispose()
        child.dispose()
        root.dispose()
        self.assertEqual(engine._contexts, {})

    def test_dispose_does_not_refund_cumulative_quotas_or_ids(self):
        for name in ("max_child_vms", "max_total_vms"):
            with self.subTest(name=name):
                config = {key: -1 for key in CUMULATIVE_OPTIONS}
                config[name] = 1 if name == "max_child_vms" else 2
                engine = SericiteEngine(SericiteLimits(**config))
                vm = engine.create_root('sub = VM("")\nsub.dispose()\nsub = VM("")')
                with self.assertRaises(SericiteError) as ctx:
                    vm.run()
                self.assertEqual(ctx.exception.kind, "resource_exhausted")
                self.assertEqual(vm.snapshot()["child_count"], 1)

        engine = SericiteEngine(unlimited_limits())
        vm = engine.create_root('sub = VM("")\nsub.dispose()\nsub = VM("")')
        vm.run()
        self.assertEqual(engine._next_vm_id, 3)
        self.assertEqual(set(engine._contexts), {0, 2})
        self.assertGreater(engine._contexts[0].instruction_count, 0)
        self.assertGreater(engine._contexts[0].alloc_bytes, 0)


if __name__ == "__main__":
    unittest.main()
