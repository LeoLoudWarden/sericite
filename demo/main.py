"""Demo: HTTP capability granting + multi-layer virtualized LLM code exec.

Structure:
  host Python ──(prompt 1)── LLM outer session
      │  tool_call: sericite_exec → runs in a freshly created sericite VM (granted llm_chat / http_get)
      ▼
  sericite code in the VM (AI-generated) ──(prompt 2)── LLM inner session
      │  tool_call: sericite_exec → runs in the next-level VM (no llm_chat granted, chain terminates)
      ▼
  sericite code in the inner VM (AI-generated, doing a simple exercise)

Run: configure .env first (API_URL / API_KEY / API_MODEL), then
  uv run --extra demo demo/main.py
Without a real API, verify the whole chain against the local stub server:
  uv run --extra demo demo/mock_server.py   # another terminal
  DEMO_ENV=demo/.env.mock uv run --extra demo demo/main.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sericite import SericiteEngine, SericiteError

DOC_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "language-reference.zh-CN.md"
)
DOC_VFS_PATH = "/sericite语言特性速览.md"
INNER_PROMPT_VFS_PATH = "/prompt_inner.txt"
MAX_RESULT_CHARS = 4000
MAX_ROUNDS = 30

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sericite_exec",
            "description": "在当前工作空间执行一段 sericite 代码，返回其标准输出。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "sericite 源码"}
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "读取工作目录中的一个文本文件。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "向工作目录写入一个文本文件（覆盖）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "列出工作目录中的文件。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]

API_HELP_URL = (
    "https://platform.kimi.com/docs/guide/use-kimi-api-to-complete-tool-calls.md"
)
MAX_FETCH_CHARS = 200_000

PROMPT_INNER = """你是一个有代码执行能力的助手。

你可以使用 sericite_exec 工具执行代码，以及 file_read / file_write / file_list 工具读写当前工作目录的文件。

工作目录里有一份 `sericite语言特性速览.md`，写任何 sericite 代码之前，先用 file_read 读完它并严格遵守——sericite 是 Python 的子集但有差异（没有字符串方法、没有 f-string、没有 import）。

任务：随便做点简单的事情作为练习，比如用 sericite_exec 算几个斐波那契数、写个文件再读出来验证。做完后给出简短的总结。"""

PROMPT1 = (
    """你是一个有代码执行能力的助手。

你可以使用 sericite_exec 工具执行代码（sericite 语言），以及 file_read / file_write / file_list 工具读写当前工作目录的文件。

工作目录里有一份 `sericite语言特性速览.md`，写任何 sericite 代码之前，先用 file_read 读完它并严格遵守——sericite 是 Python 的子集但有差异（没有字符串方法、没有 f-string、没有 import）。

请完成两件事：

1. 练习：用 sericite_exec 随便做点简单的事情（比如算几个斐波那契数并打印）。

2. 递归任务：你的 sericite 执行环境额外被授予了两个函数：llm_chat(payload) 和 http_get(url)。用它们实现一个完整的 LLM 会话循环：
   - llm_chat 的入参是 dict：{"messages": [...], "tools": [...]}，返回 dict：
     {"content": 字符串, "tool_calls": [{"id":..., "name":..., "args": {...}}],
      "assistant_message": {...}}
   - http_get 的入参是 url 字符串，返回该网址的文本内容（用于获取资料）。
   - 把 resp["assistant_message"] 原样追加进 messages；每个工具结果用
     {"role": "tool", "tool_call_id": 调用id, "content": 结果字符串} 追加。
   - 会话的系统提示词用 file 里的 /prompt_inner.txt（read_file 读取）。
   - tools 用和你自己一样的四个工具（sericite_exec / file_read / file_write / file_list）。
     如果你不确定 tools 的 schema 写法，不要凭记忆手写——先用 http_get 从
     """
    + API_HELP_URL
    + """
     获取帮助文本（OpenAI 兼容 API 的 tool_calls 协议说明，Markdown 纯文本），照着它写。
   - 对方调用 sericite_exec 时：创建一个新 VM 执行（VM(code)），并先 write_file 把 `sericite语言特性速览.md` 放进它的工作目录。不要给这些 VM 授予任何 functions。
   - 对方调用 file_read / file_write / file_list 时：直接用你环境里的 read_file / write_file / list_dir 处理（共享当前工作目录）。
   - 循环直到对方不再调用工具（tool_calls 为空列表），把对方的最终回答 print 出来。
   - 所有文件内容都用 read_file 读出来后嵌入，不要凭记忆复述。

把这个会话循环写进一次 sericite_exec 里执行。注意 sericite 没有 try 之外的容错，代码尽量朴素。"""
)


def _normalize_api_url(url: str) -> str:
    """Allow API_URL to be a base address (e.g. http://host:8080/); append the standard endpoint path automatically."""
    from urllib.parse import urlparse

    if urlparse(url).path in ("", "/"):
        return url.rstrip("/") + "/v1/chat/completions"
    return url


def make_llm_chat(api_url: str, api_key: str, model: str):
    """Build the llm_chat granted to the VM: send the request + normalize the tool_calls shape in both directions."""

    def llm_chat(payload):
        body = {"model": model}
        messages = []
        for message in payload["messages"]:
            message = dict(message)
            calls = message.get("tool_calls")
            if calls and isinstance(calls[0], dict) and "name" in calls[0]:
                message["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["args"], ensure_ascii=False),
                        },
                    }
                    for call in calls
                ]
            messages.append(message)
        body["messages"] = messages
        if "tools" in payload:
            body["tools"] = payload["tools"]
        resp = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    api_url,
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=600,
                )
                break
            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ):
                if attempt == 2:
                    raise
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            # Operator-side diagnostics: the script only sees the sanitized ffi_error; details go to stderr
            print(
                f"[llm_chat 错误] {resp.status_code}: {resp.text[:500]}",
                file=sys.stderr,
            )
            raise
        data = resp.json()
        raw_message = data["choices"][0]["message"]
        calls = []
        for raw_call in raw_message.get("tool_calls") or []:
            fn = raw_call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append({"id": raw_call["id"], "name": fn["name"], "args": args})
        assistant_message = {
            "role": "assistant",
            "content": raw_message.get("content") or "",
        }
        if calls:
            assistant_message["tool_calls"] = calls
        return {
            "content": raw_message.get("content") or "",
            "tool_calls": calls,
            "assistant_message": assistant_message,
        }

    return llm_chat


def make_http_get():
    """Build the http_get granted to the VM: fetch a URL's text content (for looking things up)."""

    def http_get(url):
        resp = requests.get(str(url), timeout=60)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            print(
                f"[http_get 错误] {resp.status_code}: {url}",
                file=sys.stderr,
            )
            raise
        return resp.text[:MAX_FETCH_CHARS]

    return http_get


def harvest(vm, workspace: dict[str, str], prefix: str = "/") -> None:
    """Collect the files from the VM's file system back into the workspace."""
    for name in vm.list_dir(prefix):
        path = prefix.rstrip("/") + "/" + name
        try:
            workspace[path] = vm.read_file(path)
        except SericiteError as exc:
            if exc.kind == "is_directory":
                harvest(vm, workspace, path)
            else:
                raise


def _norm_path(path: str) -> str:
    if not path or path == ".":
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def make_host_handler(llm_chat, http_get, seed_files: dict[str, str]):
    workspace: dict[str, str] = {}

    def handler(name: str, args: dict) -> str:
        if name == "sericite_exec":
            code = args.get("code", "")
            engine = SericiteEngine()
            try:
                vm = engine.create_root(
                    code,
                    functions={"llm_chat": llm_chat, "http_get": http_get},
                )
                for path, text in {**seed_files, **workspace}.items():
                    vm.write_file(path, text)
                output = vm.run()
            except SericiteError as exc:
                # Feed compile/run errors back as tool results so the model can fix the code and retry
                return f"(sericite error: {exc})"
            harvest(vm, workspace)
            return output[:MAX_RESULT_CHARS] or "(no output)"
        if name == "file_read":
            path = _norm_path(args.get("path", ""))
            if path in workspace:
                return workspace[path]
            if path in seed_files:
                return seed_files[path]
            return f"(no such file: {path})"
        if name == "file_write":
            workspace[_norm_path(args["path"])] = args["content"]
            return "(written)"
        if name == "file_list":
            prefix = _norm_path(args.get("path", "/")).rstrip("/") + "/"
            names = {
                path[len(prefix) :].split("/", 1)[0]
                for path in [*workspace, *seed_files]
                if path.startswith(prefix)
            }
            return "\n".join(sorted(names)) or "(empty)"
        return f"(unknown tool: {name})"

    return handler


def run_session(
    llm_chat, system_prompt: str, user_prompt: str, handler, label: str
) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    for round_index in range(MAX_ROUNDS):
        resp = llm_chat({"messages": messages, "tools": TOOLS})
        if resp["content"]:
            print(f"[{label} 第{round_index + 1}轮] {resp['content'][:300]}")
        messages.append(resp["assistant_message"])
        if not resp["tool_calls"]:
            return resp["content"]
        for call in resp["tool_calls"]:
            print(
                f"[{label} 工具调用] {call['name']}({json.dumps(call['args'], ensure_ascii=False)[:120]})"
            )
            result = handler(call["name"], call["args"])
            # print(f"[{label} 工具结果] {result[:300]}")
            print(f"[{label} 工具结果] {result}")
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": result}
            )
    return "(达到最大轮数)"


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(os.environ.get("DEMO_ENV") or ".env")
    api_url = os.environ.get("API_URL")
    api_key = os.environ.get("API_KEY")
    model = os.environ.get("API_MODEL")
    if not (api_url and api_key and model):
        print(
            "缺少配置：需要 API_URL / API_KEY / API_MODEL（写入 .env 或设置环境变量）"
        )
        print(
            "没有真实 API 时，可先运行 demo/mock_server.py，再用 DEMO_ENV=demo/.env.mock 启动"
        )
        sys.exit(1)

    llm_chat = make_llm_chat(_normalize_api_url(api_url), api_key, model)
    seed_files = {
        DOC_VFS_PATH: DOC_PATH.read_text(encoding="utf-8"),
        INNER_PROMPT_VFS_PATH: PROMPT_INNER,
    }
    handler = make_host_handler(llm_chat, make_http_get(), seed_files)
    final = run_session(llm_chat, PROMPT1, "开始吧", handler, label="外层")
    print("\n=== 外层会话最终回答 ===")
    print(final)


if __name__ == "__main__":
    main()
