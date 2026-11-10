# root-agent: a multi-layer LLM application driven by root Sericite

[中文](README.zh-CN.md)

This demo is a multi-layer LLM application driven by a root Sericite program. **Root runs the outer LLM session**: it builds messages/tools, sends requests, and dispatches tools. Python supplies model communication, terminal styling, and initial files through `configure()`; `agentkit` handles only the outer session, workspace, and display, while the model writes the inner agent itself.

## Runtime structure

- **Outer session**: root imports `agentkit` and holds a detached VFS across tool calls. The model manages files with `file_read` / `file_write` / `file_list` and selects an entry to execute with `run(path)` instead of submitting source strings directly.
- **Script runs**: every `run(path)` moves the workspace into a fresh VM and retrieves it at the terminal state. Variables, module caches, and execution ledgers do not survive, while files do, so editing an imported module and rerunning loads the new code. Scripts can use `llm_chat` and `http_get`, allowing them to complete ordinary exercises or implement another LLM session.
- **Child agents**: the outer model uses these two granted functions to write the child agent's session loop and tool dispatch, with an independent workspace. The child then runs the innermost code in a VM with no host functions, ending capability recursion there. AgentKit does not generate this layer for the model.

## Files and prompt boundary

- The root VFS is divided into `/control`, `/workspace`, and `/agentkit`. The outer prompt stays in control, AgentKit is outer-controller code, and the model workspace starts with the language reference and inner prompt.
- Between runs, file tools operate on the detached VFS. A run exclusively moves it into a VM and takes it back afterward, so file tools and `run(path)` always see the same world.
- The model-written code creates the child agent's workspace separately instead of automatically copying outer files. The innermost run can access neither control files, the network, nor outer VM variables.
- `run(path)` reports errors without erasing files produced before the failure. Syntax errors, runtime errors, and failure artifacts remain inspectable. Waiting for input ends a non-interactive run: the VM is terminated before its workspace is retrieved.

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

The stub follows a fixed script as the outer and child models, covering file writes, `run(path)`, imports, rerun after module edits, preserved failure artifacts, and the complete chain in which the outer model writes and runs child-agent source before entering a deeper VM. It proves repeatability, not that every real model will use the tools equally smoothly. `tests/test_demos.py` runs this chain automatically on a temporary port.

## Live display and logs

Default stdout shows only the execution story: one heading per round, compact tool summaries, and live `VM 1` output. It does not dump file contents or source, or print a second copy of output returned by `run(path)`. Display summaries never truncate actual tool arguments or results sent to the model.

### Tool-result truncation

- Short `run(path)` results are returned unchanged.
- A result longer than `MAX_RESULT_CHARS` (4000) characters returns only the first 4000 characters, with advice to write full text using `file_write` and read it using `file_read`.
- Repeated truncation in the same session escalates to an explicit warning not to print or rerun large output again.
- This is deliberate progressive feedback from the execution environment, independent of live-output folding; the prompts do not teach this recovery strategy in advance.

### Live output

- Root `print()` output is forwarded live by the CLI, and each VM's output is explicitly forwarded through `output_writer`.
- `ROOT`, `MODEL`, `VM 1`, `ROUND`, and `FINAL` use a consistent eight-column prefix and vertical separator; multiline content is prefixed line by line.
- In an interactive terminal, each source has a distinct bold color. Redirection disables color automatically, and `NO_COLOR` disables it explicitly.
- Each `run(path)` shows at most its first `MAX_LIVE_LINES` (8) lines; when folding occurs, it ends with a size summary and the last `LIVE_TAIL_LINES` (3) lines.
- `MODEL` responses, the `FINAL` response, and root result text are always shown in full. Folding applies only to live VM output, where lines longer than `MAX_LIVE_LINE_CHARS` (240) characters are also shortened by default.
- Append `--verbose` after `agent.sericite` to show full tool arguments/results and disable live-output folding; tool arguments and results use `repr`.
- Neither display path changes the raw tool results sent back to the model. VM stdout remains buffered because `run()` also returns that text as the tool result; see the [VM reference](../../docs/vm-reference.md) §4 for buffering semantics.

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

Set `LOG_LLM = True` to print one summary line per call with the call number and model, message and tool counts, HTTP status and elapsed time, and response text and tool-call counts. Set `LOG_LLM_FULL_JSON = True` as well to include complete request/response JSON. Logs flush immediately and never record Authorization headers or API keys.

Diagnostic lines use the same fixed-width prefix style as stdout, for example `LLM     │ call #18 still waiting · 15s`. The prefix is bold red when stderr is an interactive terminal; redirection or `NO_COLOR` disables color.

Slow requests and network problems remain visible even when low-level logging is off: a waiting notice appears every 15 seconds for the first minute, then once per minute; each attempt times out after 90 seconds and is retried up to three times; retries and HTTP errors are always reported.

Full JSON contains prompts, model-generated code, and tool results; review it before sharing. Use `2>llm.log` to save stderr separately.

## Files and responsibilities

- `agent.sericite`: short entry point that configures verbose mode and starts the outer agent.
- `agentkit/session.sericite`: generic LLM session loop, tool schemas, dispatch, and compact summaries.
- `agentkit/workspace.sericite`: persistent workspace, file tools, and the exclusive VM-transfer loop behind `run(path)`.
- `agentkit/runtime.sericite`: outer-agent assembly; it does not generate a child agent.
- `agentkit/display.sericite`: live-output folding, result-truncation feedback, and terminal presentation.
- `capabilities.py`: trusted host adapter. It loads the environment, performs HTTP requests and protocol normalization, handles terminal colors, and returns `functions`, a demo-specific instruction budget, and initial root VFS files through `configure()`. It has no application session loop.
- `prompt_outer.txt`: outer prompt kept in the control area; `prompt_inner.txt`: inner prompt seeded into the model workspace and read by the model-written child agent.
- `mock_server.py`: local OpenAI-compatible stub; `.env.example`: environment template.

`requests` and `python-dotenv` belong only to the `demo` extra, not to the engine or base CLI. See the [CLI reference](../../docs/cli-reference.md) for general options, multi-file projects, exit codes, and trust boundaries. To let an existing Python system own VM lifecycles, use the embedding API in the [Sericite-PY reference](../../docs/sericite-py-reference.md).
