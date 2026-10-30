import re
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_ROOT = PROJECT_ROOT / "demos" / "sericite-debugger"
DEBUGGER = DEMO_ROOT / "debugger.sericite"

CONTRACT_PROGRAM = """class Account:
    balance: int

account = Account(100)
deposit = 40
account.balance = account.balance + deposit
print("after deposit", account)
account.balance = "unlimited"
"""

CLOSURE_PROGRAM = """def make_readers():
    late = []
    early = []
    for value in range(3):
        def read_late():
            return value
        def read_early(captured=value):
            return captured
        late.append(read_late)
        early.append(read_early)
    return {"late": late, "early": early}

readers = make_readers()
print("late:", readers["late"][0](), readers["late"][1](), readers["late"][2]())
print("early:", readers["early"][0](), readers["early"][1](), readers["early"][2]())
"""

QUOTA_PROGRAM = """def run_job():
    job = VM("while True: pass", max_instructions=40)
    try:
        job.run()
    except resource_exhausted as error:
        print("child stopped:", error.kind)
    finally:
        job.dispose()
    return "parent still running"

status = run_job()
print(status)
"""

INPUT_PROGRAM = 'name = input()\nprint("hello", name)\n'


class SericiteDebuggerDemoTests(unittest.TestCase):
    def run_debugger(
        self, source, debugger_input="", target_input=None, target_args=None
    ):
        command = [sys.executable, "-m", "sericite", str(DEBUGGER), source]
        if target_input is not None or target_args:
            command.append(target_input or "")
        if target_args:
            command.extend(target_args)
        result = subprocess.run(
            command,
            input=debugger_input,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("Traceback", result.stdout)
        return result.stdout

    def test_watchpoint_pauses_on_record_changes_and_shows_error_scene(self):
        output = self.run_debugger(CONTRACT_PROGRAM, "w account\nc\nc\nc\n")
        self.assertEqual(output.count("watchpoint hit · account"), 2)
        self.assertIn("after:  {'<record>': {'balance': 100}}", output)
        self.assertIn("before: {'<record>': {'balance': 100}}", output)
        self.assertIn("after:  {'<record>': {'balance': 140}}", output)
        self.assertIn("state error", output)
        self.assertIn("contract_error: field balance: expected int, got str", output)
        self.assertIn("!   9  account.balance", output)
        self.assertIn("after deposit record(balance=140)", output)
        self.assertIn("session ended · error", output)

    def test_statement_and_instruction_step_have_distinct_granularity(self):
        output = self.run_debugger(CONTRACT_PROGRAM, "\ni\nq\n")
        counts = [int(value) for value in re.findall(r"instructions (\d+)", output)]
        self.assertGreaterEqual(len(counts), 4)
        self.assertEqual(counts[0], 0)
        self.assertGreater(counts[1], counts[0])
        self.assertGreater(counts[2], counts[1])
        self.assertIn("last 3 → next 2", output)
        self.assertNotIn("Account =", output)
        self.assertIn("session ended · terminated", output)

    def test_watchpoint_enters_function_frame(self):
        output = self.run_debugger(CLOSURE_PROGRAM, "w value\nc\nq\n")
        self.assertEqual(output.count("watchpoint hit · value"), 1)
        self.assertIn("after:  0", output)
        self.assertIn("value = 0", output)
        self.assertIn("session ended · terminated", output)

    def test_subject_catches_child_quota_error(self):
        output = self.run_debugger(QUOTA_PROGRAM, "r\n")
        self.assertIn("child stopped: resource_exhausted", output)
        self.assertIn("parent still running", output)
        self.assertIn("state done", output)
        self.assertIn("session ended · done", output)

    def test_waiting_target_can_be_fed_interactively(self):
        output = self.run_debugger(INPUT_PROGRAM, "\n\nAda\nr\n")
        self.assertIn("[child stdin]", output)
        self.assertIn("hello Ada", output)
        self.assertIn("session ended · done", output)

    def test_target_argv_is_explicitly_constructed(self):
        output = self.run_debugger(
            "print(argv)\n", "r\n", target_args=["alpha", "beta"]
        )
        self.assertIn("['<target>', 'alpha', 'beta']", output)
        self.assertIn("session ended · done", output)

    def test_debugger_can_debug_itself_debugging_another_program(self):
        output = self.run_debugger(
            DEBUGGER.read_text(encoding="utf-8"),
            "r\n",
            target_input="r\n",
            target_args=[INPUT_PROGRAM, "Sericite\n"],
        )
        self.assertIn("hello Sericite", output)
        self.assertIn("│ session ended · done", output)
        self.assertIn("session ended · done", output)
        self.assertIn("state done", output)

    def test_continue_stops_at_target_quota_without_exhausting_debugger(self):
        for commands in ("c\n", "w missing\nc\n"):
            with self.subTest(commands=commands):
                output = self.run_debugger("while True:\n    pass\n", commands)
                self.assertIn("state resource_exhausted", output)
                self.assertIn("session ended · resource_exhausted", output)

    def test_target_syntax_error_exits_cleanly(self):
        output = self.run_debugger('if True print("bad")\n')
        self.assertIn("target syntax_error: invalid syntax", output)

    def test_target_with_live_child_does_not_break_cleanup(self):
        output = self.run_debugger('child = VM("pass")\n', "r\n")
        self.assertIn("session ended · done", output)
        self.assertNotIn("cannot dispose", output)

    def test_eof_exits_cleanly(self):
        output = self.run_debugger("print('unused')\n")
        self.assertIn("input closed", output)
        self.assertNotIn("input_error", output)


if __name__ == "__main__":
    unittest.main()
