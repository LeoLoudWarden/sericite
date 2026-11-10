"""Local OpenAI-compatible stub for the complete root-agent harness.

The fixed conversation covers workspace files, run(path), imports, fresh module
loading, preserved failure artifacts, and a model-written child agent with an
independent workspace.

Run: uv run --extra demo demos/root-agent/mock_server.py (listens on 127.0.0.1:8399)
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTER_PROMPT = (BASE_DIR / "prompt_outer.txt").read_text(encoding="utf-8")

PRACTICE_CODE = """print("外层练习: fib")
a = 0
b = 1
for i in range(6):
    t = a + b
    a = b
    b = t
    print(a)
"""

INNER_PRACTICE_CODE = """print("内层练习: 写读文件")
write_file("/inner_note.txt", "来自最内层 VM 的笔记")
print(read_file("/inner_note.txt"))
for k in {"c": 3, "a": 1}:
    print("key:", k)
"""

MODULE_MAIN = """import greeting
print(greeting.message())
"""

FAILURE_CODE = """write_file("/failure_note.txt", "失败前写入的产物")
print("准备触发失败")
missing()
"""

CHILD_AGENT_CODE = """prompt_inner = read_file("/prompt_inner.txt")
doc = read_file("/sericite语言特性速览.md")

tools = [
    {"type": "function", "function": {"name": "file_read", "description": "读文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "file_write", "description": "写文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "file_list", "description": "列目录", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "run", "description": "运行入口文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]

messages = [{"role": "system", "content": prompt_inner}, {"role": "user", "content": "开始"}]
workspace = VFS()
workspace.write_file("/sericite语言特性速览.md", doc)

final = "(无结果)"
done = False
rounds = 0
while not done and rounds < 20:
    rounds = rounds + 1
    resp = llm_chat({"messages": messages, "tools": tools})
    messages = messages + [resp["assistant_message"]]
    calls = resp["tool_calls"]
    if len(calls) == 0:
        final = resp["content"]
        done = True
    else:
        for call in calls:
            name = call["name"]
            args = call["args"]
            result = "(未知工具)"
            if name == "file_read":
                try:
                    result = workspace.read_file(args["path"])
                except file_not_found:
                    result = "(文件不存在)"
            if name == "file_write":
                workspace.write_file(args["path"], args["content"])
                result = "(已写入)"
            if name == "file_list":
                result = ""
                for item in workspace.list_dir(args["path"]):
                    result = result + item + "\\n"
                if result == "":
                    result = "(空)"
            if name == "run":
                run = None
                try:
                    run = VM(entry_file=args["path"], fs=workspace)
                    result = run.run()
                except ... as e:
                    result = f"({e.kind}: {e.message})"
                finally:
                    if run != None:
                        if run.snapshot()["state"] == "waiting_input":
                            run.terminate()
                        workspace = run.take_fs()
                        run.dispose()
            print("[内层工具]", name, "->", result)
            messages = messages + [{"role": "tool", "tool_call_id": call["id"], "content": result}]

print("内层最终回答:", final)
"""

OUTER_FINAL = "外层收尾：练习完成，内层会话也跑完了。"


def _tool_call(index: int, name: str, args: dict) -> dict:
    return {
        "id": f"call_{index}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _reply(content: str = "", tool_calls: list | None = None) -> dict:
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


class Handler(BaseHTTPRequestHandler):
    outer_turn = 0
    inner_turn = 0

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        system = ""
        if body.get("messages"):
            system = body["messages"][0].get("content") or ""
        if system == OUTER_PROMPT:
            payload = self._outer_reply()
        else:
            payload = self._inner_reply()
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _outer_reply(self) -> dict:
        type(self).outer_turn += 1
        turn = type(self).outer_turn
        if turn == 1:
            return _reply(
                tool_calls=[
                    _tool_call(1, "file_read", {"path": "/sericite语言特性速览.md"}),
                    _tool_call(10, "file_list", {"path": "/"}),
                ]
            )
        if turn == 2:
            return _reply(
                tool_calls=[
                    _tool_call(
                        2,
                        "file_write",
                        {"path": "/practice.sericite", "content": PRACTICE_CODE},
                    ),
                    _tool_call(20, "run", {"path": "/practice.sericite"}),
                ]
            )
        if turn == 3:
            return _reply(
                tool_calls=[
                    _tool_call(
                        3,
                        "file_write",
                        {
                            "path": "/broken.sericite",
                            "content": "try:\n    pass\nexcept host_error:\n    pass",
                        },
                    ),
                    _tool_call(30, "run", {"path": "/broken.sericite"}),
                ]
            )
        if turn == 4:
            return _reply(
                tool_calls=[
                    _tool_call(
                        4,
                        "file_write",
                        {"path": "/failure.sericite", "content": FAILURE_CODE},
                    ),
                    _tool_call(40, "run", {"path": "/failure.sericite"}),
                    _tool_call(41, "file_read", {"path": "/failure_note.txt"}),
                ]
            )
        if turn == 5:
            return _reply(
                tool_calls=[
                    _tool_call(
                        5,
                        "file_write",
                        {
                            "path": "/project/greeting.sericite",
                            "content": "def message():\n    return 'module v1'\n",
                        },
                    ),
                    _tool_call(
                        50,
                        "file_write",
                        {
                            "path": "/project/module_main.sericite",
                            "content": MODULE_MAIN,
                        },
                    ),
                    _tool_call(51, "run", {"path": "/project/module_main.sericite"}),
                ]
            )
        if turn == 6:
            return _reply(
                tool_calls=[
                    _tool_call(
                        6,
                        "file_write",
                        {
                            "path": "/project/greeting.sericite",
                            "content": "def message():\n    return 'module v2'\n",
                        },
                    ),
                    _tool_call(60, "run", {"path": "/project/module_main.sericite"}),
                ]
            )
        if turn == 7:
            return _reply(
                tool_calls=[
                    _tool_call(
                        7,
                        "file_write",
                        {"path": "/child_agent.sericite", "content": CHILD_AGENT_CODE},
                    ),
                    _tool_call(70, "run", {"path": "/child_agent.sericite"}),
                ]
            )
        return _reply(content=OUTER_FINAL)

    def _inner_reply(self) -> dict:
        type(self).inner_turn += 1
        turn = type(self).inner_turn
        if turn == 1:
            return _reply(
                tool_calls=[
                    _tool_call(
                        101,
                        "file_write",
                        {"path": "/inner.sericite", "content": INNER_PRACTICE_CODE},
                    ),
                    _tool_call(110, "run", {"path": "/inner.sericite"}),
                ]
            )
        if turn == 2:
            return _reply(
                tool_calls=[
                    _tool_call(
                        102,
                        "file_write",
                        {
                            "path": "/nested/inner_module.sericite",
                            "content": "def message():\n    return 'inner module'\n",
                        },
                    ),
                    _tool_call(
                        103,
                        "file_write",
                        {
                            "path": "/nested/inner_main.sericite",
                            "content": "import inner_module\nprint(inner_module.message())\n",
                        },
                    ),
                    _tool_call(111, "run", {"path": "/nested/inner_main.sericite"}),
                ]
            )
        return _reply(content="内层练习完成：写了文件、跑了入口、使用了模块。")

    def log_message(self, *args) -> None:
        pass


def make_server(port: int = 8399) -> HTTPServer:
    Handler.outer_turn = 0
    Handler.inner_turn = 0
    return HTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    server = make_server()
    print("mock server on http://127.0.0.1:8399/v1/chat/completions")
    server.serve_forever()
