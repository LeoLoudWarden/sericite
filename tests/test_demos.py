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

    def test_root_agent_runs_full_chain_through_cli(self):
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
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sericite",
                "--capabilities",
                str(DEMO_ROOT / "capabilities.py"),
                str(DEMO_ROOT / "agent.sericite"),
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            env=env,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("外层练习: fib", result.stdout)
        self.assertIn("内层练习: 写读文件", result.stdout)
        self.assertIn("来自最内层 VM 的笔记", result.stdout)
        self.assertIn("内层最终回答: 内层练习完成", result.stdout)
        self.assertIn("外层收尾：练习完成，内层会话也跑完了。", result.stdout)
        self.assertNotIn("prompt_outer.txt", result.stdout)
        self.assertNotIn("/control", result.stdout)
        self.assertEqual(result.stdout.count("(sericite execution failed)"), 1)
        self.assertEqual(self.mock.Handler.outer_turn, 5)
        self.assertEqual(self.mock.Handler.inner_turn, 2)
        self.assertIn("[llm_chat] call #1 request: model=mock", result.stderr)
        self.assertIn("messages=2, tools=4", result.stderr)
        self.assertIn("response: HTTP 200", result.stderr)
        self.assertNotIn("response body", result.stderr)
        self.assertNotIn("Authorization", result.stderr)


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


if __name__ == "__main__":
    unittest.main()
