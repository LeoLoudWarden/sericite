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

    def test_arguments_are_required_and_mutually_exclusive(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        result = self.run_cli("-c", "pass", "examples/root.sericite")
        self.assertEqual(result.returncode, 2)

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
