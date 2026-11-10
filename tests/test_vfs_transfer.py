from __future__ import annotations

import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits


class VfsTransferTests(unittest.TestCase):
    def test_sequential_runs_move_workspace_and_refresh_imports(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "workspace = VFS()\n"
            "workspace.write_file('/util.sericite', 'value = 1\\n')\n"
            "workspace.write_file('/main.sericite', \"import util\\n"
            "write_file('/result.txt', str(util.value))\\nprint(util.value)\")\n"
            "run = VM(workspace.read_file('/main.sericite'), fs=workspace)\n"
            "print(run.run(), end='')\n"
            "workspace = run.take_fs()\n"
            "print(workspace.read_file('/result.txt'))\n"
            "workspace.write_file('/util.sericite', 'value = 2\\n')\n"
            "run2 = VM(workspace.read_file('/main.sericite'), fs=workspace)\n"
            "print(run2.run(), end='')\n"
            "workspace = run2.take_fs()\n"
            "print(workspace.read_file('/result.txt'))\n"
        )
        self.assertEqual(root.run(), "1\n1\n2\n2\n")

    def test_attach_consumes_handle_permanently(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "fs = VFS()\n"
            "fs.write_file('/x', 'value')\n"
            "run = VM('', fs=fs)\n"
            "returned = run.take_fs()\n"
            "try:\n"
            "    fs.read_file('/x')\n"
            "except runtime_error as e:\n"
            "    print(e.message)\n"
            "print(returned.read_file('/x'))\n"
        )
        self.assertEqual(root.run(), "VFS handle has been consumed\nvalue\n")

    def test_failed_attach_leaves_workspace_detached_and_usable(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "fs = VFS()\n"
            "fs.write_file('/x', 'safe')\n"
            "try:\n"
            "    run = VM('def broken(:', fs=fs)\n"
            "except syntax_error:\n"
            "    print('compile failed')\n"
            "print(fs.read_file('/x'))\n"
            "run = VM('', fs=fs)\n"
            "print(run.snapshot()['state'])\n"
        )
        self.assertEqual(root.run(), "compile failed\nsafe\ndone\n")

    def test_take_requires_terminal_state_and_supports_abandoning_input(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "ready = VM('x = 1')\n"
            "try:\n"
            "    ready.take_fs()\n"
            "except runtime_error:\n"
            "    print('not terminal')\n"
            'waiting = VM("input()")\n'
            "waiting.run()\n"
            "try:\n"
            "    waiting.take_fs()\n"
            "except runtime_error:\n"
            "    print('waiting')\n"
            "waiting.terminate()\n"
            "fs = waiting.take_fs()\n"
            "print(fs.path_exists('/'))\n"
        )
        self.assertEqual(root.run(), "not terminal\nwaiting\nTrue\n")

    def test_detached_vm_keeps_diagnostics_but_loses_file_and_exec_access(self):
        engine = SericiteEngine()
        fs = engine.create_vfs()
        fs.write_file("/x", "value")
        vm = engine.create_root("print(read_file('/x'))", fs=fs)
        self.assertEqual(vm.run(), "value\n")
        returned = vm.take_fs()
        self.assertEqual(returned.read_file("/x"), "value")
        self.assertEqual(vm.snapshot()["state"], "done")
        self.assertEqual(vm.stdout(), "value\n")
        for operation in (
            lambda: vm.read_file("/x"),
            lambda: vm.exec("print('new')"),
        ):
            with (
                self.subTest(operation=operation),
                self.assertRaises(SericiteError) as ctx,
            ):
                operation()
            self.assertEqual(ctx.exception.kind, "runtime_error")
        vm.dispose()

    def test_old_home_function_cannot_reach_transferred_vfs(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "saved = []\n"
            "def capture(fn):\n"
            "    saved.append(fn)\n"
            "fs = VFS()\n"
            "fs.write_file('/secret', 'home')\n"
            'run = VM("def read_secret():\\n'
            "    return read_file('/secret')\\n"
            "capture(read_secret)\", fs=fs, functions={'capture': capture})\n"
            "run.run()\n"
            "fs = run.take_fs()\n"
            "try:\n"
            "    saved[0]()\n"
            "except runtime_error:\n"
            "    print('home revoked')\n"
        )
        self.assertEqual(root.run(), "home revoked\n")

    def test_tighter_vm_can_shrink_but_not_grow_transferred_world(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "fs = VFS()\n"
            "fs.write_file('/a', 'a')\n"
            "fs.write_file('/b', 'b')\n"
            "run = VM(\"print(read_file('/a'))\\n"
            "try:\\n"
            "    write_file('/c', 'c')\\n"
            "except file_limit_error:\\n"
            "    print('limited')\\n"
            "delete_file('/b')\\n"
            "write_file('/c', 'c')\", fs=fs, max_fs_files=2)\n"
            "print(run.run(), end='')\n"
            "fs = run.take_fs()\n"
            "print(fs.list_dir('/'))\n"
        )
        self.assertEqual(root.run(), "a\nlimited\n['a', 'c']\n")

    def test_vfs_value_is_safe_and_cannot_cross_ffi(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "fs = VFS()\nprint(fs)\n",
            functions={"echo": lambda value: value},
        )
        self.assertEqual(root.run(), "<VFS>\n")
        self.assertEqual(root.snapshot()["locals"]["fs"], "<VFS>")
        with self.assertRaises(SericiteError) as ctx:
            root.exec("echo(fs)")
        self.assertEqual(ctx.exception.kind, "ffi_error")

    def test_detached_list_dir_enforces_result_list_limit(self):
        engine = SericiteEngine(SericiteLimits(max_list_size=1))
        root = engine.create_root(
            "fs = VFS()\n"
            "fs.write_file('/a', '')\n"
            "fs.write_file('/b', '')\n"
            "result = fs.list_dir('/')\n"
        )
        with self.assertRaises(SericiteError) as ctx:
            root.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(root.snapshot()["state"], "resource_exhausted")

    def test_vfs_mutation_has_no_post_commit_allocation_failure(self):
        source = "fs = VFS()\nfs.write_file('/a', 'x')\n"

        def attempt(limit):
            engine = SericiteEngine(SericiteLimits(max_total_bytes=limit))
            try:
                root = engine.create_root(source)
            except SericiteError:
                return None, None
            try:
                root.run()
            except SericiteError as error:
                return root, error
            return root, None

        success_limit = None
        for limit in range(256):
            root, error = attempt(limit)
            if root is not None and error is None:
                success_limit = limit
                break
        self.assertIsNotNone(success_limit)
        failure = None
        for limit in range(success_limit - 1, -1, -1):
            root, error = attempt(limit)
            if root is not None and error is not None:
                failure = (root, error)
                break
        self.assertIsNotNone(failure)
        root, error = failure
        self.assertEqual(error.kind, "resource_exhausted")
        fs = root._engine._context(root).frames[0].locals["fs"]
        self.assertFalse(fs.path_exists("/a"))

    def test_detached_list_dir_rejects_invalid_call_signatures(self):
        calls = (
            'fs.list_dir("/", "ignored")',
            'fs.list_dir(path="/", ignored=1)',
            'fs.list_dir("/", path="/ignored")',
        )
        for call in calls:
            with self.subTest(call=call):
                engine = SericiteEngine()
                root = engine.create_root(
                    "fs = VFS()\n"
                    "fs.write_file('/a', '')\n"
                    "try:\n"
                    f"    {call}\n"
                    "except type_error:\n"
                    "    print('type_error')\n"
                )
                self.assertEqual(root.run(), "type_error\n")

    def test_vm_handle_does_not_grant_script_file_access(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "sub = VM('')\n"
            "try:\n"
            "    sub.read_file('/x')\n"
            "except attribute_error as e:\n"
            "    print(e.kind)\n"
        )
        self.assertEqual(root.run(), "attribute_error\n")

    def test_take_fs_allocation_failure_preserves_attachment(self):
        checkpoints = []
        source = "sub = VM(\"write_file('/x', 'safe')\")\nsub.run()\ncheckpoint()\nfs = sub.take_fs()\n"
        probe = SericiteEngine()
        probe.create_root(
            source,
            functions={
                "checkpoint": lambda: checkpoints.append(probe._contexts[0].alloc_bytes)
            },
        ).run()
        engine = SericiteEngine(SericiteLimits(max_total_bytes=checkpoints[0] + 4))
        root = engine.create_root(source, functions={"checkpoint": lambda: None})
        with self.assertRaises(SericiteError) as ctx:
            root.run()
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        sub = engine._context(root).frames[0].locals["sub"]
        self.assertEqual(sub.read_file("/x"), "safe")

    def test_fs_option_rejects_non_vfs_values(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as ctx:
            engine.create_root("", fs=object())
        self.assertEqual(ctx.exception.kind, "type_error")
        root = engine.create_root(
            "try:\n    sub = VM('', fs=1)\nexcept type_error:\n    print('rejected')\n"
        )
        self.assertEqual(root.run(), "rejected\n")

    def test_host_create_attach_take_and_cross_engine_rejection(self):
        first = SericiteEngine()
        second = SericiteEngine()
        fs = first.create_vfs()
        fs.write_file("/x", "host")
        with self.assertRaises(SericiteError) as ctx:
            second.create_root("", fs=fs)
        self.assertEqual(ctx.exception.kind, "internal_error")
        vm = first.create_root("print(read_file('/x'))", fs=fs)
        self.assertEqual(vm.run(), "host\n")
        returned = vm.take_fs()
        self.assertEqual(returned.read_file("/x"), "host")


if __name__ == "__main__":
    unittest.main()
