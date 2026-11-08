from __future__ import annotations

import unittest

from sericite import SericiteError
from sericite.engine import SericiteEngine


class VirtualFileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SericiteEngine()
        self.engine.create_root("")
        self.context = self.engine._contexts[0]
        self.fs = self.context.fs
        self.meter = self.engine._meter(self.context)

    def test_script_write_consumes_matching_permit(self) -> None:
        amount = self.fs.write_allocation("/a/file.txt", "x")
        permit = self.meter.reserve(self.fs, "write", amount)
        self.fs.write_file("/a/file.txt", "x", permit=permit)
        self.assertTrue(permit.consumed)
        self.assertEqual(self.fs.read_file("/a/file.txt"), "x")
        self.assertEqual(self.context.alloc_bytes, amount)

    def test_directory_name_metadata_supports_constant_time_estimates(self) -> None:
        self.fs.write_file_trusted("/alpha/file.txt", "")
        self.fs.write_file_trusted("/beta.txt", "")
        root = self.fs._root
        names = (*root.directories, *root.files)
        self.assertEqual(root.name_chars, sum(len(name) for name in names))
        count = len(names)
        expected = 1 + (count + root.name_chars) * max(1, count.bit_length())
        self.assertEqual(self.fs.list_dir_work("/"), expected)

    def test_delete_prunes_only_empty_implicit_directories(self) -> None:
        self.fs.write_file_trusted("/a/b/remove.txt", "x")
        self.fs.write_file_trusted("/a/keep.txt", "y")
        self.fs.delete_file("/a/b/remove.txt")
        self.assertFalse(self.fs.path_exists("/a/b"))
        self.assertTrue(self.fs.path_exists("/a"))
        self.assertEqual(self.fs.list_dir("/a"), ["keep.txt"])
        self.fs.delete_file("/a/keep.txt")
        self.assertFalse(self.fs.path_exists("/a"))
        self.assertTrue(self.fs.path_exists("/"))

    def test_delete_rejects_missing_files_and_directories(self) -> None:
        self.fs.write_file_trusted("/d/file.txt", "x")
        for path in ("/missing.txt", "/d"):
            with self.subTest(path=path), self.assertRaises(SericiteError) as ctx:
                self.fs.delete_file(path)
            expected = "file_not_found" if path == "/missing.txt" else "is_directory"
            self.assertEqual(ctx.exception.kind, expected)
        self.assertEqual(self.fs.read_file("/d/file.txt"), "x")

    def test_rename_moves_file_and_updates_both_directory_trees(self) -> None:
        self.fs.write_file_trusted("/old/nested/file.txt", "payload")
        amount = self.fs.rename_allocation("/old/nested/file.txt", "/new/renamed.txt")
        permit = self.meter.reserve(self.fs, "write", amount)
        self.fs.rename_file("/old/nested/file.txt", "/new/renamed.txt", permit=permit)
        self.assertTrue(permit.consumed)
        self.assertFalse(self.fs.path_exists("/old"))
        self.assertEqual(self.fs.read_file("/new/renamed.txt"), "payload")
        self.assertEqual(self.fs.list_dir("/new"), ["renamed.txt"])

    def test_copy_keeps_source_and_consumes_matching_permit(self) -> None:
        self.fs.write_file_trusted("/source.txt", "payload")
        amount = self.fs.copy_allocation("/source.txt", "/a/b/copy.txt")
        permit = self.meter.reserve(self.fs, "write", amount)
        self.fs.copy_file("/source.txt", "/a/b/copy.txt", permit=permit)
        self.assertTrue(permit.consumed)
        self.assertEqual(self.fs.read_file("/source.txt"), "payload")
        self.assertEqual(self.fs.read_file("/a/b/copy.txt"), "payload")

    def test_rename_and_copy_reject_existing_files_without_mutation(self) -> None:
        self.fs.write_file_trusted("/source.txt", "source")
        self.fs.write_file_trusted("/destination.txt", "destination")
        operations = (
            lambda: self.fs.rename_file_trusted("/source.txt", "/destination.txt"),
            lambda: self.fs.copy_file_trusted("/source.txt", "/destination.txt"),
            lambda: self.fs.rename_file_trusted("/source.txt", "/source.txt"),
            lambda: self.fs.copy_file_trusted("/source.txt", "/source.txt"),
        )
        for operation in operations:
            with (
                self.subTest(operation=operation),
                self.assertRaises(SericiteError) as ctx,
            ):
                operation()
            self.assertEqual(ctx.exception.kind, "file_exists")
            self.assertEqual(self.fs.read_file("/source.txt"), "source")
            self.assertEqual(self.fs.read_file("/destination.txt"), "destination")

    def test_rename_and_copy_reject_directories(self) -> None:
        self.fs.write_file_trusted("/d/source.txt", "source")
        operations = (
            (lambda: self.fs.delete_file("/d"), "is_directory"),
            (lambda: self.fs.rename_file_trusted("/d", "/new"), "is_directory"),
            (lambda: self.fs.copy_file_trusted("/d", "/new"), "is_directory"),
            (
                lambda: self.fs.rename_file_trusted("/d/source.txt", "/d"),
                "is_directory",
            ),
            (
                lambda: self.fs.copy_file_trusted("/d/source.txt", "/d"),
                "is_directory",
            ),
        )
        for operation, kind in operations:
            with self.subTest(kind=kind), self.assertRaises(SericiteError) as ctx:
                operation()
            self.assertEqual(ctx.exception.kind, kind)
        self.assertEqual(self.fs.read_file("/d/source.txt"), "source")

    def assert_aggregate_metadata(self) -> None:
        pending = [("", self.fs._root)]
        while pending:
            directory_path, directory = pending.pop()
            files = [
                (path, text)
                for path, text in self.fs._files.items()
                if not directory_path or path.startswith(directory_path + "/")
            ]
            directories = []
            children = [directory]
            while children:
                child = children.pop()
                for name, nested in child.directories.items():
                    directories.append(name)
                    children.append(nested)
            self.assertEqual(directory.file_count, len(files))
            self.assertEqual(
                directory.file_text_chars, sum(len(text) for _, text in files)
            )
            self.assertEqual(
                directory.file_path_chars, sum(len(path) for path, _ in files)
            )
            self.assertEqual(directory.directory_count, len(directories))
            self.assertEqual(
                directory.directory_name_chars,
                sum(len(name) for name in directories),
            )
            for name, child in directory.directories.items():
                pending.append((f"{directory_path}/{name}", child))

    def test_aggregate_metadata_tracks_write_copy_rename_and_delete(self) -> None:
        self.fs.write_file_trusted("/a/b/x.txt", "x")
        self.fs.write_file_trusted("/a/y.txt", "yy")
        self.assert_aggregate_metadata()
        self.fs.write_file_trusted("/a/y.txt", "longer")
        self.assert_aggregate_metadata()
        self.fs.copy_dir_trusted("/a", "/copy")
        self.assert_aggregate_metadata()
        self.fs.rename_dir_trusted("/copy/b", "/moved")
        self.assert_aggregate_metadata()
        self.fs.delete_dir("/copy")
        self.assert_aggregate_metadata()
        self.fs.delete_dir("/a")
        self.fs.delete_dir("/moved")
        self.assert_aggregate_metadata()
        self.assertEqual(self.fs.list_dir("/"), [])

    def test_copy_dir_recursively_copies_files_and_consumes_permit(self) -> None:
        self.fs.write_file_trusted("/source/a.txt", "a")
        self.fs.write_file_trusted("/source/nested/b.txt", "bb")
        amount = self.fs.copy_dir_allocation("/source", "/destination")
        permit = self.meter.reserve(self.fs, "write", amount)
        self.fs.copy_dir("/source", "/destination", permit=permit)
        self.assertTrue(permit.consumed)
        self.assertEqual(self.fs.read_file("/source/nested/b.txt"), "bb")
        self.assertEqual(self.fs.read_file("/destination/a.txt"), "a")
        self.assertEqual(self.fs.read_file("/destination/nested/b.txt"), "bb")
        self.assert_aggregate_metadata()

    def test_rename_dir_moves_whole_tree_without_extra_file_slots(self) -> None:
        self.fs.write_file_trusted("/old/a.txt", "a")
        self.fs.write_file_trusted("/old/nested/b.txt", "b")
        amount = self.fs.rename_dir_allocation("/old", "/new")
        permit = self.meter.reserve(self.fs, "write", amount)
        self.fs.rename_dir("/old", "/new", permit=permit)
        self.assertTrue(permit.consumed)
        self.assertFalse(self.fs.path_exists("/old"))
        self.assertEqual(self.fs.read_file("/new/a.txt"), "a")
        self.assertEqual(self.fs.read_file("/new/nested/b.txt"), "b")
        self.assert_aggregate_metadata()

    def test_directory_operations_reject_invalid_paths_atomically(self) -> None:
        self.fs.write_file_trusted("/tree/file.txt", "source")
        self.fs.write_file_trusted("/plain.txt", "plain")
        self.fs.write_file_trusted("/existing/file.txt", "existing")
        operations = (
            (lambda: self.fs.delete_dir("/missing"), "file_not_found"),
            (lambda: self.fs.delete_dir("/plain.txt"), "not_directory"),
            (lambda: self.fs.rename_dir_trusted("/plain.txt", "/new"), "not_directory"),
            (lambda: self.fs.copy_dir_trusted("/plain.txt", "/new"), "not_directory"),
            (lambda: self.fs.rename_dir_trusted("/tree", "/existing"), "file_exists"),
            (lambda: self.fs.copy_dir_trusted("/tree", "/plain.txt"), "file_exists"),
            (lambda: self.fs.rename_dir_trusted("/tree", "/tree/new"), "runtime_error"),
            (lambda: self.fs.copy_dir_trusted("/tree", "/tree/new"), "runtime_error"),
            (lambda: self.fs.delete_dir("/"), "runtime_error"),
            (lambda: self.fs.rename_dir_trusted("/tree", "/"), "runtime_error"),
            (lambda: self.fs.copy_dir_trusted("/tree", "/"), "runtime_error"),
        )
        for operation, kind in operations:
            with self.subTest(kind=kind), self.assertRaises(SericiteError) as ctx:
                operation()
            self.assertEqual(ctx.exception.kind, kind)
            self.assertEqual(self.fs.read_file("/tree/file.txt"), "source")
            self.assertEqual(self.fs.read_file("/plain.txt"), "plain")
            self.assertEqual(self.fs.read_file("/existing/file.txt"), "existing")
            self.assertFalse(self.fs.path_exists("/new"))
        self.assert_aggregate_metadata()

    def test_make_dir_creates_persistent_empty_directories(self) -> None:
        amount = self.fs.make_dir_allocation("/a/empty/nested")
        permit = self.meter.reserve(self.fs, "write", amount)
        self.fs.make_dir("/a/empty/nested", permit=permit)
        self.assertTrue(permit.consumed)
        self.assertEqual(self.fs.list_dir("/a/empty"), ["nested"])
        self.assertEqual(self.fs.list_dir("/a/empty/nested"), [])
        self.fs.write_file_trusted("/a/empty/file.txt", "x")
        self.fs.delete_file("/a/empty/file.txt")
        self.assertTrue(self.fs.path_exists("/a/empty"))
        self.assertTrue(self.fs.path_exists("/a/empty/nested"))
        self.assert_aggregate_metadata()

    def test_make_dir_rejects_existing_paths(self) -> None:
        self.fs.make_dir_trusted("/empty")
        self.fs.write_file_trusted("/file.txt", "x")
        for path in ("/empty", "/file.txt", "/"):
            with self.subTest(path=path), self.assertRaises(SericiteError) as ctx:
                self.fs.make_dir_trusted(path)
            self.assertEqual(ctx.exception.kind, "file_exists")

    def test_empty_directories_survive_copy_and_rename(self) -> None:
        self.fs.make_dir_trusted("/tree/empty/nested")
        self.fs.copy_dir_trusted("/tree", "/copy")
        self.assertTrue(self.fs.path_exists("/copy/empty/nested"))
        self.fs.rename_dir_trusted("/copy", "/moved")
        self.assertFalse(self.fs.path_exists("/copy"))
        self.assertEqual(self.fs.list_dir("/moved/empty"), ["nested"])
        self.fs.delete_dir("/moved/empty/nested")
        self.assertEqual(self.fs.list_dir("/moved/empty"), [])
        self.fs.delete_dir("/moved")
        self.fs.delete_dir("/tree")
        self.assertEqual(self.fs.list_dir("/"), [])
        self.assert_aggregate_metadata()

    def test_file_parent_conflicts_are_rejected_before_any_mutation(self) -> None:
        self.fs.write_file_trusted("/a", "parent file")
        self.fs.write_file_trusted("/source.txt", "source")
        self.fs.write_file_trusted("/tree/file.txt", "tree")
        operations = (
            lambda: self.fs.write_file_trusted("/a/b", "new"),
            lambda: self.fs.make_dir_trusted("/a/b"),
            lambda: self.fs.rename_file_trusted("/source.txt", "/a/b"),
            lambda: self.fs.copy_file_trusted("/source.txt", "/a/b"),
            lambda: self.fs.rename_dir_trusted("/tree", "/a/b"),
            lambda: self.fs.copy_dir_trusted("/tree", "/a/b"),
            lambda: self.fs.write_file_trusted("/a/b/c", "deep"),
            lambda: self.fs.make_dir_trusted("/a/b/c"),
        )
        for operation in operations:
            with (
                self.subTest(operation=operation),
                self.assertRaises(SericiteError) as ctx,
            ):
                operation()
            self.assertEqual(ctx.exception.kind, "not_directory")
            self.assertEqual(self.fs.read_file("/a"), "parent file")
            self.assertEqual(self.fs.read_file("/source.txt"), "source")
            self.assertEqual(self.fs.read_file("/tree/file.txt"), "tree")
            self.assertFalse(self.fs.path_exists("/a/b"))
            self.assertEqual(self.fs.list_dir("/"), ["a", "source.txt", "tree"])
        self.assert_aggregate_metadata()


if __name__ == "__main__":
    unittest.main()
