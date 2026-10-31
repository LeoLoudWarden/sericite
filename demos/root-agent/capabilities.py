"""Trusted host capabilities for the root-driven LLM agent demo."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from itertools import count
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from sericite import SericiteError, SericiteLimits

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
DOC_VFS_PATH = "/sericite语言特性速览.md"
MAX_FETCH_CHARS = 500_000
LOG_LLM = False
LOG_LLM_FULL_JSON = False
WAIT_LOG_INTERVAL = 15
TERMINAL_STYLES = {
    "root": "\x1b[1;94m",
    "model": "\x1b[1;95m",
    "vm": "\x1b[1;92m",
    "round": "\x1b[1;96m",
    "final": "\x1b[1;93m",
    "llm": "\x1b[1;91m",
}


def _terminal_style(text: str, color: str, stream) -> str:
    if not stream.isatty() or "NO_COLOR" in os.environ:
        return text
    return f"{TERMINAL_STYLES[color]}{text}\x1b[0m"


def terminal_style(text: str, color: str) -> str:
    return _terminal_style(text, color, sys.stdout)


def _log_line(message: str) -> None:
    if LOG_LLM:
        _log_warning(message)


def _log_warning(message: str) -> None:
    prefix = _terminal_style("LLM     │ ", "llm", sys.stderr)
    print(f"{prefix}{message}", file=sys.stderr, flush=True)


def _log_json(label: str, payload) -> None:
    if LOG_LLM and LOG_LLM_FULL_JSON:
        print(file=sys.stderr, flush=True)
        _log_warning(label)
        print(
            json.dumps(payload, ensure_ascii=False, indent=2),
            file=sys.stderr,
            flush=True,
        )


def _post_with_wait_log(call_id: int, **kwargs):
    stopped = threading.Event()

    def report_wait():
        waited = 0
        interval = WAIT_LOG_INTERVAL
        while not stopped.wait(interval):
            waited += interval
            _log_warning(f"call #{call_id} still waiting · {waited}s")
            if waited >= 60:
                interval = 60

    waiter = threading.Thread(target=report_wait, daemon=True)
    waiter.start()
    try:
        return requests.post(**kwargs)
    finally:
        stopped.set()
        waiter.join()


def _normalize_api_url(url: str) -> str:
    if urlparse(url).path in ("", "/"):
        return url.rstrip("/") + "/v1/chat/completions"
    return url


def make_llm_chat(api_url: str, api_key: str, model: str):
    call_ids = count(1)

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
        call_id = next(call_ids)
        _log_line(
            f"call #{call_id} request: model={model}, "
            f"messages={len(messages)}, tools={len(body.get('tools', []))}"
        )
        _log_json(f"call #{call_id} request", body)
        started = time.monotonic()
        resp = None
        for attempt in range(3):
            try:
                resp = _post_with_wait_log(
                    call_id,
                    url=api_url,
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=90,
                )
                break
            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                _log_warning(
                    f"call #{call_id} network error: {type(exc).__name__} "
                    f"(attempt {attempt + 1}/3)"
                )
                _log_json(
                    f"call #{call_id} network error",
                    {"attempt": attempt + 1, "error": type(exc).__name__},
                )
                if attempt == 2:
                    raise SericiteError(
                        "llm_chat: network failure after retries",
                        kind="runtime_error",
                    ) from None
        elapsed = time.monotonic() - started
        _log_json(
            f"call #{call_id} response metadata",
            {
                "http_status": resp.status_code,
                "elapsed_seconds": round(elapsed, 3),
            },
        )
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            _log_warning(f"HTTP {resp.status_code}: {resp.text[:500]}")
            raise SericiteError(
                f"llm_chat: HTTP {resp.status_code}", kind="runtime_error"
            ) from None
        data = resp.json()
        _log_json(f"call #{call_id} response body", data)
        raw_message = data["choices"][0]["message"]
        calls = []
        for raw_call in raw_message.get("tool_calls") or []:
            fn = raw_call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append({"id": raw_call["id"], "name": fn["name"], "args": args})
        content = raw_message.get("content") or ""
        _log_line(
            f"call #{call_id} response: HTTP {resp.status_code}, "
            f"{elapsed:.3f}s, content={len(content)} chars, tool_calls={len(calls)}"
        )
        assistant_message = {
            "role": "assistant",
            "content": content,
        }
        if calls:
            assistant_message["tool_calls"] = calls
        return {
            "content": content,
            "tool_calls": calls,
            "assistant_message": assistant_message,
        }

    return llm_chat


def make_http_get():
    def http_get(url):
        try:
            resp = requests.get(str(url), timeout=60)
        except requests.exceptions.RequestException:
            raise SericiteError(
                "http_get: network failure", kind="runtime_error"
            ) from None
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            _log_warning(f"http_get: HTTP {resp.status_code}: {url}")
            raise SericiteError(
                f"http_get: HTTP {resp.status_code}", kind="runtime_error"
            ) from None
        return resp.text[:MAX_FETCH_CHARS]

    return http_get


def configure():
    load_dotenv(os.environ.get("DEMO_ENV") or BASE_DIR / ".env")
    api_url = os.environ.get("API_URL")
    api_key = os.environ.get("API_KEY")
    model = os.environ.get("API_MODEL")
    if not (api_url and api_key and model):
        raise RuntimeError(
            "API_URL, API_KEY, and API_MODEL are required; "
            "set them in demos/root-agent/.env or the environment"
        )
    return {
        "limits": SericiteLimits(max_instructions=100_000_000),
        "functions": {
            "llm_chat": make_llm_chat(_normalize_api_url(api_url), api_key, model),
            "http_get": make_http_get(),
            "terminal_style": terminal_style,
        },
        "files": {
            "/control/prompt_outer.txt": (BASE_DIR / "prompt_outer.txt").read_text(
                encoding="utf-8"
            ),
            "/workspace/prompt_inner.txt": (BASE_DIR / "prompt_inner.txt").read_text(
                encoding="utf-8"
            ),
            "/workspace" + DOC_VFS_PATH: (
                PROJECT_ROOT / "docs" / "language-reference.zh-CN.md"
            ).read_text(encoding="utf-8"),
        },
    }
