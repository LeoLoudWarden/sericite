# root-agent: a multi-layer LLM application driven by root Sericite

[中文](README.zh-CN.md)

This demo is a multi-layer LLM application driven by a root Sericite program. **Root runs the outer LLM session**: it builds messages/tools, reads the outer prompt, sends requests, and dispatches tools. Python only supplies two host functions, `llm_chat` / `http_get`, plus the initial root VFS files through `configure()`.

## Runtime structure

- **Outer session**: root keeps one persistent first-level VM for the whole session, grants it those two host functions, and seeds the model workspace at startup.
- **First-level VM**: when the outer model calls `sericite_exec`, root delivers the code to that VM with `exec`. Module variables, definitions, and files survive across calls; model-generated code can use `llm_chat` to start its own inner session.
- **Second-level VM**: when that session calls `sericite_exec`, model-written code maintains a second-level VM. It receives no host functions, so it has no network access, and the recursion ends there. The inner session and its VM management are written by the model, not supplied as another prewritten agent.

## Files and prompt boundary

- Root VFS is divided into `/control` and `/workspace`: the outer prompt stays in control, and the workspace seeds the execution VM once at startup.
- The model's file tools operate on the persistent VM's filesystem directly, so files written by `sericite_exec` code and by `file_write` live in one place with no re-seeding or harvesting.
- Prompts tell the model that it can create VMs, not that its own code and files are already inside one.

## Run

From the repository root, install the demo extra:

```bash
uv sync --extra demo
```

Copy `.env.example` to `.env` in this directory and configure the OpenAI-compatible `API_URL` / `API_KEY` / `API_MODEL`, then run:

```bash
uv run --extra demo sericite \
  --capabilities demos/root-agent/capabilities.py \
  demos/root-agent/agent.sericite
```

`DEMO_ENV` can select another environment file. Never commit API keys; for the capability file's trust boundary, see the [CLI reference](../../docs/cli-reference.md) §4.2.

## Full verification without a real API

Start the local stub in one terminal:

```bash
uv run --extra demo demos/root-agent/mock_server.py
```

Run the same root application in another:

```bash
API_URL=http://127.0.0.1:8399/v1/chat/completions API_KEY=mock API_MODEL=mock \
  uv run --extra demo sericite \
  --capabilities demos/root-agent/capabilities.py \
  demos/root-agent/agent.sericite
```

The stub follows a fixed script as the outer and inner models, covering the complete root → child inner session → deeper VM exercise chain. It proves repeatability, not that every real model can generate equivalent code. `tests/test_demos.py` runs this chain automatically on a temporary port.

## Live display and logs

Default stdout shows only the execution story: one heading per outer round, compact tool summaries, and live `vm 1` output. It does not dump file contents or source, or print a second copy of the output returned by `sericite_exec`. Display summaries never truncate the actual tool arguments or results sent to the model.

### Tool-result truncation

- Short `sericite_exec` results are returned unchanged.
- A result longer than `MAX_RESULT_CHARS` (4000) characters returns only the first 4000 characters, with advice appended to write the full text with `write_file` and then read it with `file_read`.
- On a repeated truncation, the advice escalates to an explicit warning: do not print or rerun the large output again; use `write_file` plus `file_read`.
- This is deliberate progressive feedback from the execution environment, independent of live-output folding; the prompts do not teach this recovery strategy in advance.

### Live output

- Root `print()` output is forwarded live by the CLI.
- The first-level VM forwards its own output through root with an `output_writer`, so model-generated progress appears during execution.
- By default, output is printed as readable lines with a `vm 1` prefix.
- Each `sericite_exec` shows at most its first `MAX_LIVE_LINES` (8) lines; when folding occurs, it ends with a size summary and the last `LIVE_TAIL_LINES` (3) lines.
- Lines longer than `MAX_LIVE_LINE_CHARS` (240) characters are shortened.
- Append `--verbose` after `agent.sericite` to show complete output and full tool arguments/results; tool arguments and results use `repr`.
- Neither display path changes the raw tool results sent back to the model.
- The first-level VM keeps stdout buffered because `sub.exec()` still returns that text as the `sericite_exec` tool result; see the [VM reference](../../docs/vm-reference.md) §4 for buffering semantics.

```bash
uv run --extra demo sericite \
  --capabilities demos/root-agent/capabilities.py \
  demos/root-agent/agent.sericite --verbose
```

### stderr logging

Two constants at the top of `capabilities.py` control low-level **stderr** logging:

```python
LOG_LLM = False
LOG_LLM_FULL_JSON = False
```

Set `LOG_LLM = True` to print one summary line per call, containing:

- call number and model;
- message and tool counts;
- HTTP status and elapsed time;
- response text length and tool-call count.

Set `LOG_LLM_FULL_JSON = True` as well to include complete request/response JSON. Logs flush immediately and never record Authorization headers or API keys.

Slow requests and network problems remain visible even when low-level logging is off:

- a waiting notice appears every 15 seconds for the first minute, then once per minute;
- each attempt times out after 90 seconds and is retried up to three times;
- retries and HTTP errors are always reported.

Full JSON contains prompts, model-generated code, and tool results; review it before sharing. Use `2>llm.log` to save stderr separately.

## Files and responsibilities

- `agent.sericite`: the only Sericite application body, namely the root environment. It implements the outer session loop, dispatches four model tools (`sericite_exec` / `file_read` / `file_write` / `file_list`), and maintains the `/control` versus `/workspace` boundary.
- `capabilities.py`: trusted host adapter. It loads the environment, performs HTTP requests and protocol normalization, and returns `functions`, a demo-specific instruction budget, and initial root VFS files through `configure()`. It has no application session loop.
- `prompt_outer.txt` / `prompt_inner.txt`: prompts for the two model sessions. The outer prompt stays in root control; the inner prompt is seeded into the model workspace and is not told to grant recursive capabilities onward.
- `mock_server.py`: local OpenAI-compatible stub.
- `.env.example`: environment template.

`requests` and `python-dotenv` belong only to the `demo` extra, not to the engine or base CLI. See the [CLI reference](../../docs/cli-reference.md) for general options, includes, exit codes, and trust boundaries. To let an existing Python system own VM lifecycles, use the embedding API in the [Sericite-PY reference](../../docs/sericite-py-reference.md).
