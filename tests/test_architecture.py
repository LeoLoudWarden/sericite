from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "sericite"


class AccountingArchitectureTests(unittest.TestCase):
    def test_legacy_accounting_entry_points_do_not_exist(self) -> None:
        tree = ast.parse((SOURCE / "engine.py").read_text(encoding="utf-8"))
        definitions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertFalse(
            {"_charge_work", "_charge_alloc", "_mirror_charge"} & definitions
        )

    def test_only_accounting_writes_instruction_and_allocation_ledgers(self) -> None:
        violations = []
        for path in SOURCE.glob("*.py"):
            if path.name == "accounting.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.AugAssign):
                    continue
                if isinstance(node.target, ast.Attribute) and node.target.attr in {
                    "instruction_count",
                    "alloc_bytes",
                }:
                    violations.append(f"{path.name}:{node.lineno}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
