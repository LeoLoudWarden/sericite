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


if __name__ == "__main__":
    unittest.main()
