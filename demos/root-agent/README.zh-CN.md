# root-agent：由 root Sericite 驱动的多层 LLM 应用

[English](README.md)

这个 demo 是一个由 root Sericite 程序驱动的多层 LLM 应用。**root 自己运行外层 LLM 会话**：构建 messages/tools、发送请求并分发工具。Python 通过 `configure()` 提供模型通信、终端着色和初始文件；`agentkit` 只负责外层会话、工作区与展示，内层 Agent 由模型自己编写。

## 运行结构

- **外层会话**：root 导入 `agentkit`，持有一个跨工具调用保留的分离 VFS。模型用 `file_read` / `file_write` / `file_list` 操作文件，用 `run(path)` 选择并运行入口，而不是直接提交源码字符串。
- **脚本运行**：每次 `run(path)` 都用 `VM(entry_file=path, fs=...)` 把工作区移入一台全新 VM，终态后取回工作区。模块从入口文件所在目录导入，文件操作仍以工作区根为基准。变量、模块缓存和执行账不保留，文件保留；修改已 import 的模块后重跑会加载新代码。运行中的脚本可以使用 `llm_chat` 和 `http_get`，因此既能完成普通练习，也能实现新的 LLM 会话。
- **子 Agent**：外层模型用这两个授予函数自己编写子 Agent 的会话循环和工具分发，并为它维护独立工作区。子 Agent 再通过 VM 运行没有宿主函数的最内层代码，递归能力到此终止。AgentKit 不代替模型生成这一层。

## 文件与提示词边界

- root VFS 分为 `/control`、`/workspace` 与 `/agentkit`：外层提示词只在控制区，AgentKit 是外层控制器代码；模型工作区预置语言参考和内层提示词。
- 模型的文件工具操作两次运行之间处于分离状态的 VFS；运行时工作区排他移入 VM，终态后取回，因此文件工具和 `run(path)` 始终看到同一个世界。
- 子 Agent 的工作区由模型编写的代码单独创建，不自动复制外层文件。最内层运行不能访问控制区、网络或外层 VM 的变量。
- `run(path)` 返回错误而不会抹去已产生的文件；语法错误、运行错误和失败前的产物都可以继续检查。等待输入被视为非交互运行的结束条件，先终止再取回工作区。

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

桩按固定脚本扮演外层和子 Agent，覆盖文件写入、`run(path)`、模块导入、修改模块后重跑、失败产物保留，以及外层模型写入并运行子 Agent 源码、再进入更深 VM 的完整链。它证明链路可重复运行，不证明任意真实模型都能同样顺畅地使用工具。`tests/test_demos.py` 会在临时端口自动执行这条链。

## 实时展示与日志

默认 stdout 只展示执行过程：每轮一个标题、紧凑的工具摘要，以及带 `VM 1` 前缀的实时输出。默认不倾倒文件内容或源码，也不重复打印 `run(path)` 返回的同一段输出；展示摘要不会截断实际发给模型的工具参数或结果。

### 工具结果截断

- 较短的 `run(path)` 结果原样返回。
- 超过 `MAX_RESULT_CHARS`（4000）字符的结果只返回前 4000 字符，并建议模型用 `file_write` 写入完整文本，再用 `file_read` 读取。
- 同一会话再次截断时，建议升级为明确警告：不要重复打印或重跑大段输出。
- 这是执行环境有意提供的渐进反馈，与实时展示的折叠相互独立；提示词不会提前教授这套恢复策略。

### 实时输出

- root 的 `print()` 由 CLI 实时转发到 stdout；各层 VM 通过 `output_writer` 显式转发输出。
- `ROOT`、`MODEL`、`VM 1`、`ROUND`、`FINAL` 使用统一的 8 列前缀和竖线分隔；多行内容逐行添加前缀。
- 在交互终端中，不同来源的前缀以不同颜色粗体显示；stdout 重定向时自动禁用颜色，设置 `NO_COLOR` 也可禁用。
- 每次 `run(path)` 最多直播前 `MAX_LIVE_LINES`（8）行；发生折叠时，末尾给出总量摘要和最后 `LIVE_TAIL_LINES`（3）行。
- `MODEL` 正文、`FINAL` 最终回答和 root 结果文本始终完整显示。折叠只作用于 VM 实时输出；默认展示中只有这类实时输出的单行超过 `MAX_LIVE_LINE_CHARS`（240）字符才会缩短。
- 在 `agent.sericite` 后追加 `--verbose` 可显示完整工具参数/结果并关闭实时输出折叠；工具参数和结果使用 `repr`。
- 两种展示都不改变传回模型的原始工具结果。VM stdout 仍保留缓冲，因为 `run()` 还要把同一段文本作为工具结果返回；缓冲语义见 [虚拟机参考](../../docs/vm-reference.zh-CN.md)第 4 节。

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

把 `LOG_LLM` 改为 `True` 后，每次调用输出一行摘要，包含调用编号与模型、消息数与工具数、HTTP 状态与耗时、返回文本长度与工具调用数量。再把 `LOG_LLM_FULL_JSON` 改为 `True`，可额外输出完整的请求/响应 JSON。日志立即 flush，且不会记录 Authorization 头或 API key。

诊断行使用与 stdout 一致的固定宽度前缀，例如 `LLM     │ call #18 still waiting · 15s`。stderr 是交互终端时前缀显示为粗体红色；重定向或设置 `NO_COLOR` 时不带颜色。

即使关闭底层日志，慢请求和网络问题仍然可见：第一分钟每 15 秒显示一次等待提示，之后每分钟一次；每次请求 90 秒超时，最多尝试三次；网络重试和 HTTP 错误始终报告。

完整 JSON 会包含提示词、模型生成的代码和工具结果，分享前需检查；需要分开保存时可用 `2>llm.log`。

## 文件与职责

- `agent.sericite`：短入口，设置 verbose 并启动外层 Agent。
- `agentkit/session.sericite`：通用 LLM 会话循环、工具 schema、分发与紧凑摘要。
- `agentkit/workspace.sericite`：持久工作区、文件工具和 `run(path)` 的 VM 独占移交闭环。
- `agentkit/runtime.sericite`：组装外层 Agent，不生成子 Agent。
- `agentkit/display.sericite`：实时输出折叠、结果截断反馈和终端展示。
- `capabilities.py`：可信宿主适配层。它读取环境、发起 HTTP 请求并规整协议、处理终端颜色，通过 `configure()` 返回 `functions`、demo 专用指令预算和 root VFS 初始文件。它不包含应用会话循环。
- `prompt_outer.txt`：只放控制区的外层提示词；`prompt_inner.txt`：预置到模型工作区的内层提示词，由模型编写的子 Agent 读取。
- `mock_server.py`：本地 OpenAI 兼容桩；`.env.example`：环境变量模板。

`requests` 与 `python-dotenv` 只属于 `demo` extra，不是引擎或基础 CLI 的运行时依赖。通用参数、多文件项目、退出码和信任边界见 [CLI 参考](../../docs/cli-reference.zh-CN.md)；需要由既有 Python 系统掌管 VM 生命周期时，使用 [Sericite-PY 参考](../../docs/sericite-py-reference.zh-CN.md)中的嵌入 API。
