import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


class BreakpointAPITests(unittest.TestCase):
    def test_host_locations_are_ordered_idempotent_and_normalized(self):
        vm = SericiteEngine().create_root("x = 1\n")
        self.assertIsNone(vm.add_breakpoint(1))
        vm.add_breakpoint(2, "pkg/../util.sericite")
        vm.add_breakpoint(1)
        vm.add_breakpoint(2, path="/util.sericite")
        self.assertEqual(
            vm.breakpoints(),
            [
                {"line": 1, "path": None},
                {"line": 2, "path": "/util.sericite"},
            ],
        )
        self.assertIsNone(vm.remove_breakpoint(1))
        self.assertIsNone(vm.remove_breakpoint(1))
        vm.remove_breakpoint(2, "/util.sericite")
        self.assertEqual(vm.breakpoints(), [])
        vm.add_breakpoint(1)
        vm.run()
        self.assertEqual(vm.snapshot()["state"], "paused")
        vm.terminate()
        vm.add_breakpoint(3)
        self.assertEqual(len(vm.breakpoints()), 2)
        vm.dispose()
        with self.assertRaises(SericiteError) as caught:
            vm.breakpoints()
        self.assertEqual(caught.exception.kind, "runtime_error")

    def test_script_api_and_snapshot_are_safe(self):
        root = SericiteEngine().create_root(
            'sub = VM("x = 1\\nx = 2")\n'
            "sub.add_breakpoint(1)\n"
            'sub.add_breakpoint(2, "pkg/../mod.sericite")\n'
            "sub.add_breakpoint(1)\n"
            "print(sub.breakpoints())\n"
            "sub.run()\n"
            "snap = sub.snapshot()\n"
            "print(snap)\n"
            "print(len(snap))\n"
        )
        output = root.run()
        self.assertIn(
            "[{'line': 1, 'path': None}, {'line': 2, 'path': '/mod.sericite'}]",
            output,
        )
        self.assertIn("'state': 'paused'", output)
        self.assertIn("'breakpoint': {'line': 1, 'path': None}", output)
        self.assertIn("8\n", output)
        self.assertNotIn("vm_id", output)
        self.assertNotIn("parent_id", output)

    def test_invalid_arguments_are_rejected(self):
        vm = SericiteEngine().create_root("x = 1")
        for line in (None, True, 0, -1, 1.0, "1"):
            with self.subTest(line=line), self.assertRaises(SericiteError) as caught:
                vm.add_breakpoint(line)
            self.assertEqual(caught.exception.kind, "type_error")
        for path in (1, [], False):
            with self.subTest(path=path), self.assertRaises(SericiteError) as caught:
                vm.add_breakpoint(1, path)
            self.assertEqual(caught.exception.kind, "type_error")

        operations = (
            "sub.add_breakpoint()",
            "sub.add_breakpoint(1, 2, 3)",
            "sub.add_breakpoint(line=1, path=None, extra=2)",
            "sub.add_breakpoint(True)",
            "sub.breakpoints(1)",
        )
        for operation in operations:
            with self.subTest(operation=operation):
                root = SericiteEngine().create_root(
                    'sub = VM("x = 1")\n'
                    "try:\n"
                    f"    {operation}\n"
                    "except type_error:\n"
                    "    print('caught')"
                )
                self.assertEqual(root.run(), "caught\n")

    def test_script_keyword_forms_and_terminal_management(self):
        root = SericiteEngine().create_root(
            'sub = VM("x = 1")\n'
            "sub.add_breakpoint(line=1, path=None)\n"
            "sub.remove_breakpoint(line=1)\n"
            "sub.add_breakpoint(1)\n"
            "sub.run()\n"
            "print(sub.snapshot()['state'])\n"
            "sub.remove_breakpoint(1)\n"
            "print(sub.run())\n"
            "sub.add_breakpoint(1)\n"
            "print(sub.breakpoints())\n"
        )
        self.assertEqual(root.run(), "paused\n\n[{'line': 1, 'path': None}]\n")

    def test_limit_is_structural_inherited_and_atomic(self):
        for value in (-1, -2, 1.5, True):
            with self.subTest(value=value), self.assertRaises(SericiteError):
                SericiteLimits(max_breakpoints=value)

        vm = SericiteEngine().create_root(
            "x = 1\ny = 2", limits=SericiteLimits(max_breakpoints=1)
        )
        vm.add_breakpoint(1)
        with self.assertRaises(SericiteError) as caught:
            vm.add_breakpoint(2)
        self.assertEqual(caught.exception.kind, "breakpoint_limit_error")
        self.assertEqual(vm.breakpoints(), [{"line": 1, "path": None}])
        self.assertEqual(vm.snapshot()["state"], "ready")
        vm.add_breakpoint(1)
        self.assertEqual(vm.snapshot()["state"], "ready")

        root = SericiteEngine().create_root(
            'sub = VM("x = 1", max_breakpoints=0)\n'
            "try:\n"
            "    sub.add_breakpoint(1)\n"
            "except breakpoint_limit_error as error:\n"
            "    print(error.kind)\n"
            "sub.run()\n"
            "print(sub.breakpoints())\n"
            "print('parent alive')"
        )
        self.assertEqual(root.run(), "breakpoint_limit_error\n[]\nparent alive\n")
        self.assertEqual(root.snapshot()["state"], "done")


class BreakpointExecutionTests(unittest.TestCase):
    def test_pauses_before_statement_without_charging_it(self):
        vm = SericiteEngine().create_root('x = 1\nprint("before")\nx += 1\nprint(x)')
        vm.add_breakpoint(3)
        self.assertEqual(vm.run(), "before\n")
        snapshot = vm.snapshot()
        self.assertEqual(snapshot["state"], "paused")
        self.assertIsNone(snapshot["last_line"])
        self.assertEqual(snapshot["next_line"], 3)
        self.assertEqual(snapshot["locals"]["x"], 1)
        self.assertEqual(snapshot["breakpoint"], {"line": 3, "path": None})
        self.assertIsNone(snapshot["error"])
        paused_count = snapshot["instruction_count"]
        self.assertEqual(vm.snapshot()["instruction_count"], paused_count)
        self.assertEqual(vm.run(), "before\n2\n")
        self.assertEqual(vm.snapshot()["state"], "done")
        self.assertIsNone(vm.snapshot()["breakpoint"])

    def test_ready_current_location_pauses_and_loop_rehits(self):
        ready = SericiteEngine().create_root("x = 1")
        ready.add_breakpoint(1)
        self.assertEqual(ready.step()["state"], "paused")
        self.assertEqual(ready.snapshot()["locals"], {"argv": []})

        vm = SericiteEngine().create_root("i = 0\nwhile i < 3:\n    i += 1\nprint(i)")
        vm.add_breakpoint(3)
        seen = []
        for _ in range(3):
            vm.run()
            self.assertEqual(vm.snapshot()["state"], "paused")
            seen.append(vm.snapshot()["locals"]["i"])
        self.assertEqual(seen, [0, 1, 2])
        self.assertEqual(vm.run(), "3\n")
        self.assertEqual(vm.snapshot()["state"], "done")

    def test_remove_while_paused_and_multiple_locations(self):
        vm = SericiteEngine().create_root("x = 1\nx = 2\nx = 3\nprint(x)")
        vm.add_breakpoint(2)
        vm.add_breakpoint(3)
        vm.run()
        self.assertEqual(vm.snapshot()["locals"]["x"], 1)
        vm.remove_breakpoint(2)
        self.assertEqual(vm.snapshot()["breakpoint"], {"line": 2, "path": None})
        vm.run()
        self.assertEqual(vm.snapshot()["state"], "paused")
        self.assertEqual(vm.snapshot()["locals"]["x"], 2)
        self.assertEqual(vm.run(), "3\n")

    def test_step_and_instruction_step_resume_current_statement(self):
        statement = SericiteEngine().create_root("x = 1\nx = 2\nx = 3")
        statement.add_breakpoint(2)
        statement.run()
        snapshot = statement.step()
        self.assertEqual(snapshot["state"], "ready")
        self.assertEqual(snapshot["locals"]["x"], 2)
        self.assertEqual(snapshot["next_line"], 3)
        self.assertEqual(statement.step()["state"], "done")

        instruction = SericiteEngine().create_root("x = 1\nx = 2\nx = 3")
        instruction.add_breakpoint(2)
        instruction.run()
        before = instruction.snapshot()["instruction_count"]
        snapshot = instruction.step_instruction()
        self.assertEqual(snapshot["instruction_count"], before + 1)
        self.assertEqual(snapshot["state"], "ready")
        self.assertEqual(snapshot["locals"]["x"], 1)
        self.assertEqual(instruction.run(), "")
        self.assertEqual(instruction.snapshot()["locals"]["x"], 3)

    def test_step_can_be_interrupted_inside_call(self):
        vm = SericiteEngine().create_root(
            "def f():\n    x = 1\n    return x\ny = f()\nprint(y)"
        )
        vm.add_breakpoint(2)
        self.assertEqual(vm.step()["state"], "ready")
        snapshot = vm.step()
        self.assertEqual(snapshot["state"], "paused")
        self.assertEqual(snapshot["next_line"], 2)
        self.assertEqual(vm.run(), "1\n")

    def test_only_statement_entry_lines_hit(self):
        source = "# comment\n\npass\nvalue = (\n    1 +\n    2\n)\nprint(value)"
        vm = SericiteEngine().create_root(source)
        for line in (1, 2, 3, 5, 6):
            vm.add_breakpoint(line)
        self.assertEqual(vm.run(), "3\n")
        self.assertEqual(vm.snapshot()["state"], "done")

        entry = SericiteEngine().create_root(source)
        entry.add_breakpoint(4)
        entry.run()
        self.assertEqual(entry.snapshot()["state"], "paused")
        self.assertNotIn("value", entry.snapshot()["locals"])
        self.assertEqual(entry.run(), "3\n")

    def test_compound_body_statements_keep_their_own_lines(self):
        cases = (
            "if True:\n    value = (\n        1 +\n        2\n    )\nprint(value)",
            "try:\n    value = 1\nfinally:\n    pass\nprint(value)",
        )
        for source in cases:
            with self.subTest(source=source):
                vm = SericiteEngine().create_root(source)
                vm.add_breakpoint(2)
                vm.run()
                self.assertEqual(vm.snapshot()["state"], "paused")
                self.assertEqual(vm.snapshot()["next_line"], 2)
                self.assertNotIn("value", vm.snapshot()["locals"])
                self.assertEqual(vm.run(), "1\n" if "try" in source else "3\n")

    def test_finally_breakpoint_hits_on_normal_early_and_error_exits(self):
        cases = {
            "normal": (
                "try:\n    x = 1\nfinally:\n    print('cleanup')",
                4,
            ),
            "break": (
                (
                    "while True:\n    try:\n        x = 1\n        break\n"
                    "    finally:\n        print('cleanup')"
                ),
                6,
            ),
            "continue": (
                (
                    "i = 0\nwhile i < 1:\n    i += 1\n    try:\n        x = 1\n"
                    "        continue\n    finally:\n        print('cleanup')"
                ),
                8,
            ),
            "return": (
                (
                    "def f():\n    try:\n        x = 1\n        return 1\n"
                    "    finally:\n        print('cleanup')\nf()"
                ),
                6,
            ),
            "error": (
                "try:\n    x = 1\n    raise 'boom'\nfinally:\n    print('cleanup')",
                5,
            ),
        }
        for name, (source, line) in cases.items():
            with self.subTest(name=name):
                vm = SericiteEngine().create_root(source)
                vm.add_breakpoint(line)
                self.assertEqual(vm.run(), "")
                self.assertEqual(vm.snapshot()["state"], "paused")
                self.assertEqual(
                    vm.snapshot()["breakpoint"], {"line": line, "path": None}
                )
                if name == "error":
                    with self.assertRaises(SericiteError) as caught:
                        vm.run()
                    self.assertEqual(caught.exception.kind, "raise_error")
                    self.assertEqual(vm.stdout(), "cleanup\n")
                    self.assertEqual(vm.snapshot()["state"], "error")
                else:
                    self.assertEqual(vm.run(), "cleanup\n")
                    self.assertEqual(vm.snapshot()["state"], "done")

    def test_one_line_statements_each_hit(self):
        vm = SericiteEngine().create_root("x = 1; x = 2; print(x)")
        vm.add_breakpoint(1)
        vm.run()
        self.assertEqual(vm.snapshot()["locals"], {"argv": []})
        vm.run()
        self.assertEqual(vm.snapshot()["locals"]["x"], 1)
        vm.run()
        self.assertEqual(vm.snapshot()["locals"]["x"], 2)
        self.assertEqual(vm.run(), "2\n")

    def test_pause_is_not_an_exception_and_does_not_run_finally(self):
        vm = SericiteEngine().create_root(
            "events = []\n"
            "try:\n"
            "    events.append('body')\n"
            "    raise 'boom'\n"
            "except ...:\n"
            "    events.append('except')\n"
            "finally:\n"
            "    events.append('finally')\n"
            "print(events)"
        )
        vm.add_breakpoint(4)
        vm.run()
        self.assertEqual(vm.snapshot()["state"], "paused")
        self.assertEqual(vm.snapshot()["locals"]["events"], ["body"])
        self.assertEqual(vm.run(), "['body', 'except', 'finally']\n")
        self.assertEqual(
            vm.snapshot()["locals"]["events"], ["body", "except", "finally"]
        )

    def test_waiting_input_and_breakpoint_remain_distinct(self):
        vm = SericiteEngine().create_root("x = input()\nprint(x)\ny = 2")
        vm.add_breakpoint(3)
        self.assertEqual(vm.run(), "")
        self.assertEqual(vm.snapshot()["state"], "waiting_input")
        self.assertIsNone(vm.snapshot()["breakpoint"])
        vm.feed_input("ok")
        self.assertEqual(vm.run(), "ok\n")
        self.assertEqual(vm.snapshot()["state"], "paused")
        vm.feed_input("unused")
        self.assertEqual(vm.snapshot()["state"], "paused")
        self.assertEqual(vm.run(), "ok\n")
        self.assertEqual(vm.snapshot()["state"], "done")

    def test_paused_lifecycle(self):
        vm = SericiteEngine().create_root("write_file('/x', 'a')\nx = 1")
        vm.add_breakpoint(2)
        vm.run()
        with self.assertRaises(SericiteError) as caught:
            vm.take_fs()
        self.assertEqual(caught.exception.kind, "runtime_error")
        vm.terminate()
        self.assertEqual(vm.snapshot()["state"], "terminated")
        self.assertIsNone(vm.snapshot()["breakpoint"])
        self.assertEqual(vm.take_fs().read_file("/x"), "a")

        disposable = SericiteEngine().create_root("x = 1")
        disposable.add_breakpoint(1)
        disposable.run()
        disposable.dispose()
        with self.assertRaises(SericiteError) as caught:
            disposable.snapshot()
        self.assertEqual(caught.exception.kind, "runtime_error")


class BreakpointSourceTests(unittest.TestCase):
    def make_root(self, source, files):
        engine = SericiteEngine()
        fs = engine.create_vfs()
        for path, text in files.items():
            fs.write_file(path, text)
        return engine, engine.create_root(source, fs=fs)

    def test_import_path_breakpoint_and_main_location_stay_separate(self):
        _, root = self.make_root(
            "import util\nprint('main')\n",
            {"/util.sericite": "value = 1\nprint(value)\n"},
        )
        root.add_breakpoint(2)
        root.add_breakpoint(1, path="util.sericite")
        root.run()
        snapshot = root.snapshot()
        self.assertEqual(snapshot["state"], "paused")
        self.assertEqual(snapshot["breakpoint"], {"line": 1, "path": "/util.sericite"})
        self.assertEqual(snapshot["stdout"], "")
        root.run()
        self.assertEqual(root.snapshot()["state"], "paused")
        self.assertEqual(root.snapshot()["breakpoint"], {"line": 2, "path": None})
        self.assertEqual(root.run(), "1\nmain\n")

    def test_entry_file_accepts_main_and_explicit_path(self):
        engine = SericiteEngine()
        fs = engine.create_vfs()
        fs.write_file("/pkg/main.sericite", "x = 1\nprint(x)")
        root = engine.create_root(fs=fs, entry_file="/pkg/main.sericite")
        root.add_breakpoint(2)
        root.add_breakpoint(2, "/pkg/main.sericite")
        root.run()
        self.assertEqual(root.snapshot()["breakpoint"], {"line": 2, "path": None})
        self.assertEqual(root.run(), "1\n")

    def test_exec_rebinds_main_but_not_old_functions(self):
        vm = SericiteEngine().create_root("def old():\n    x = 1\n    return x")
        vm.add_breakpoint(2)
        vm.run()
        self.assertEqual(vm.exec("value = old()\nprint(value)"), "")
        self.assertEqual(vm.snapshot()["state"], "paused")
        self.assertEqual(vm.snapshot()["locals"]["value"], 1)
        self.assertEqual(vm.run(), "1\n")
        vm.exec("new = 1\nnew += 1\nprint(new)")
        self.assertEqual(vm.snapshot()["state"], "paused")
        self.assertEqual(vm.snapshot()["locals"]["new"], 1)
        self.assertEqual(vm.run(), "1\n2\n")

    def test_failed_exec_preserves_paused_scene_and_binding(self):
        vm = SericiteEngine().create_root("x = 1\nx = 2")
        vm.add_breakpoint(2)
        vm.run()
        with self.assertRaises(SericiteError) as caught:
            vm.exec("def broken(:")
        self.assertEqual(caught.exception.kind, "syntax_error")
        self.assertEqual(vm.snapshot()["state"], "paused")
        self.assertEqual(vm.snapshot()["breakpoint"], {"line": 2, "path": None})
        self.assertEqual(vm.run(), "")
        self.assertEqual(vm.snapshot()["locals"]["x"], 2)

    def test_file_breakpoints_survive_exec_and_cached_module_functions(self):
        _, root = self.make_root(
            "import util\nprint(util.get())",
            {"/util.sericite": "def get():\n    value = 4\n    return value"},
        )
        root.add_breakpoint(2, "/util.sericite")
        root.run()
        self.assertEqual(root.snapshot()["state"], "paused")
        self.assertEqual(root.run(), "4\n")
        root.exec("print('reset')")
        self.assertEqual(root.snapshot()["state"], "done")
        root.exec("print(util.get())")
        self.assertEqual(root.snapshot()["state"], "paused")
        self.assertEqual(root.snapshot()["breakpoint"]["path"], "/util.sericite")
        self.assertEqual(root.run(), "4\nreset\n4\n")

    def test_foreign_granted_code_does_not_hit_target_breakpoints(self):
        root = SericiteEngine().create_root(
            "def shared():\n    value = 1\n    return value\n"
            'sub = VM("x = 1\\n\\nprint(shared())", functions={"shared": shared})\n'
            "sub.add_breakpoint(2)\n"
            "print(sub.run())\n"
        )
        self.assertEqual(root.run(), "1\n\n")

    def test_same_logical_path_in_foreign_vm_does_not_hit(self):
        engine = SericiteEngine()
        fs = engine.create_vfs()
        fs.write_file(
            "/main.sericite",
            "def f():\n"
            "    value = 1\n"
            "    return value\n"
            "child_fs = VFS()\n"
            "child_fs.write_file('/main.sericite', 'print(f())')\n"
            "sub = VM(entry_file='/main.sericite', fs=child_fs, functions={'f': f})\n"
            "sub.add_breakpoint(2, '/main.sericite')\n"
            "sub.run()\n"
            "print(sub.snapshot()['state'])",
        )
        root = engine.create_root(fs=fs, entry_file="/main.sericite")
        self.assertEqual(root.run(), "done\n")

    def test_output_writer_foreign_code_does_not_hit(self):
        root = SericiteEngine().create_root(
            "def writer(text):\n    value = 1\n    print(text, end='')\n"
            "sub = VM(\"print('child')\", output_writer=writer)\n"
            "sub.add_breakpoint(2)\n"
            "sub.run()\n"
            "print(sub.snapshot()['state'])\n"
        )
        self.assertEqual(root.run(), "child\ndone\n")

    def test_direct_pause_does_not_propagate(self):
        root = SericiteEngine().create_root(
            'sub = VM("x = 1\\nx = 2\\nprint(x)")\n'
            "sub.add_breakpoint(2)\n"
            "sub.run()\n"
            "print('parent', sub.snapshot()['state'], sub.snapshot()['locals']['x'])\n"
            "sub.run()\n"
            "print('root alive')\n"
        )
        self.assertEqual(root.run(), "parent paused 1\nroot alive\n")
        self.assertEqual(root.snapshot()["state"], "done")


class BreakpointAccountingTests(unittest.TestCase):
    def test_management_is_charged_to_caller_not_target(self):
        baseline_engine = SericiteEngine()
        baseline_engine.create_root('sub = VM("x = 1")').run()
        baseline = baseline_engine._contexts[1]

        engine = SericiteEngine()
        root = engine.create_root(
            'sub = VM("x = 1")\n'
            'sub.add_breakpoint(1, "/a/long/logical/path")\n'
            "sub.breakpoints()\n"
            "sub.remove_breakpoint(1, '/a/long/logical/path')\n"
        )
        root.run()
        target = engine._contexts[1]
        self.assertEqual(target.instruction_count, baseline.instruction_count)
        self.assertEqual(target.alloc_bytes, baseline.alloc_bytes)
        self.assertGreater(root.snapshot()["instruction_count"], 0)

    def test_path_work_scales_in_caller_account(self):
        def run_with_path(path):
            root = SericiteEngine().create_root(
                f'sub = VM("x = 1")\nsub.add_breakpoint(1, {path!r})'
            )
            root.run()
            return root.snapshot()["instruction_count"]

        short = run_with_path("/a")
        long_path = "/a/" + "segment/" * 20
        long = run_with_path(long_path)
        self.assertGreaterEqual(long - short, 2 * (len(long_path) - len("/a")))

    def test_host_management_does_not_charge_target(self):
        vm = SericiteEngine().create_root("x = 1")
        before = vm.snapshot()
        before_alloc = vm._context.alloc_bytes
        vm.add_breakpoint(1, "/path")
        vm.breakpoints()
        vm.remove_breakpoint(1, "/path")
        after = vm.snapshot()
        self.assertEqual(after["instruction_count"], before["instruction_count"])
        self.assertEqual(vm._context.alloc_bytes, before_alloc)


if __name__ == "__main__":
    unittest.main()
