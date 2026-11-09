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
    def run_cli(
        self, *args: object, stdin: str = "", cwd: Path = PROJECT_ROOT
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "sericite",
                *(str(arg) for arg in args),
            ],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            timeout=30,
            check=False,
        )

    def write(self, directory: Path, name: str, text: str) -> Path:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
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
        self.assertIn("Traceback (most recent call last):", result.stderr)

    def test_stdin_eof_is_catchable_and_supports_read_until_eof(self):
        result = self.run_cli(
            "-c",
            "lines = []\n"
            "while True:\n"
            "    try:\n"
            "        lines.append(input())\n"
            "    except input_error:\n"
            "        break\n"
            "print(lines)",
            stdin="a\nb\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['a', 'b']\n")
        self.assertEqual(result.stderr, "")

    def test_blank_line_and_stdin_source_eof_are_distinct(self):
        result = self.run_cli("-c", "print(repr(input()))", stdin="\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "''\n")

        result = self.run_cli(
            "-",
            stdin=("try:\n    input()\nexcept input_error as e:\n    print(e.kind)\n"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "input_error\n")

    def test_repl_uncaught_stdin_eof_prints_error_and_continues(self):
        result = self.run_cli(stdin="input()\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, ">>> >>> ")
        self.assertEqual(
            result.stderr,
            "<stdin>:1: input_error: input required\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 1, in <module>\n',
        )

    def test_writer_input_at_eof_is_an_error_not_a_suspension(self):
        result = self.run_cli(
            "-c",
            "def writer(text):\n"
            "    input()\n"
            'sub = VM("print(1)", output_writer=writer)\n'
            "try:\n"
            "    sub.run()\n"
            "except input_error:\n"
            '    print("writer input_error")',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "writer input_error\n")

    def test_help_and_version(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                result = self.run_cli(flag)
                self.assertEqual(result.returncode, 0)
                self.assertIn("--capabilities", result.stdout)
                self.assertNotIn("--include", result.stdout)
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
                f"{[str(script), 'first', '', '--flag', '世界']!r}\n",
            )

            result = self.run_cli(script, "--", "a")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f"{[str(script), '--', 'a']!r}\n")

            result = self.run_cli("--", script, "a")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f"{[str(script), 'a']!r}\n")

        result = self.run_cli("-c", "print(argv)", "first", "--flag", "世界")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-c', 'first', '--flag', '世界']\n")

        result = self.run_cli("-c", "print(argv)", "--", "a")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-c', '--', 'a']\n")

        result = self.run_cli("--command=print(argv)", "--", "--flag")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-c', '--', '--flag']\n")

        result = self.run_cli("-", "argument", stdin="print(argv)\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-', 'argument']\n")

        result = self.run_cli("-", "--", "a", stdin="print(argv)\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-', '--', 'a']\n")

        result = self.run_cli("-c", "print(argv)", "--version", "--include")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['-c', '--version', '--include']\n")

        result = self.run_cli("--unknown")
        self.assertEqual(result.returncode, 2)

    def test_utf8_bom_is_accepted_for_file_import_and_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            main = self.write(
                directory, "main.sericite", "\ufeffimport base\nprint(base.value)\n"
            )
            self.write(directory, "base.sericite", "\ufeffvalue = 42\n")
            result = self.run_cli(main)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "42\n")

        result = self.run_cli("-", stdin='\ufeffprint("stdin")\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "stdin\n")

    def test_utf8_bom_preserves_positions_and_other_decoding_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            invalid = self.write(
                directory, "invalid.sericite", '\ufeffif True print("bad")\n'
            )
            result = self.run_cli(invalid)
            self.assertEqual(result.returncode, 1)
            self.assertIn(f"{invalid}:1:9: syntax_error", result.stderr)

            main = self.write(directory, "main.sericite", "import runtime\n")
            self.write(directory, "runtime.sericite", "\ufeff\n1 / 0\n")
            result = self.run_cli(main)
            self.assertEqual(result.returncode, 1)
            self.assertIn("/runtime.sericite:2: zero_division", result.stderr)

            double_bom = self.write(
                directory, "double.sericite", '\ufeff\ufeffprint("bad")\n'
            )
            result = self.run_cli(double_bom)
            self.assertEqual(result.returncode, 1)
            self.assertIn("invalid non-printable character U+FEFF", result.stderr)

            undecodable = directory / "undecodable.sericite"
            undecodable.write_bytes(b"\xff")
            result = self.run_cli(undecodable)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unable to read source", result.stderr)
            self.assertNotIn("internal_error", result.stderr)

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
        result = self.run_cli(stdin="def f():\n    return 1 / 0\n\ndel x\n(\nf()\n)\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("syntax_error", result.stderr)
        self.assertIn(
            "<stdin>:2: zero_division: division by zero\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 2, in <module>\n'
            '  File "<stdin>", line 2, in f\n',
            result.stderr,
        )

    def test_repl_traceback_maps_imported_function_to_vfs_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            capabilities = self.write(
                directory,
                "caps.py",
                "def configure():\n"
                "    return {'files': {'/bad_rt.sericite': "
                "'def g():\\n    return 1 / 0\\n'}}\n",
            )
            result = self.run_cli(
                "--capabilities", capabilities, stdin="from bad_rt import g\ng()\n"
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr,
            "/bad_rt.sericite:2: zero_division: division by zero\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 1, in <module>\n'
            '  File "/bad_rt.sericite", line 2, in g\n',
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

    def test_repl_input_error_uses_input_function_delivery(self):
        result = self.run_cli(
            stdin=(
                "def f():\n    x = 1\n    value = input()\n    return value\n\nf()\n"
            )
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr,
            "<stdin>:3: input_error: input required\n"
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 1, in <module>\n'
            '  File "<stdin>", line 3, in f\n',
        )

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

    def test_repl_uses_import_capabilities_files_and_empty_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            capabilities = self.write(
                directory,
                "caps.py",
                "def configure():\n"
                "    return {\n"
                "        'functions': {'double': lambda x: x * 2},\n"
                "        'files': {'/base.sericite': 'x = 41\\n', "
                "'/message.txt': 'from vfs'},\n"
                "    }\n",
            )
            result = self.run_cli(
                "--capabilities",
                capabilities,
                stdin=(
                    "import base\n"
                    "print(double(base.x + 1))\n"
                    'read_file("/message.txt")\nargv\n'
                ),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout,
            ">>> >>> 84\n>>> 'from vfs'\n>>> []\n>>> ",
        )

    def test_repl_import_syntax_failure_is_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            capabilities = self.write(
                Path(tmp),
                "caps.py",
                "def configure():\n"
                "    return {'files': {'/invalid.sericite': "
                "'if True print(\"bad\")\\n'}}\n",
            )
            result = self.run_cli(
                "--capabilities", capabilities, stdin="import invalid\nprint('alive')\n"
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, ">>> >>> alive\n>>> ")
        self.assertIn("/invalid.sericite:1:9: syntax_error", result.stderr)

    def test_command_and_stdin_source(self):
        result = self.run_cli(
            "-c", 'name = input()\nprint("hello", name)', stdin="world\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "hello world\n")
        result = self.run_cli("-", stdin='print("from stdin")\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from stdin\n")

    def test_project_imports_have_namespaces_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(
                directory,
                "util.sericite",
                "order = []\nvalue = 20\ndef double(x):\n    return x * 2\n",
            )
            self.write(
                directory,
                "first.sericite",
                "import util\nutil.order.append('first')\n",
            )
            self.write(
                directory,
                "second.sericite",
                "import util\nutil.order.append('second')\n",
            )
            main = self.write(
                directory,
                "main.sericite",
                "import first\nimport second\nimport first\nimport util\n"
                "util.order.append('main')\n"
                "print(util.order)\nprint(util.double(util.value))\n",
            )
            result = self.run_cli(main)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "['first', 'second', 'main']\n40\n")

    def test_project_packages_and_relative_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, "pkg/__init__.sericite", "from . import base\n")
            self.write(directory, "pkg/base.sericite", "value = 40\n")
            self.write(
                directory,
                "pkg/mod.sericite",
                "from .base import value\nresult = value + 2\n",
            )
            main = self.write(
                directory,
                "main.sericite",
                "from pkg.mod import result\nprint(result)\n",
            )
            result = self.run_cli(main)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "42\n")

    def test_project_copies_only_reachable_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, "util.sericite", "value = 1\n")
            self.write(directory, "unrelated.sericite", "value = 'secret'\n")
            self.write(directory, "note.txt", "not copied\n")
            main = self.write(
                directory,
                "main.sericite",
                "import util\n"
                "print(path_exists('/main.sericite'), path_exists('/util.sericite'))\n"
                "print(path_exists('/unrelated.sericite'), path_exists('/note.txt'))\n",
            )
            result = self.run_cli(main)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "True True\nFalse False\n")

    def test_command_does_not_implicitly_load_cwd_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, "util.sericite", "value = 1\n")
            result = self.run_cli("-c", "import util", cwd=directory)
        self.assertEqual(result.returncode, 1)
        self.assertIn("import_error", result.stderr)

    def test_capabilities_files_override_project_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, "util.sericite", "value = 1\n")
            main = self.write(
                directory, "main.sericite", "import util\nprint(util.value)\n"
            )
            capabilities = self.write(
                directory,
                "caps.py",
                "def configure():\n"
                "    return {'files': {'/util.sericite': 'value = 2\\n'}}\n",
            )
            result = self.run_cli("--capabilities", capabilities, main)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2\n")

    def test_project_import_symlink_cannot_escape_entry_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            outside = self.write(directory, "outside.sericite", "value = 1\n")
            project = directory / "project"
            project.mkdir()
            try:
                (project / "util.sericite").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            main = self.write(project, "main.sericite", "import util\n")
            result = self.run_cli(main)
        self.assertEqual(result.returncode, 1)
        self.assertIn("import_error", result.stderr)

    def test_deep_inactive_dependency_chain_uses_iterative_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for index in range(300):
                text = (
                    f"if False:\n    import m{index - 1:03d}\n"
                    if index
                    else "value = 0\n"
                )
                if index == 299:
                    text += "print('alive')\n"
                self.write(directory, f"m{index:03d}.sericite", text)
            result = self.run_cli(directory / "m299.sericite")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "alive\n")
        self.assertNotIn("RecursionError", result.stderr)

    def test_deep_executed_dependency_chain_fails_at_vm_frame_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for index in range(140):
                text = f"import m{index + 1:03d}\n" if index < 139 else "value = 1\n"
                self.write(directory, f"m{index:03d}.sericite", text)
            result = self.run_cli(directory / "m000.sericite")
        self.assertEqual(result.returncode, 1)
        self.assertIn("resource_exhausted", result.stderr)
        self.assertIn("call depth limit exceeded", result.stderr)
        self.assertNotIn("RecursionError", result.stderr)
        self.assertNotIn("_project.py", result.stderr)

    def test_project_snapshot_precedes_capabilities_configure(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, "util.sericite", "value = 1\n")
            main = self.write(
                directory, "main.sericite", "import util\nprint(util.value)\n"
            )
            capabilities = self.write(
                directory,
                "caps.py",
                "from pathlib import Path\n"
                "def configure():\n"
                "    Path(__file__).with_name('util.sericite').write_text("
                "'value = 2\\n', encoding='utf-8')\n"
                "    return {}\n",
            )
            result = self.run_cli("--capabilities", capabilities, main)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "1\n")

    def test_include_option_is_removed(self):
        result = self.run_cli("--include", "base.sericite")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: --include", result.stderr)

    def test_import_errors_are_lazy_and_use_vfs_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, "runtime.sericite", "print('imported')\n1 / 0\n")
            main = self.write(directory, "main.sericite", "import runtime\n")
            result = self.run_cli(main)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "imported\n")
            self.assertIn("/runtime.sericite:2: zero_division", result.stderr)

            self.write(directory, "invalid.sericite", "if True print('bad')\n")
            main = self.write(
                directory,
                "main.sericite",
                "if False:\n    import invalid\nprint('main')\n",
            )
            result = self.run_cli(main)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "main\n")

            main = self.write(directory, "main.sericite", "import invalid\n")
            result = self.run_cli(main)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn("/invalid.sericite:1:", result.stderr)
            self.assertIn("syntax_error", result.stderr)

            main = self.write(directory, "main.sericite", "print(missing)\n")
            result = self.run_cli(main)
            self.assertIn(f"{main}:1: name_error", result.stderr)

    def test_traceback_maps_each_frame_to_its_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(
                directory,
                "runtime.sericite",
                "def inner():\n"
                "    return missing\n\n"
                "def outer():\n"
                "    return inner()\n",
            )
            main = self.write(
                directory, "main.sericite", "from runtime import outer\nouter()\n"
            )
            result = self.run_cli(main)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "/runtime.sericite:2: name_error: name 'missing' is not defined\n"
            "Traceback (most recent call last):\n"
            f'  File "{main}", line 2, in <module>\n'
            '  File "/runtime.sericite", line 5, in outer\n'
            '  File "/runtime.sericite", line 2, in inner\n',
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
                "-X",
                "utf8",
                "-m",
                "sericite",
                "-c",
                'print("first", end="")\ninput()\nprint("second")',
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
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

    def test_closed_stdout_pipe_exits_quietly(self):
        process = subprocess.Popen(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "sericite",
                "-c",
                "for i in range(1000):\n    print(i)",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
        )
        try:
            process.stdout.close()
            returncode = process.wait(timeout=10)
            errors = process.stderr.read()
            self.assertEqual(returncode, 0, errors)
            self.assertEqual(errors, "")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stderr.close()

    def close_stdout_after_output(self, args, *, lines=3, timeout=3):
        process = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "sericite", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
        )
        try:
            for _ in range(lines):
                if process.stdout.readline() == "":
                    self.fail(
                        f"CLI produced no expected output: {process.stderr.read()}"
                    )
            process.stdout.close()
            returncode = process.wait(timeout=timeout)
            errors = process.stderr.read()
            return returncode, errors
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_pipe_closure_stops_root_with_default_and_unlimited_quotas(self):
        source = "i = 0\nwhile True:\n    print(i)\n    i += 1"
        returncode, errors = self.close_stdout_after_output(["-c", source])
        self.assertEqual(returncode, 0, errors)
        self.assertEqual(errors, "")

        with tempfile.TemporaryDirectory() as tmp:
            capabilities = Path(tmp) / "unlimited.py"
            capabilities.write_text(
                "from sericite import SericiteLimits\n"
                "def configure():\n"
                "    return {'limits': SericiteLimits("
                "max_instructions=-1, max_output_bytes=-1)}\n",
                encoding="utf-8",
            )
            returncode, errors = self.close_stdout_after_output(
                ["--capabilities", str(capabilities), "-c", source], timeout=2
            )
        self.assertEqual(returncode, 0, errors)
        self.assertEqual(errors, "")

    def test_pipe_closure_stops_nested_vm_output(self):
        source = (
            "def forward(text):\n"
            '    print(text, end="")\n'
            "sub = VM("
            "'i = 0\\nwhile True:\\n    print(i)\\n    i += 1', "
            "output_writer=forward, buffer_output=False, "
            "max_instructions=-1, max_output_bytes=-1)\n"
            "sub.run()"
        )
        returncode, errors = self.close_stdout_after_output(["-c", source], timeout=2)
        self.assertEqual(returncode, 0, errors)
        self.assertEqual(errors, "")

    def test_pipe_closure_skips_remaining_script_and_finally(self):
        with tempfile.TemporaryDirectory() as tmp:
            capabilities = Path(tmp) / "mark.py"
            capabilities.write_text(
                "import sys\n"
                "def mark(message):\n"
                "    print(message, file=sys.stderr, flush=True)\n"
                "def configure():\n"
                "    return {'functions': {'mark': mark}}\n",
                encoding="utf-8",
            )
            source = (
                "i = 0\n"
                "try:\n"
                "    while i < 50000:\n"
                "        print(i)\n"
                "        i += 1\n"
                "finally:\n"
                '    mark("finally")\n'
                'mark("finished")'
            )
            returncode, errors = self.close_stdout_after_output(
                ["--capabilities", str(capabilities), "-c", source]
            )
        self.assertEqual(returncode, 0, errors)
        self.assertEqual(errors, "")

    def test_frontend_stdout_closure_returns_zero(self):
        from io import StringIO
        from unittest.mock import patch

        from sericite.cli import main

        class ClosedStdout:
            def __init__(self, sink):
                self.sink = sink

            def write(self, value):
                raise BrokenPipeError

            def flush(self):
                pass

            def fileno(self):
                return self.sink.fileno()

        for args in (["--help"], ["--version"], []):
            with (
                self.subTest(args=args),
                tempfile.TemporaryFile() as sink,
                patch("sys.stdout", ClosedStdout(sink)),
                patch("sys.stdin", StringIO("")),
            ):
                self.assertEqual(main(args), 0)

    def test_windows_einvalid_stdout_closure_returns_zero(self):
        import errno
        from unittest.mock import patch

        from sericite.cli import main

        class ClosedStdout:
            def __init__(self, sink):
                self.sink = sink

            def write(self, value):
                raise OSError(errno.EINVAL, "Invalid argument")

            def flush(self):
                pass

            def fileno(self):
                return self.sink.fileno()

        with (
            tempfile.TemporaryFile() as sink,
            patch("sys.stdout", ClosedStdout(sink)),
            patch("sericite.cli._hostio.sys.platform", "win32"),
        ):
            self.assertEqual(main(["--version"]), 0)

    def test_windows_stdout_other_os_errors_are_not_silenced(self):
        import errno
        from unittest.mock import patch

        from sericite.cli import main

        class FailingStdout:
            def write(self, value):
                raise OSError(errno.EIO, "I/O error")

            def flush(self):
                pass

        with (
            patch("sys.stdout", FailingStdout()),
            patch("sericite.cli._hostio.sys.platform", "win32"),
            self.assertRaises(OSError) as caught,
        ):
            main(["--version"])
        self.assertEqual(caught.exception.errno, errno.EIO)


if __name__ == "__main__":
    unittest.main()
