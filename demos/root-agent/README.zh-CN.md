# root-agent：由 root Sericite 驱动的多层 LLM 应用

[English](README.md)

这个 demo 是一个由 root Sericite 程序驱动的多层 LLM 应用。**root 自己运行外层 LLM 会话**：构建 messages/tools、读取外层提示词、发送请求并分发工具。Python 只通过 `configure()` 提供两个宿主函数 `llm_chat` / `http_get`，以及 root VFS 的初始文件。

## 运行结构

- **外层会话**：root 为整个会话维护一台持久的第一层 VM，向它授予这两个宿主函数，并在启动时预置模型工作区。
- **第一层 VM**：外层模型调用 `sericite_exec` 时，root 用 `exec` 把代码投递给这台 VM。模块变量、定义和文件在多次调用之间保留；模型生成的代码可以用 `llm_chat` 自己再开一个内部会话。
- **第二层 VM**：内部会话继续调用 `sericite_exec` 时，由模型生成的代码维护一台第二层 VM。它不获得任何宿主函数，因此没有网络能力，递归在这里终止。内层会话及其 VM 管理代码全部由模型编写，demo 不预写另一层 agent。

## 文件与提示词边界

- root VFS 分为 `/control` 与 `/workspace`：外层提示词只在控制区，工作区在启动时一次性预置进执行 VM。
- 模型的文件工具直接对接这台持久 VM 的文件系统，`sericite_exec` 代码写的文件和 `file_write` 写的文件落在同一个地方，无需重复预置或回收。
- 提示词只告诉模型它能创建 VM，不告诉它当前代码和文件也已经处于 VM 中。

## 运行

在仓库根目录安装 demo extra：

```bash
uv sync --extra demo
```

复制 `.env.example` 为本目录的 `.env`，配置 OpenAI 兼容端点的 `API_URL` / `API_KEY` / `API_MODEL`，然后运行：

```bash
uv run --extra demo sericite \
  --capabilities demos/root-agent/capabilities.py \
  demos/root-agent/agent.sericite
```

也可以用 `DEMO_ENV` 指定另一个环境文件。不要把 API 密钥提交到仓库；能力文件的信任边界见 [CLI 参考](../../docs/cli-reference.zh-CN.md)第 4.2 节。

## 无真实 API 的完整验证

在一个终端启动本地桩：

```bash
uv run --extra demo demos/root-agent/mock_server.py
```

在另一个终端运行同一个 root 应用：

```bash
API_URL=http://127.0.0.1:8399/v1/chat/completions API_KEY=mock API_MODEL=mock \
  uv run --extra demo sericite \
  --capabilities demos/root-agent/capabilities.py \
  demos/root-agent/agent.sericite
```

桩按固定脚本扮演外层和内部模型，覆盖"root → 子 VM 内部会话 → 更深 VM 练习"的完整链。它证明链路可重复运行，不证明任意真实模型都能生成等价代码。`tests/test_demos.py` 会在临时端口自动执行这条链。

## 实时展示与日志

默认 stdout 只展示执行过程：每个外层轮次一个标题、紧凑的工具摘要，以及带 `vm 1` 前缀的实时输出。它不倾倒文件内容或源码，也不重复打印 `sericite_exec` 返回的同一段输出；展示摘要不会截断实际发给模型的工具参数或结果。

### 工具结果截断

- 较短的 `sericite_exec` 结果原样返回。
- 超过 `MAX_RESULT_CHARS`（4000）字符的结果只返回前 4000 字符，并在结果末尾建议模型用 `write_file` 写入完整文本，再用 `file_read` 读取。
- 再次截断时，建议升级为明确警告：不要重复打印或重跑大段输出，改用 `write_file` + `file_read`。
- 这是执行环境有意提供的渐进反馈，与实时展示的折叠相互独立；提示词不会提前教授这套恢复策略。

### 实时输出

- root 的 `print()` 由 CLI 实时转发到 stdout。
- 第一层 VM 通过 `output_writer` 把自己的输出经 root 转发，模型生成的进度在执行期间即可见。
- 默认按可读行显示，并加 `vm 1` 前缀。
- 每次 `sericite_exec` 最多直播前 `MAX_LIVE_LINES`（8）行；发生折叠时，末尾给出总量摘要和最后 `LIVE_TAIL_LINES`（3）行。
- 单行超过 `MAX_LIVE_LINE_CHARS`（240）字符会缩短。
- 在 `agent.sericite` 后追加 `--verbose` 可显示完整输出和工具参数/结果；工具参数和结果使用 `repr`。
- 两种展示都不改变传回模型的原始工具结果。
- 第一层 stdout 仍保留缓冲，因为 `sub.exec()` 还要把同一段文本作为 `sericite_exec` 的工具结果返回；缓冲语义见 [虚拟机参考](../../docs/vm-reference.zh-CN.md)第 4 节。

```bash
uv run --extra demo sericite \
  --capabilities demos/root-agent/capabilities.py \
  demos/root-agent/agent.sericite --verbose
```

### stderr 日志

`capabilities.py` 顶部的两个常量控制底层 **stderr** 日志：

```python
LOG_LLM = False
LOG_LLM_FULL_JSON = False
```

把 `LOG_LLM` 改为 `True` 后，每次调用输出一行摘要，包含：

- 调用编号与模型；
- 消息数与工具数；
- HTTP 状态与耗时；
- 返回文本长度与工具调用数量。

再把 `LOG_LLM_FULL_JSON` 改为 `True`，可额外输出完整的请求/响应 JSON。日志立即 flush，且不会记录 Authorization 头或 API key。

即使关闭底层日志，慢请求和网络问题仍然可见：

- 第一分钟每 15 秒显示一次等待提示，之后每分钟一次；
- 每次请求 90 秒超时，最多尝试三次；
- 网络重试和 HTTP 错误始终报告。

完整 JSON 会包含提示词、模型生成的代码和工具结果，分享前需检查；需要分开保存时可用 `2>llm.log`。

## 文件与职责

- `agent.sericite`：唯一的 Sericite 应用主体，即 root 环境。它实现外层会话循环、四个模型工具（`sericite_exec` / `file_read` / `file_write` / `file_list`）的分发，以及 `/control` 与 `/workspace` 的边界。
- `capabilities.py`：可信宿主适配层。它读取环境、发起 HTTP 请求并规整协议，通过 `configure()` 返回 `functions`、demo 专用指令预算和 root VFS 初始文件。它不包含应用会话循环。
- `prompt_outer.txt` / `prompt_inner.txt`：两层模型提示词。外层提示词只放 root 控制区；内层提示词预置到模型工作区，且不被告知继续授予递归能力。
- `mock_server.py`：本地 OpenAI 兼容桩。
- `.env.example`：环境变量模板。

`requests` 与 `python-dotenv` 只属于 `demo` extra，不是引擎或基础 CLI 的运行时依赖。通用参数、include、退出码和信任边界见 [CLI 参考](../../docs/cli-reference.zh-CN.md)；需要由既有 Python 系统掌管 VM 生命周期时，使用 [Sericite-PY 参考](../../docs/sericite-py-reference.zh-CN.md)中的嵌入 API。
