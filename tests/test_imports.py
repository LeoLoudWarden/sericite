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
            "import_error module 'missing' not found\n"
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
            "fs = VFS()\n"
            "fs.write_file('/util.sericite', \"value = 'child'\\n\")\n"
            "sub = VM('import util\\nprint(util.value)', fs=fs)\n"
            "print(sub.run(), end='')\n",
            {"/util.sericite": "value = 'parent'\n"},
        )
        self.assertEqual(output, "child\n")

    def test_entry_file_scopes_imports_without_rerooting_file_paths(self):
        output = self.run_source(
            "fs = VFS()\n"
            "fs.write_file('/util.sericite', \"value = 'workspace'\\n\")\n"
            "fs.write_file('/project/util.sericite', \"value = 'project'\\n\")\n"
            "fs.write_file('/project/pkg/__init__.sericite', '')\n"
            "fs.write_file('/project/pkg/util.sericite', \"value = 'project'\\n\")\n"
            "fs.write_file('/project/pkg/mod.sericite', 'from .util import value\\n')\n"
            "fs.write_file('/project/main.sericite', \"import util\\n"
            "from pkg.mod import value\\nwrite_file('/result.txt', util.value)\\n"
            'print(util.value, value)")\n'
            "sub = VM(entry_file='/project/main.sericite', fs=fs)\n"
            "print(sub.run(), end='')\n"
            "fs = sub.take_fs()\n"
            "print(fs.read_file('/result.txt'))\n"
        )
        self.assertEqual(output, "project project\nproject\n")

    def test_entry_file_is_normalized_and_module_root_stays_in_session(self):
        output = self.run_source(
            "fs = VFS()\n"
            "fs.write_file('/util.sericite', \"value = 'workspace'\\n\")\n"
            "fs.write_file('/project/util.sericite', \"value = 'project'\\n\")\n"
            "fs.write_file('/project/main.sericite', "
            "'import util\\nprint(util.value)\\n')\n"
            "sub = VM(entry_file='/scratch/../project/./main.sericite', fs=fs)\n"
            "print(sub.run(), end='')\n"
            "print(sub.exec('print(util.value)'), end='')\n"
            "fs = sub.take_fs()\n"
            "sub = VM('import util\\nprint(util.value)', fs=fs)\n"
            "print(sub.run(), end='')\n"
        )
        self.assertEqual(output, "project\nproject\nworkspace\n")

    def test_entry_file_root_follows_granted_function_home(self):
        engine = SericiteEngine()
        fs = engine.create_vfs()
        fs.write_file("/home/util.sericite", "value = 'home'\n")
        fs.write_file(
            "/home/main.sericite",
            "def load():\n"
            "    import util\n"
            "    return util.value\n"
            "fs = VFS()\n"
            "fs.write_file('/caller/main.sericite', 'print(load())\\n')\n"
            "sub = VM(entry_file='/caller/main.sericite', "
            "functions={'load': load}, fs=fs)\n"
            "print(sub.run(), end='')\n",
        )
        root = engine.create_root(entry_file="/home/main.sericite", fs=fs)
        self.assertEqual(root.run(), "home\n")

    def test_invalid_entry_file_does_not_consume_vfs(self):
        output = self.run_source(
            "fs = VFS()\n"
            "fs.write_file('/broken.sericite', 'def broken(:')\n"
            "try:\n"
            "    VM(entry_file=1, fs=fs)\n"
            "except type_error as e:\n"
            "    print(e.message)\n"
            "try:\n"
            "    VM(entry_file='/missing.sericite', fs=fs)\n"
            "except file_not_found as e:\n"
            "    print(e.kind)\n"
            "try:\n"
            "    VM(entry_file='/broken.sericite', fs=fs)\n"
            "except syntax_error as e:\n"
            "    print(e.kind)\n"
            "try:\n"
            "    VM('', entry_file='/main.sericite', fs=fs)\n"
            "except type_error as e:\n"
            "    print(e.message)\n"
            "fs.write_file('/ok.txt', 'ok')\n"
            "print(fs.read_file('/ok.txt'))\n"
        )
        self.assertEqual(
            output,
            "entry_file must be a string\nfile_not_found\nsyntax_error\n"
            "exactly one of source or entry_file is required\nok\n",
        )

    def test_source_keyword_and_entry_file_requires_fs(self):
        output = self.run_source(
            "sub = VM(source='print(42)')\n"
            "print(sub.run(), end='')\n"
            "try:\n"
            "    VM(entry_file='/main.sericite')\n"
            "except type_error as e:\n"
            "    print(e.message)\n"
        )
        self.assertEqual(output, "42\nentry_file requires fs\n")

    def test_granted_function_imports_from_home_not_caller(self):
        output = self.run_source(
            "def load():\n"
            "    import util\n"
            "    return util.value\n"
            "fs = VFS()\n"
            "fs.write_file('/util.sericite', \"value = 'caller'\\n\")\n"
            "sub = VM('print(load())', functions={'load': load}, fs=fs)\n"
            "print(sub.run(), end='')\n",
            {"/util.sericite": "value = 'home'\n"},
        )
        self.assertEqual(output, "home\n")

    def test_granted_module_function_keeps_home_for_nested_import(self):
        output = self.run_source(
            "from util import read_other\n"
            "fs = VFS()\n"
            "fs.write_file('/other.sericite', \"value = 'caller'\\n\")\n"
            "sub = VM('print(read_other())', functions={'read_other': read_other}, fs=fs)\n"
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

    def test_dotted_import_binding_alias_and_from_import(self):
        output = self.run_source(
            "import lib.math\n"
            "import lib.math as m\n"
            "from lib.math import double\n"
            "print(lib.math.double(2), m.double(3), double(4))\n",
            {
                "/lib/__init__.sericite": "print('lib')\n",
                "/lib/math.sericite": (
                    "print('math')\ndef double(x):\n    return x * 2\n"
                ),
            },
        )
        self.assertEqual(output, "lib\nmath\n4 6 8\n")

    def test_dotted_import_inside_function_binds_top_level_package(self):
        output = self.run_source(
            "def f():\n    import lib.math\n    return lib.math.value\nprint(f())\n",
            {
                "/lib/__init__.sericite": "",
                "/lib/math.sericite": "value = 16\n",
            },
        )
        self.assertEqual(output, "16\n")

    def test_nested_packages_and_final_package(self):
        nested = self.run_source(
            "import root.branch.leaf\nprint(root.branch.leaf.value)\n",
            {
                "/root/__init__.sericite": "",
                "/root/branch/__init__.sericite": "",
                "/root/branch/leaf.sericite": "value = 17\n",
            },
        )
        self.assertEqual(nested, "17\n")
        final_package = self.run_source(
            "import lib.math\nprint(lib.math.value)\n",
            {
                "/lib/__init__.sericite": "",
                "/lib/math/__init__.sericite": "value = 18\n",
            },
        )
        self.assertEqual(final_package, "18\n")

    def test_from_package_prefers_existing_export(self):
        output = self.run_source(
            "from pkg import child\nprint(child)\n",
            {
                "/pkg/__init__.sericite": "child = 'export'\n",
                "/pkg/child.sericite": "print('should not load')\n",
            },
        )
        self.assertEqual(output, "export\n")

    def test_from_package_loads_and_caches_submodule(self):
        output = self.run_source(
            "from pkg import child\n"
            "import pkg.child\n"
            "print(child.value, pkg.child == child)\n",
            {
                "/pkg/__init__.sericite": "",
                "/pkg/child.sericite": "print('child')\nvalue = 19\n",
            },
        )
        self.assertEqual(output, "child\n19 True\n")

    def test_failed_from_package_submodule_can_be_retried(self):
        _, root = self.make_root(
            files={
                "/pkg/__init__.sericite": "",
                "/pkg/child.sericite": "raise 'bad'\n",
            }
        )
        root.exec("try:\n    from pkg import child\nexcept raise_error:\n    pass\n")
        root.write_file("/pkg/child.sericite", "value = 20\n")
        self.assertEqual(root.exec("from pkg import child\nprint(child.value)"), "20\n")

    def test_package_requires_init_and_cannot_conflict_with_file(self):
        missing_init = self.run_source(
            "try:\n    import lib.math\nexcept import_error as e:\n    print(e.kind)\n",
            {"/lib/math.sericite": "value = 1\n"},
        )
        self.assertEqual(missing_init, "import_error\n")

        not_package = self.run_source(
            "try:\n    import lib.math\nexcept import_error as e:\n    print(e.message)\n",
            {
                "/lib.sericite": "",
                "/lib/math.sericite": "value = 1\n",
            },
        )
        self.assertEqual(not_package, "module 'lib' is not a package\n")

        ambiguous = self.run_source(
            "try:\n    import lib\nexcept import_error as e:\n    print(e.message)\n",
            {"/lib.sericite": "", "/lib/__init__.sericite": ""},
        )
        self.assertEqual(ambiguous, "module 'lib' is both a file and a package\n")

    def test_relative_imports_within_package(self):
        output = self.run_source(
            "from pkg.mod import result\nprint(result)\n",
            {
                "/pkg/__init__.sericite": "",
                "/pkg/util.sericite": "value = 21\n",
                "/pkg/other.sericite": "value = 4\n",
                "/pkg/mod.sericite": (
                    "from .util import value\n"
                    "from . import other\n"
                    "result = value + other.value\n"
                ),
            },
        )
        self.assertEqual(output, "25\n")

    def test_package_init_can_import_child_while_package_is_loading(self):
        output = self.run_source(
            "import pkg\nprint(pkg.child.value)\n",
            {
                "/pkg/__init__.sericite": "from . import child\n",
                "/pkg/child.sericite": "value = 22\n",
            },
        )
        self.assertEqual(output, "22\n")

    def test_relative_imports_from_parent_package(self):
        output = self.run_source(
            "from pkg.sub.mod import result\nprint(result)\n",
            {
                "/pkg/__init__.sericite": "",
                "/pkg/util.sericite": "value = 23\n",
                "/pkg/other.sericite": "value = 5\n",
                "/pkg/sub/__init__.sericite": "",
                "/pkg/sub/mod.sericite": (
                    "from ..util import value\n"
                    "from .. import other\n"
                    "result = value + other.value\n"
                ),
            },
        )
        self.assertEqual(output, "28\n")

    def test_relative_and_absolute_imports_share_cache(self):
        output = self.run_source(
            "import pkg\nfrom pkg.mod import value\nimport pkg.util\n",
            {
                "/pkg/__init__.sericite": "from . import util\n",
                "/pkg/util.sericite": "print('util')\nvalue = 24\n",
                "/pkg/mod.sericite": "from .util import value\n",
            },
        )
        self.assertEqual(output, "util\n")

    def test_relative_import_outside_package_or_above_root_fails(self):
        outside = self.run_source(
            "try:\n"
            "    from . import util\n"
            "except import_error as e:\n"
            "    print(e.message)\n"
        )
        self.assertEqual(outside, "relative import outside a package\n")
        above_root = self.run_source(
            "try:\n"
            "    from pkg.mod import value\n"
            "except import_error as e:\n"
            "    print(e.message)\n",
            {
                "/pkg/__init__.sericite": "",
                "/pkg/mod.sericite": "from ..util import value\n",
            },
        )
        self.assertEqual(above_root, "relative import escapes the package root\n")

    def test_granted_function_relative_import_uses_home_package(self):
        output = self.run_source(
            "from pkg.mod import load\n"
            "fs = VFS()\n"
            "fs.write_file('/pkg/__init__.sericite', '')\n"
            "fs.write_file('/pkg/util.sericite', \"value = 'caller'\\n\")\n"
            "sub = VM('print(load())', functions={'load': load}, fs=fs)\n"
            "print(sub.run(), end='')\n",
            {
                "/pkg/__init__.sericite": "",
                "/pkg/util.sericite": "value = 'home'\n",
                "/pkg/mod.sericite": (
                    "def load():\n    from .util import value\n    return value\n"
                ),
            },
        )
        self.assertEqual(output, "home\n")

    def test_package_cycle_reports_qualified_names(self):
        output = self.run_source(
            "try:\n    import pkg.a\nexcept import_error as e:\n    print(e.message)\n",
            {
                "/pkg/__init__.sericite": "",
                "/pkg/a.sericite": "from . import b\n",
                "/pkg/b.sericite": "from . import a\n",
            },
        )
        self.assertEqual(output, "circular import: pkg.a -> pkg.b -> pkg.a\n")

    def test_from_package_continues_with_later_exports(self):
        output = self.run_source(
            "from pkg import child\n"
            "from pkg import answer\n"
            "print(child.value, answer)\n",
            {
                "/pkg/__init__.sericite": "answer = 42\n",
                "/pkg/child.sericite": "value = 7\n",
            },
        )
        self.assertEqual(output, "7 42\n")

    def test_from_package_comma_imports_keep_values_and_stack_aligned(self):
        output = self.run_source(
            "from pkg import child, other, answer\n"
            "print(child.value, other.value, answer)\n",
            {
                "/pkg/__init__.sericite": "answer = 42\n",
                "/pkg/child.sericite": "value = 7\n",
                "/pkg/other.sericite": "value = 8\n",
            },
        )
        self.assertEqual(output, "7 8 42\n")

    def test_package_init_comma_imports_resume_correctly(self):
        output = self.run_source(
            "import pkg\nprint(pkg.child.value, pkg.other.value, pkg.answer)\n",
            {
                "/pkg/__init__.sericite": (
                    "answer = 42\nfrom . import child, other, answer\n"
                ),
                "/pkg/child.sericite": "value = 9\n",
                "/pkg/other.sericite": "value = 10\n",
            },
        )
        self.assertEqual(output, "9 10 42\n")

    def test_function_and_granted_function_from_imports_resume_correctly(self):
        files = {
            "/pkg/__init__.sericite": "answer = 42\n",
            "/pkg/child.sericite": "value = 11\n",
        }
        local = self.run_source(
            "def load():\n"
            "    from pkg import child, answer\n"
            "    return child.value + answer\n"
            "print(load())\n",
            files,
        )
        self.assertEqual(local, "53\n")
        granted = self.run_source(
            "def load():\n"
            "    from pkg import child, answer\n"
            "    return child.value + answer\n"
            "sub = VM('print(load())', functions={'load': load})\n"
            "print(sub.run(), end='')\n",
            files,
        )
        self.assertEqual(granted, "53\n")

    def test_sibling_vm_import_charges_home_account(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "box = []\n"
            "def capture(fn):\n"
            "    box.append(fn)\n"
            "a = VM('def load():\\n"
            "    import util\\n"
            "    return util.value\\n"
            "capture(load)\\n', functions={'capture': capture})\n"
            "a.run()\n"
            "f = box[0]\n"
        )
        root.run()
        context = engine._context(root)
        a = context.frames[0].locals["a"]
        home = engine._context(a)
        a.write_file("/util.sericite", "value = 99\n")
        before = home.alloc_bytes
        output = root.exec(
            "b = VM('print(f())', functions={'f': f})\nprint(b.run(), end='')\n"
        )
        self.assertEqual(output, "99\n")
        self.assertGreater(home.alloc_bytes, before)
        self.assertEqual(list(home.modules), ["util"])

    def test_sibling_vm_import_cannot_bypass_exhausted_home_quota(self):
        engine = SericiteEngine()
        root = engine.create_root(
            "box = []\n"
            "def capture(fn):\n"
            "    box.append(fn)\n"
            "a = VM('def load():\\n"
            "    import util\\n"
            "    return util.value\\n"
            "capture(load)\\n', functions={'capture': capture}, max_total_bytes=8)\n"
            "a.run()\n"
            "f = box[0]\n"
        )
        root.run()
        context = engine._context(root)
        a = context.frames[0].locals["a"]
        home = engine._context(a)
        a.write_file("/util.sericite", "value = 99\n")
        before = (home.instruction_count, home.alloc_bytes)
        output = root.exec(
            "b = VM('try:\\n"
            "    print(f())\\n"
            "except resource_exhausted as e:\\n"
            "    print(e.kind)', functions={'f': f})\n"
            "print(b.run(), end='')\n"
        )
        self.assertEqual(output, "resource_exhausted\n")
        self.assertGreater(home.instruction_count, before[0])
        self.assertEqual(home.alloc_bytes, before[1])
        self.assertEqual(home.modules, {})

    def test_invalid_import_bindings_and_wildcard_are_rejected(self):
        cases = (
            "from util import *\n",
            "import print\n",
            "import __private\n",
            "import pkg.__private as p\n",
            "from pkg.__private import value\n",
            "from __private import value\n",
            "from .__private import value\n",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(SericiteError) as caught:
                    SericiteEngine().create_root(source)
                self.assertEqual(caught.exception.kind, "syntax_error")


if __name__ == "__main__":
    unittest.main()
