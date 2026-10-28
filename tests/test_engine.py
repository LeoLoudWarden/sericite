import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits, VMHandle

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
        self.assertEqual(snap["locals"], {"a": "2"})
        self.assertEqual(snap["last_line"], 1)
        self.assertEqual(snap["next_line"], 2)

        snap = vm.step()
        self.assertEqual(snap["locals"], {"a": "2", "b": "3"})

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
        self.assertEqual(snap["locals"], {})

        vm.feed_input("2")
        snap = vm.step()
        self.assertEqual(snap["state"], "ready")
        self.assertEqual(snap["locals"], {"a": "2"})

        vm.feed_input("3")
        output = vm.run()
        self.assertEqual(output, "23\n")

    def test_empty_program_is_done(self):
        engine = SericiteEngine()
        vm = engine.create_root("")
        self.assertEqual(vm.snapshot()["state"], "done")
        self.assertEqual(vm.run(), "")


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

    def test_error_views_never_expose_engine_filename(self):
        engine = SericiteEngine()
        source = (
            "try:\n"
            '    VM("def broken(:")\n'
            "except syntax_error as e:\n"
            '    print("compile:", e)\n'
            'sub = VM("raise \\"boom\\"")\n'
            "try:\n"
            "    sub.run()\n"
            "except raise_error as e:\n"
            '    print("runtime:", e)\n'
        )
        output = engine.create_root(source).run()
        self.assertEqual(output, "compile: invalid syntax\nruntime: boom\n")
        self.assertNotIn("sericite", output)
        error = VMHandle(engine, 1).snapshot()["error"]
        self.assertEqual(set(error.keys()), {"kind", "message", "line", "column"})
        self.assertNotIn("sericite", error["message"])


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


if __name__ == "__main__":
    unittest.main()
