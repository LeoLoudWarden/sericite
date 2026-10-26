from __future__ import annotations

import unittest

from sericite.accounting import Meter
from sericite.engine import SericiteEngine


class VirtualFileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SericiteEngine()
        self.engine.create_root("")
        self.context = self.engine._contexts[0]
        self.fs = self.context.fs
        self.meter = Meter(self.engine._account_routes[0])

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


if __name__ == "__main__":
    unittest.main()
