from __future__ import annotations

import unittest

from sericite import SericiteEngine, SericiteError, SericiteLimits
from sericite.cli import _CombinedSource, _format_error


class ImportTests(unittest.TestCase):
    def make_root(
        self,
        source="",
        files=None,
        *,
        functions=None,
        limits=None,
    ):
        engine = SericiteEngine()
        root = engine.create_root(source, functions=functions, limits=limits)
        for path, text in (files or {}).items():
            root.write_file(path, text)
        return engine, root

    def run_source(self, source, files=None, **kwargs):
        _, root = self.make_root(source, files, **kwargs)
        return root.run()

    def test_basic_import_forms_and_aliases(self):
        output = self.run_source(
            "import util\n"
            "import util as u\n"
            "from util import double\n"
            "from util import double as twice\n"
            "print(util.value, u.value, double(3), twice(4))\n"
            "print(util == u)\n",
            {"/util.sericite": ("value = 7\ndef double(x):\n    return x * 2\n")},
        )
        self.assertEqual(output, "7 7 6 8\nTrue\n")

    def test_module_globals_are_independent(self):
        output = self.run_source(
            "import util\n"
            "x = 99\n"
            "print(util.get(), x)\n"
            "try:\n"
            "    print(get())\n"
            "except name_error:\n"
            "    print('not leaked')\n",
            {"/util.sericite": ("x = 10\ndef get():\n    return x\n")},
        )
        self.assertEqual(output, "10 99\nnot leaked\n")

    def test_module_records_and_functions_keep_their_definition_environment(self):
        output = self.run_source(
            "from util import Point, make\np = make()\nprint(p.x, p.y)\n",
            {
                "/util.sericite": (
                    "class Point:\n"
                    "    x: int\n"
                    "    y: int\n"
                    "def make() -> Point:\n"
                    "    return Point(2, 3)\n"
                )
            },
        )
        self.assertEqual(output, "2 3\n")

    def test_repeated_and_diamond_imports_execute_once(self):
        output = self.run_source(
            "import a\nimport b\nimport util\n",
            {
                "/util.sericite": "print('util')\n",
                "/a.sericite": "import util\nprint('a')\n",
                "/b.sericite": "import util\nprint('b')\n",
            },
        )
        self.assertEqual(output, "util\na\nb\n")

    def test_cache_persists_across_exec_and_does_not_reload_changed_source(self):
        _, root = self.make_root(files={"/util.sericite": "print('load')\nx = 1\n"})
        self.assertEqual(root.exec("import util"), "load\n")
        root.write_file("/util.sericite", "print('new')\nx = 2\n")
        self.assertEqual(root.exec("import util\nprint(util.x)"), "1\n")

    def test_function_import_is_a_local_binding(self):
        output = self.run_source(
            "def f():\n"
            "    import util as u\n"
            "    return u.value\n"
            "print(f())\n"
            "try:\n"
            "    print(u)\n"
            "except name_error:\n"
            "    print('local')\n",
            {"/util.sericite": "value = 11\n"},
        )
        self.assertEqual(output, "11\nlocal\n")

    def test_conditional_and_caught_imports_are_lazy(self):
        output = self.run_source(
            "if False:\n"
            "    import absent\n"
            "try:\n"
            "    import missing\n"
            "except import_error as e:\n"
            "    print(e.kind, e.message)\n"
            "try:\n"
            "    from util import missing\n"
            "except import_error as e:\n"
            "    print(e.kind, e.message)\n",
            {"/util.sericite": "value = 1\n"},
        )
        self.assertEqual(
            output,
            "import_error module 'missing' not found at /missing.sericite\n"
            "import_error cannot import name 'missing'\n",
        )

    def test_direct_and_indirect_cycles_are_catchable(self):
        direct = self.run_source(
            "try:\n    import a\nexcept import_error as e:\n    print(e.message)\n",
            {"/a.sericite": "import a\n"},
        )
        self.assertEqual(direct, "circular import: a -> a\n")
        indirect = self.run_source(
            "try:\n    import a\nexcept import_error as e:\n    print(e.message)\n",
            {
                "/a.sericite": "import b\n",
                "/b.sericite": "import a\n",
            },
        )
        self.assertEqual(indirect, "circular import: a -> b -> a\n")

    def test_runtime_failure_is_not_cached_and_can_be_retried(self):
        _, root = self.make_root(files={"/util.sericite": "raise 'bad'\n"})
        root.exec("try:\n    import util\nexcept raise_error:\n    pass\n")
        root.write_file("/util.sericite", "value = 8\n")
        self.assertEqual(root.exec("import util\nprint(util.value)"), "8\n")

    def test_syntax_failure_is_not_cached_and_can_be_retried(self):
        _, root = self.make_root(files={"/util.sericite": "def broken(:\n"})
        root.exec("try:\n    import util\nexcept syntax_error:\n    pass\n")
        root.write_file("/util.sericite", "value = 9\n")
        self.assertEqual(root.exec("import util\nprint(util.value)"), "9\n")

    def test_imported_runtime_error_preserves_kind_location_and_frames(self):
        source = "import util\nutil.fail()\n"
        _, root = self.make_root(
            source,
            {"/util.sericite": "def fail():\n    return 1 / 0\n"},
        )
        with self.assertRaises(SericiteError) as caught:
            root.run()
        error = caught.exception
        self.assertEqual(error.kind, "zero_division")
        self.assertEqual(error.filename, "/util.sericite")
        self.assertEqual(error.line, 2)
        self.assertEqual(
            [(frame.function, frame.line) for frame in error.frames],
            [("<module>", 2), ("fail", 2)],
        )
        formatted = _format_error(error, _CombinedSource([("main.sericite", source)]))
        self.assertIn("/util.sericite:2: zero_division", formatted)
        self.assertIn('File "main.sericite", line 2, in <module>', formatted)
        self.assertIn('File "/util.sericite", line 2, in fail', formatted)

    def test_imported_syntax_error_uses_module_location(self):
        _, root = self.make_root(
            "import util\n", {"/util.sericite": "x = 1\nif True print('bad')\n"}
        )
        with self.assertRaises(SericiteError) as caught:
            root.run()
        self.assertEqual(caught.exception.kind, "syntax_error")
        self.assertEqual(caught.exception.filename, "/util.sericite")
        self.assertEqual(caught.exception.line, 2)

    def test_child_vm_does_not_inherit_parent_modules_or_files(self):
        output = self.run_source(
            "sub = VM('import util')\n"
            "try:\n"
            "    sub.run()\n"
            "except import_error as e:\n"
            "    print(e.kind)\n",
            {"/util.sericite": "value = 'parent'\n"},
        )
        self.assertEqual(output, "import_error\n")

    def test_child_uses_its_own_module_file(self):
        output = self.run_source(
            "sub = VM('import util\\nprint(util.value)')\n"
            "sub.write_file('/util.sericite', \"value = 'child'\\n\")\n"
            "print(sub.run(), end='')\n",
            {"/util.sericite": "value = 'parent'\n"},
        )
        self.assertEqual(output, "child\n")

    def test_granted_function_imports_from_home_not_caller(self):
        output = self.run_source(
            "def load():\n"
            "    import util\n"
            "    return util.value\n"
            "sub = VM('print(load())', functions={'load': load})\n"
            "sub.write_file('/util.sericite', \"value = 'caller'\\n\")\n"
            "print(sub.run(), end='')\n",
            {"/util.sericite": "value = 'home'\n"},
        )
        self.assertEqual(output, "home\n")

    def test_granted_module_function_keeps_home_for_nested_import(self):
        output = self.run_source(
            "from util import read_other\n"
            "sub = VM('print(read_other())', functions={'read_other': read_other})\n"
            "sub.write_file('/other.sericite', \"value = 'caller'\\n\")\n"
            "print(sub.run(), end='')\n",
            {
                "/util.sericite": (
                    "def read_other():\n    import other\n    return other.value\n"
                ),
                "/other.sericite": "value = 'home'\n",
            },
        )
        self.assertEqual(output, "home\n")

    def test_module_can_be_explicitly_returned_to_another_vm(self):
        output = self.run_source(
            "import util\n"
            "def get_module():\n"
            "    return util\n"
            "sub = VM('m = get_module()\\nprint(m.value)\\nprint(m)', "
            "functions={'get_module': get_module})\n"
            "print(sub.run(), end='')\n",
            {"/util.sericite": "value = 12\n"},
        )
        self.assertEqual(output, "12\n<module>\n")

    def test_foreign_import_failure_does_not_expose_home_module_name(self):
        output = self.run_source(
            "def load():\n"
            "    import private_helper\n"
            "sub = VM('load()', functions={'load': load})\n"
            "try:\n"
            "    sub.run()\n"
            "except import_error as e:\n"
            "    print(e.message)\n"
        )
        self.assertEqual(output, "module import failed\n")

    def test_module_cannot_cross_host_ffi(self):
        _, root = self.make_root(
            "import util\necho(util)\n",
            {"/util.sericite": "value = 1\n"},
            functions={"echo": lambda value: value},
        )
        with self.assertRaises(SericiteError) as caught:
            root.run()
        self.assertEqual(caught.exception.kind, "ffi_error")
        self.assertIn("module", caught.exception.message)

    def test_module_rendering_attribute_errors_and_snapshots_are_safe(self):
        _, root = self.make_root(
            "import util\nprint(util)\n",
            {"/util.sericite": "value = 1\n"},
        )
        self.assertEqual(root.run(), "<module>\n")
        self.assertEqual(root.snapshot()["locals"]["util"], "<module>")
        with self.assertRaises(SericiteError) as caught:
            root.exec("util.missing")
        self.assertEqual(caught.exception.kind, "attribute_error")
        with self.assertRaises(SericiteError) as caught:
            root.exec("util.value = 2")
        self.assertEqual(caught.exception.kind, "type_error")

    def test_module_input_pauses_and_resumes_the_same_execution(self):
        _, root = self.make_root(
            "import util\nprint(util.value)\n",
            {"/util.sericite": "value = input()\n"},
        )
        self.assertEqual(root.run(), "")
        self.assertEqual(root.snapshot()["state"], "waiting_input")
        root.feed_input("ready")
        self.assertEqual(root.run(), "ready\n")

    def test_statement_step_executes_import_as_one_statement(self):
        _, root = self.make_root(
            "import util\nprint('main')\n",
            {"/util.sericite": "print('a')\nprint('b')\n"},
        )
        snapshot = root.step()
        self.assertEqual(snapshot["stdout"], "a\nb\n")
        self.assertEqual(snapshot["next_line"], 2)
        self.assertEqual(root.step()["state"], "done")

    def test_instruction_step_enters_module_frame(self):
        _, root = self.make_root(
            "import util\nprint(util.value)\n",
            {"/util.sericite": "value = 4\n"},
        )
        snapshot = root.step_instruction()
        self.assertEqual(snapshot["state"], "ready")
        self.assertEqual(snapshot["next_line"], 1)
        self.assertEqual(root.run(), "4\n")

    def test_exec_discarding_waiting_module_clears_loading_state(self):
        _, root = self.make_root(
            "import util\n", {"/util.sericite": "value = input()\n"}
        )
        root.run()
        self.assertEqual(root.snapshot()["state"], "waiting_input")
        self.assertEqual(root.exec("print('reset')"), "reset\n")
        root.write_file("/util.sericite", "value = 6\n")
        self.assertEqual(root.exec("import util\nprint(util.value)"), "6\n")

    def test_output_writer_frame_cleanup_allows_import_retry(self):
        output = self.run_source(
            "def writer(text):\n"
            "    import util\n"
            "sub = VM(\"print('x')\", output_writer=writer)\n"
            "try:\n"
            "    sub.run()\n"
            "except runtime_error:\n"
            "    print('caught')\n"
            "write_file('/util.sericite', 'value = 1\\n')\n"
            "import util\n"
            "print('retried')\n",
            {"/util.sericite": "value = input()\n"},
        )
        self.assertEqual(output, "caught\nretried\n")

    def test_import_uses_frames_and_instruction_quotas(self):
        _, root = self.make_root(
            "import util\n",
            {"/util.sericite": "value = 1\n"},
            limits=SericiteLimits(max_frames=1),
        )
        with self.assertRaises(SericiteError) as caught:
            root.run()
        self.assertEqual(caught.exception.kind, "resource_exhausted")

        _, root = self.make_root(
            "import util\n",
            {"/util.sericite": "value = 1\n"},
            limits=SericiteLimits(max_instructions=4),
        )
        with self.assertRaises(SericiteError) as caught:
            root.run()
        self.assertEqual(caught.exception.kind, "resource_exhausted")

    def test_cached_import_is_cheaper_than_initial_execution(self):
        _, root = self.make_root(files={"/util.sericite": "value = 1\n"})
        root.exec("import util")
        initial = root.snapshot()["instruction_count"]
        root.exec("import util")
        self.assertLess(root.snapshot()["instruction_count"] - initial, initial)

    def test_unsupported_import_forms_and_invalid_bindings_are_rejected(self):
        cases = (
            "import lib.util\n",
            "from . import util\n",
            "from util import *\n",
            "import print\n",
            "import __private\n",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as caught:
                    SericiteEngine().create_root(source)
                self.assertEqual(caught.exception.kind, "syntax_error")


if __name__ == "__main__":
    unittest.main()
