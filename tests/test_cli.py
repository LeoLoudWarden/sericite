import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from sericite import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class CliTests(unittest.TestCase):
    def run_cli(self, *args: object, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "sericite", *(str(arg) for arg in args)],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            check=False,
        )

    def write(self, directory: Path, name: str, text: str) -> Path:
        path = directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_root_example(self):
        result = self.run_cli(
            PROJECT_ROOT / "examples" / "root.sericite", stdin="2\n3\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "23\n")

    def test_sub_vm_example(self):
        result = self.run_cli(PROJECT_ROOT / "examples" / "sub_vm.sericite")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "23\n\n")

    def test_debug_sub_vm_example(self):
        result = self.run_cli(PROJECT_ROOT / "examples" / "debug_sub_vm.sericite")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'state': 'done'", result.stdout)
        self.assertTrue(result.stdout.endswith("23\n\n"))

    def test_missing_input_is_error(self):
        result = self.run_cli(PROJECT_ROOT / "examples" / "root.sericite")
        self.assertEqual(result.returncode, 1)
        self.assertIn("input_error", result.stderr)

    def test_help_and_version(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                result = self.run_cli(flag)
                self.assertEqual(result.returncode, 0)
                self.assertIn("--capabilities", result.stdout)
                self.assertIn("--include", result.stdout)
                self.assertIn("--command", result.stdout)
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"sericite {__version__}\n")

    def test_script_argv_for_file_command_and_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self.write(Path(tmp), "args.sericite", "print(argv)\n")
            result = self.run_cli(script, "first", "", "--flag", "世界")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                f"['{script}', 'first', '', '--flag', '世界']\n",
            )

        result = self.run_cli("-c", "print(argv)", "first", "--flag", "世界")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-c', 'first', '--flag', '世界']\n")

        result = self.run_cli("-", "argument", stdin="print(argv)\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-', 'argument']\n")

        result = self.run_cli("-c", "print(argv)", "--", "--include", "literal")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-c', '--include', 'literal']\n")

        result = self.run_cli("-c", "print(argv)", "--version", "--include")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-c', '--version', '--include']\n")

        result = self.run_cli("--unknown")
        self.assertEqual(result.returncode, 2)

    def test_repl_echoes_expressions_and_preserves_state(self):
        result = self.run_cli(stdin='x = 40\nx + 2\n"hello"\n["x", 1]\nNone\nargv\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout,
            ">>> >>> 42\n>>> 'hello'\n>>> ['x', 1]\n>>> >>> []\n>>> ",
        )

    def test_repl_does_not_echo_none_from_print(self):
        result = self.run_cli(stdin="x = 1\nprint(x)\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, ">>> >>> 1\n>>> ")

    def test_repl_script_input_shares_stdin_with_the_session(self):
        result = self.run_cli(stdin="name = input()\nworld\nname\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, ">>> >>> 'world'\n>>> ")

    def test_repl_supports_multiline_definitions_schemas_and_vfs(self):
        result = self.run_cli(
            stdin=(
                "def inc(value):\n"
                "    return value + 1\n"
                "\n"
                "class Point:\n"
                "    x: int\n"
                "\n"
                "p = Point(4)\n"
                "p.x = inc(p.x)\n"
                'write_file("/value.txt", str(p.x))\n'
                'read_file("/value.txt")\n'
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("... ", result.stdout)
        self.assertTrue(result.stdout.endswith("'5'\n>>> "))

    def test_repl_multiline_function_body_executes_as_one_unit(self):
        result = self.run_cli(
            stdin=("def g(n):\n    a = n + 1\n    return a * 2\n\ng(3)\n")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("unexpected indent", result.stdout)
        self.assertEqual(result.stdout, ">>> ... ... ... >>> 8\n>>> ")

    def test_repl_recovers_from_compile_and_runtime_errors(self):
        result = self.run_cli(stdin="x = 9\ndef broken(:\nx\n(\n1 / 0\n)\nx\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, ">>> >>> >>> 9\n>>> ... ... >>> 9\n>>> ")
        self.assertIn("syntax_error", result.stderr)
        self.assertIn("<stdin>:2: zero_division", result.stderr)

    def test_repl_traceback_preserves_function_delivery_lines(self):
        result = self.run_cli(stdin="def f():\n    x = 1\n    return 1 / 0\n\nf()\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr,
            "<stdin>:3: zero_division: division by zero\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 1, in <module>\n'
            '  File "<stdin>", line 3, in f\n',
        )

    def test_repl_multiline_expression_offsets_only_its_own_frames(self):
        result = self.run_cli(stdin="def f():\n    return 1 / 0\n\n(\nf()\n)\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr,
            "<stdin>:2: zero_division: division by zero\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 2, in <module>\n'
            '  File "<stdin>", line 2, in f\n',
        )

    def test_repl_compile_failure_does_not_desynchronize_source_ids(self):
        result = self.run_cli(
            stdin="def f():\n    return 1 / 0\n\nimport os\n(\nf()\n)\n"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("syntax_error", result.stderr)
        self.assertIn(
            "<stdin>:2: zero_division: division by zero\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 2, in <module>\n'
            '  File "<stdin>", line 2, in f\n',
            result.stderr,
        )

    def test_repl_traceback_maps_include_function_to_include_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            include = self.write(
                Path(tmp), "bad_rt.sericite", "def g():\n    return 1 / 0\n"
            )
            result = self.run_cli("--include", include, stdin="g()\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr,
            f"{include}:2: zero_division: division by zero\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 1, in <module>\n'
            f'  File "{include}", line 2, in g\n',
        )

    def test_repl_current_multiline_expression_keeps_its_own_location(self):
        result = self.run_cli(stdin="(\n1 / 0\n)\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr,
            "<stdin>:2: zero_division: division by zero\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 2, in <module>\n',
        )

    def test_repl_input_required_uses_waiting_function_delivery(self):
        result = self.run_cli(
            stdin=(
                "def f():\n    x = 1\n    value = input()\n    return value\n\nf()\n"
            )
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "<stdin>:3: input_error: input required\n")

    def test_cli_maps_foreign_frames_to_unknown_source(self):
        from sericite import SericiteEngine, SericiteError
        from sericite.cli import _CombinedSource, _format_error

        engine = SericiteEngine()
        root = engine.create_root("public()\n")
        donor = engine.create_root("def secret():\n    return missing\n")
        donor.run()
        engine._contexts[0].granted["public"] = (
            engine._contexts[1].frames[0].locals["secret"]
        )
        with self.assertRaises(SericiteError) as ctx:
            root.run()
        self.assertEqual(ctx.exception._frame_sources, (0, None))
        source = _CombinedSource([("<stdin>", "public()")])
        self.assertEqual(
            _format_error(ctx.exception, source, source_map={0: (source, 0)}),
            "<sericite>: name_error: name is not defined\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 1, in <module>\n'
            '  File "<sericite>", line ?, in function',
        )

    def test_error_mapping_uses_unknown_location_for_missing_source(self):
        from sericite import SericiteEngine, SericiteError
        from sericite.cli import _CombinedSource, _format_error

        vm = SericiteEngine().create_root("1 / 0\n")
        with self.assertRaises(SericiteError) as ctx:
            vm.run()
        formatted = _format_error(
            ctx.exception,
            _CombinedSource([("<stdin>", "1 / 0")]),
            source_map={},
        )
        self.assertEqual(
            formatted,
            "<sericite>: zero_division: division by zero\n"
            "Traceback (most recent call last):\n"
            '  File "<sericite>", line ?, in <module>',
        )

    def test_repl_source_map_releases_previous_delivery_text(self):
        import gc
        import weakref

        from sericite.cli import _CombinedSource, _ReplSourceMap

        sources = _ReplSourceMap(_CombinedSource([]))
        previous = _CombinedSource([("<stdin>", "def f():\n    return 1 / 0")])
        previous_ref = weakref.ref(previous)
        sources.add(previous, 0)
        sources.add(_CombinedSource([("<stdin>", "f()")]), 1)
        del previous
        gc.collect()
        self.assertIsNone(previous_ref())
        historical = sources.get(1)
        self.assertIsNotNone(historical)
        source, offset = historical
        self.assertEqual(offset, 0)
        self.assertEqual(source.location(2), ("<stdin>", 2))

    def test_repl_uses_include_capabilities_files_and_empty_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            include = self.write(directory, "base.sericite", "x = 41\n")
            capabilities = self.write(
                directory,
                "caps.py",
                "def configure():\n"
                "    return {\n"
                "        'functions': {'double': lambda x: x * 2},\n"
                "        'files': {'/message.txt': 'from vfs'},\n"
                "    }\n",
            )
            result = self.run_cli(
                "--include",
                include,
                "--capabilities",
                capabilities,
                stdin=('print(double(x + 1))\nread_file("/message.txt")\nargv\n'),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout,
            ">>> 84\n>>> 'from vfs'\n>>> []\n>>> ",
        )

    def test_repl_include_startup_failure_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            invalid = self.write(
                Path(tmp), "invalid.sericite", "if True print('bad')\n"
            )
            result = self.run_cli("--include", invalid)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("syntax_error", result.stderr)

    def test_command_and_stdin_source(self):
        result = self.run_cli(
            "-c", 'name = input()\nprint("hello", name)', stdin="world\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "hello world\n")
        result = self.run_cli("-", stdin='print("from stdin")\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from stdin\n")

    def test_includes_share_scope_in_order_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            initial = self.write(directory, "initial.sericite", "order = []\n")
            first = self.write(
                directory, "first.sericite", 'order.append("first")\nvalue = 20\n'
            )
            second = self.write(
                directory,
                "second.sericite",
                'order.append("second")\ndef double(x):\n    return x * 2\n',
            )
            result = self.run_cli(
                "--include",
                initial,
                "--include",
                first,
                "--include",
                second,
                "--include",
                first,
                "-c",
                'order.append("main")\nprint(order)\nprint(double(value))',
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "['first', 'second', 'first', 'main']\n40\n",
        )

    def test_include_error_locations_and_atomic_compilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runtime = self.write(
                directory, "runtime.sericite", 'print("included")\n1 / 0\n'
            )
            result = self.run_cli("--include", runtime, "-c", "pass")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "included\n")
            self.assertIn(f"{runtime}:2: zero_division", result.stderr)

            invalid = self.write(
                directory, "invalid.sericite", "if True print('bad')\n"
            )
            result = self.run_cli(
                "--include", runtime, "--include", invalid, "-c", "pass"
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn(f"{invalid}:1:", result.stderr)
            self.assertIn("syntax_error", result.stderr)

            main = self.write(directory, "main.sericite", "print(missing)\n")
            result = self.run_cli(main)
            self.assertIn(f"{main}:1: name_error", result.stderr)

    def test_traceback_maps_each_frame_to_its_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write(
                Path(tmp),
                "runtime.sericite",
                "def inner():\n"
                "    return missing\n\n"
                "def outer():\n"
                "    return inner()\n",
            )
            result = self.run_cli("--include", runtime, "-c", "outer()")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            f"{runtime}:2: name_error: name 'missing' is not defined\n"
            "Traceback (most recent call last):\n"
            '  File "<command>", line 1, in <module>\n'
            f'  File "{runtime}", line 5, in outer\n'
            f'  File "{runtime}", line 2, in inner\n',
        )

    def test_capabilities_functions_limits_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            capabilities = self.write(
                directory,
                "caps.py",
                "from sericite import SericiteLimits\n"
                "def configure():\n"
                "    return {\n"
                "        'functions': {'double': lambda x: x * 2},\n"
                "        'limits': SericiteLimits(max_instructions=100000),\n"
                "        'files': {'/message.txt': 'from vfs'},\n"
                "    }\n",
            )
            result = self.run_cli(
                "--capabilities",
                capabilities,
                "-c",
                'print(double(21))\nprint(read_file("/message.txt"))',
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "42\nfrom vfs\n")
            result = self.run_cli("-c", "print(double(21))")
            self.assertEqual(result.returncode, 1)
            self.assertIn("name_error", result.stderr)

            limited = self.write(
                directory,
                "limited.py",
                "from sericite import SericiteLimits\n"
                "def configure():\n"
                "    return {'limits': SericiteLimits(max_instructions=1)}\n",
            )
            result = self.run_cli(
                "--capabilities", limited, "-c", "while True:\n    pass"
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("resource_exhausted", result.stderr)

    def test_capabilities_support_long_running_root_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            capabilities = self.write(
                directory,
                "unlimited.py",
                "from sericite import SericiteLimits\n"
                "def configure():\n"
                "    return {'limits': SericiteLimits(\n"
                "        max_instructions=-1,\n"
                "        max_output_bytes=-1,\n"
                "        max_total_bytes=-1,\n"
                "        max_child_vms=-1,\n"
                "        max_total_vms=-1,\n"
                "    )}\n",
            )
            result = self.run_cli(
                "--capabilities",
                capabilities,
                "-c",
                "i = 0\n"
                "while i < 20:\n"
                "    i += 1\n"
                "print(i)\n"
                'sub = VM("")\n'
                'sub.exec("x = 41")\n'
                'text = sub.exec("print(x + 1)")\n'
                'print(text, end="")\n'
                "sub.dispose()\n"
                'print("done")',
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "20\n42\ndone\n")

    def test_invalid_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            cases = {
                "missing.py": "value = 1\n",
                "return.py": "def configure():\n    return []\n",
                "unknown.py": "def configure():\n    return {'function': {}}\n",
                "limits.py": "def configure():\n    return {'limits': {}}\n",
                "functions.py": "def configure():\n    return {'functions': {'f': 1}}\n",
                "files.py": "def configure():\n    return {'files': {'/x': 1}}\n",
                "raises.py": "def configure():\n    raise ValueError('bad config')\n",
            }
            for name, text in cases.items():
                with self.subTest(name=name):
                    path = self.write(directory, name, text)
                    result = self.run_cli("--capabilities", path, "-c", "pass")
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("capabilities", result.stderr)
                    self.assertEqual(result.stdout, "")
            result = self.run_cli(
                "--capabilities", directory / "absent.py", "-c", "pass"
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("capabilities", result.stderr)

    def test_host_exception_contract_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            capabilities = self.write(
                directory,
                "caps.py",
                "def fail():\n    raise ValueError('host secret')\n"
                "def configure():\n"
                "    return {'functions': {'fail': fail}}\n",
            )
            result = self.run_cli(
                "--capabilities",
                capabilities,
                "-c",
                "try:\n    fail()\nexcept:\n    print('caught')",
            )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("caught", result.stdout)
        self.assertIn("host_error", result.stderr)


class CliStreamingTests(unittest.TestCase):
    def test_stdout_arrives_before_program_exits(self):
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sericite",
                "-c",
                'print("first", end="")\ninput()\nprint("second")',
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=PROJECT_ROOT,
        )
        try:
            first = queue.Queue()
            reader = threading.Thread(
                target=lambda: first.put(process.stdout.read(5)), daemon=True
            )
            reader.start()
            self.assertEqual(first.get(timeout=5), "first")
            remaining, errors = process.communicate("continue\n", timeout=10)
            self.assertEqual(process.returncode, 0, errors)
            self.assertEqual(remaining, "second\n")
        except Exception:
            process.kill()
            process.communicate()
            raise
        finally:
            reader.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
