# root-agent: a multi-layer LLM application driven by root Sericite

[中文](README.zh-CN.md)

This demo is a multi-layer LLM application whose root environment is Sericite itself. **Root runs the outer LLM session**: it builds messages/tools, reads the outer prompt, sends requests, and dispatches tools. Python only supplies `llm_chat` / `http_get` and root VFS initialization through `configure()`.

- **Outer session**: root keeps one persistent first-level VM for the whole session, granted those two functions and seeded once with the model workspace.
- **First-level VM**: when the outer model calls `sericite_exec`, root delivers the code to that VM with `exec` — module variables, definitions, and files survive across calls. Model-generated code runs freely there and can use `llm_chat` to start its own inner session.
- **Second-level VM**: when that session calls `sericite_exec`, model-written code maintains a second-level VM without network grants, terminating the recursion. The inner session and its VM management are written by the model, not supplied as another prewritten agent.

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

`DEMO_ENV` can select another environment file. Trust the capability file as Python code with full host privileges, and never commit API keys.

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

## Live logs

Two constants at the top of `capabilities.py` control **stderr** logging:

```python
LOG_LLM = True
LOG_LLM_FULL_JSON = False
```

`LOG_LLM` is the master switch. By default, one compact line per call reports:

- call number and model;
- message/tool counts;
- HTTP status and elapsed time;
- response text length and tool-call count.

Network retries are also logged. Set `LOG_LLM_FULL_JSON = True` to include complete request/response JSON as well. Logs flush immediately and never record Authorization headers or API keys.

Full JSON contains prompts, model-generated code, and tool results; review it before sharing. Use `2>llm.log` to save it separately.

Progress is also visible live:

- Root `print()` output is forwarded live by the CLI.
- The first-level VM forwards its own output through root with an `output_writer`, so model-generated progress appears during execution.
- Live output, tool arguments, and tool results are displayed with `repr`, keeping multiline text on a single log line without changing the raw tool results sent back to the model.
- The first-level VM keeps stdout buffered because `sub.exec()` still returns that text as the `sericite_exec` tool result.

## Files and responsibilities

- `agent.sericite`: the only handwritten application, namely the root environment; runs the outer LLM session, dispatches four tools against one persistent first-level execution VM, and maintains the `/control` versus `/workspace` boundary.
- `capabilities.py`: trusted host adapter; environment loading, HTTP and protocol normalization, and `configure()` returning functions, a demo-specific instruction budget, and initial root VFS files. It has no application session loop.
- `prompt_outer.txt` / `prompt_inner.txt`: prompts for the two model sessions; the outer prompt stays in root control, while the inner prompt is seeded into the model workspace; the inner session is not told to grant recursive capabilities onward.
- `mock_server.py`: local OpenAI-compatible stub.
- `.env.example`: environment template.

`requests` and `python-dotenv` belong only to the `demo` extra, not to the engine or base CLI. See the [CLI reference](../../docs/cli-reference.md) for general options, includes, exit codes, and trust boundaries. To let an existing Python system own VM lifecycles, use the embedding API in the [Sericite-PY reference](../../docs/sericite-py-reference.md).
