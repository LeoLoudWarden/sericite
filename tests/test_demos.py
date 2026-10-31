import importlib.util
import os
import subprocess
import sys
import threading
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_ROOT = PROJECT_ROOT / "demos" / "root-agent"


class RootAgentDemoTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "sericite_demo_mock_server", DEMO_ROOT / "mock_server.py"
        )
        self.mock = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mock)
        self.server = self.mock.make_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def run_agent(self, *args):
        env = os.environ.copy()
        env.update(
            {
                "API_URL": (
                    f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"
                ),
                "API_KEY": "mock",
                "API_MODEL": "mock",
            }
        )
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "sericite",
                "--capabilities",
                str(DEMO_ROOT / "capabilities.py"),
                str(DEMO_ROOT / "agent.sericite"),
                *args,
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            env=env,
            timeout=60,
            check=False,
        )

    def test_root_agent_runs_full_chain_through_cli(self):
        result = self.run_agent()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ROUND   │ outer session 1", result.stdout)
        self.assertIn("ROOT    │ file_read /sericite语言特性速览.md", result.stdout)
        self.assertIn("chars · full result sent to model", result.stdout)
        self.assertIn("VM 1    │ 外层练习: fib", result.stdout)
        self.assertIn("内层练习: 写读文件", result.stdout)
        self.assertIn("来自最内层 VM 的笔记", result.stdout)
        self.assertIn("内层最终回答: 内层练习完成", result.stdout)
        self.assertIn("FINAL   │ 外层收尾", result.stdout)
        self.assertNotIn("# Sericite 语言参考", result.stdout)
        self.assertNotIn("/control", result.stdout)
        self.assertEqual(result.stdout.count("外层练习: fib"), 1)
        self.assertEqual(result.stdout.count("(syntax_error:"), 1)
        self.assertEqual(
            result.stdout.count("外层收尾：练习完成，内层会话也跑完了。"), 1
        )
        self.assertEqual(self.mock.Handler.outer_turn, 5)
        self.assertEqual(self.mock.Handler.inner_turn, 2)

    def test_large_live_output_is_folded(self):
        payload = "\n".join(f"line {i}: " + "x" * 300 for i in range(40))
        self.mock.PRACTICE_CODE = f'print("""{payload}""")'
        result = self.run_agent()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"display folded · {len(payload) + 1} chars / 40 lines total",
            result.stdout,
        )
        self.assertIn("ROOT    │ ↳ output truncated · ", result.stdout)
        self.assertIn("suggested write_file + file_read", result.stdout)
        self.assertIn("VM 1    │ line 0:", result.stdout)
        self.assertIn("VM 1    │ line 39:", result.stdout)
        self.assertNotIn("VM 1    │ line 25:", result.stdout)

    def test_final_response_is_never_folded_or_shortened(self):
        payload = "\n".join(f"final line {i}: " + "x" * 300 for i in range(40))
        self.mock.OUTER_FINAL = payload
        result = self.run_agent()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("FINAL   │ … display folded", result.stdout)
        self.assertIn("FINAL   │ final line 0:", result.stdout)
        self.assertIn("FINAL   │ final line 25:", result.stdout)
        self.assertIn("FINAL   │ final line 39:", result.stdout)
        self.assertIn("x" * 300, result.stdout)

    def test_verbose_mode_does_not_fold_live_output(self):
        payload = "\n".join(f"line {i}: " + "x" * 300 for i in range(40))
        self.mock.PRACTICE_CODE = f'print("""{payload}""")'
        result = self.run_agent("--verbose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("display folded", result.stdout)
        self.assertIn("VM 1    │ line 25:", result.stdout)
        self.assertIn("ROOT    │ arg code = ", result.stdout)
        self.assertIn("[提示：本次输出共 ", result.stdout)
        self.assertIn("再使用 file_read 工具读取。", result.stdout)

    def test_repeated_truncation_returns_stronger_advice(self):
        payload = "\n".join(f"line {i}: " + "x" * 300 for i in range(40))
        self.mock.PRACTICE_CODE = f'print("""{payload}""")'
        self.mock.INNER_PRACTICE_CODE = f'print("""{payload}""")'
        result = self.run_agent("--verbose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[提示：本次输出共 ", result.stdout)
        self.assertIn("[再次截断：本次输出共 ", result.stdout)
        self.assertIn("请不要重复打印或重跑大段输出", result.stdout)


class TerminalStyleTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "sericite_demo_capabilities", DEMO_ROOT / "capabilities.py"
        )
        self.capabilities = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.capabilities)

    def test_styles_only_a_tty_and_honors_no_color(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys.stdout, "isatty", return_value=True),
        ):
            self.assertEqual(
                self.capabilities.terminal_style("ROOT", "root"),
                "\x1b[1;94mROOT\x1b[0m",
            )
        with (
            mock.patch.dict(os.environ, {"NO_COLOR": "1"}),
            mock.patch.object(sys.stdout, "isatty", return_value=True),
        ):
            self.assertEqual(self.capabilities.terminal_style("ROOT", "root"), "ROOT")
        with mock.patch.object(sys.stdout, "isatty", return_value=False):
            self.assertEqual(self.capabilities.terminal_style("ROOT", "root"), "ROOT")

    def test_stderr_style_uses_stderr_tty(self):
        stderr = StringIO()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(stderr, "isatty", return_value=True),
        ):
            self.assertEqual(
                self.capabilities._terminal_style("LLM", "llm", stderr),
                "\x1b[1;91mLLM\x1b[0m",
            )


class LlmChatLoggingTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "sericite_demo_capabilities", DEMO_ROOT / "capabilities.py"
        )
        self.capabilities = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.capabilities)

    def run_chat(self) -> str:
        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        }
        stderr = StringIO()
        with (
            mock.patch.object(
                self.capabilities.requests, "post", return_value=response
            ),
            redirect_stderr(stderr),
        ):
            chat = self.capabilities.make_llm_chat("http://example.test", "secret", "m")
            result = chat({"messages": []})
        self.assertEqual(result["content"], "ok")
        return stderr.getvalue()

    def test_full_json_mode(self):
        self.capabilities.LOG_LLM = True
        self.capabilities.LOG_LLM_FULL_JSON = True
        output = self.run_chat()
        self.assertIn('"messages": []', output)
        self.assertIn("response metadata", output)
        self.assertIn("response body", output)
        self.assertNotIn("Authorization", output)
        self.assertNotIn("secret", output)

    def test_logging_can_be_disabled(self):
        self.capabilities.LOG_LLM = False
        self.assertEqual(self.run_chat(), "")

    def test_slow_request_reports_wait_while_logging_is_disabled(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        }

        def slow_post(**kwargs):
            threading.Event().wait(0.055)
            return response

        self.capabilities.WAIT_LOG_INTERVAL = 0.02
        stderr = StringIO()
        with (
            mock.patch.object(
                self.capabilities.requests, "post", side_effect=slow_post
            ),
            redirect_stderr(stderr),
        ):
            chat = self.capabilities.make_llm_chat("http://example.test", "secret", "m")
            result = chat({"messages": []})
        self.assertEqual(result["content"], "ok")
        self.assertIn("LLM     │ call #1 still waiting · ", stderr.getvalue())

    def test_network_retries_are_visible_while_logging_is_disabled(self):
        stderr = StringIO()
        with (
            mock.patch.object(
                self.capabilities.requests,
                "post",
                side_effect=self.capabilities.requests.exceptions.ConnectionError(),
            ),
            redirect_stderr(stderr),
        ):
            chat = self.capabilities.make_llm_chat("http://example.test", "secret", "m")
            with self.assertRaises(Exception) as caught:
                chat({"messages": []})
        self.assertEqual(caught.exception.kind, "runtime_error")
        self.assertEqual(stderr.getvalue().count("network error: ConnectionError"), 3)
        self.assertIn("attempt 3/3", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
