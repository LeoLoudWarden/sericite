import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_ROOT = PROJECT_ROOT / "demos" / "sorting-arena"


class SortingArenaDemoTests(unittest.TestCase):
    def test_arena_runs_entries_and_survives_disruptive_submissions(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sericite",
                "--capabilities",
                str(DEMO_ROOT / "capabilities.py"),
                str(DEMO_ROOT / "arena.sericite"),
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=60,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("SERICITE / SORTING ARENA", result.stdout)
        self.assertIn("9 submissions · 4 test cases", result.stdout)
        self.assertIn("Fresh random cases from Python random_int", result.stdout)
        self.assertIn("→ qualified · ", result.stdout)
        self.assertEqual(result.stdout.count("→ qualified · "), 3)
        self.assertIn("wrong_answer", result.stdout)
        self.assertIn("file_not_found", result.stdout)
        self.assertEqual(result.stdout.count("resource_exhausted"), 6)
        self.assertIn("DQ    output-flood", result.stdout)
        self.assertIn("DQ    infinite-loop", result.stdout)
        self.assertIn("DQ    vm-spawner", result.stdout)
        self.assertIn("DQ    input                   input_error", result.stdout)
        self.assertIn("The arena survived every submission.", result.stdout)
        self.assertNotIn("Traceback", result.stdout)


if __name__ == "__main__":
    unittest.main()
