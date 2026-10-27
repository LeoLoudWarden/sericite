# root-agent：由 root Sericite 驱动的多层 LLM 应用

[English](README.md)

这个 demo 把旧厚宿主 `main.py` 的根部环境从 Python 换成了 Sericite。**root 自己运行外层 LLM 会话**：构建 messages/tools、读取外层提示词、发送请求并分发工具；Python 只通过 `configure()` 提供 `llm_chat` / `http_get` 和 root VFS 的初始文件。

root 为整个外层会话维护一个持久的第一层 VM，授予这两个函数并一次性预置模型工作区。外层模型调用 `sericite_exec` 时，root 用 `exec` 把代码投递给这个 VM——模块变量、定义和文件在多次调用之间保留；模型生成的代码在其中自由执行，可以用 `llm_chat` 自己再开一个内部会话。内部会话继续调用 `sericite_exec` 时，由模型生成的代码维护一个不再授予网络能力的第二层 VM，递归因此终止。内层会话及其 VM 管理代码全部由模型编写，demo 不预写另一层 agent。

root VFS 分为 `/control` 与 `/workspace`：外层提示词只在控制区，工作区在启动时一次性预置进执行 VM。模型的文件工具直接对接这个持久 VM 的文件系统，`sericite_exec` 代码写的文件和 `file_write` 写的文件落在同一个地方，无需再播种或收种。提示词只告诉模型它能创建 VM，不告诉它当前代码和文件也已经处于 VM 中。

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

也可以用 `DEMO_ENV` 指定另一个环境文件。配置文件必须被当作拥有完整宿主权限的 Python 代码信任；不要把 API 密钥提交到仓库。

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

桩按固定脚本扮演外层和内部模型，覆盖“root → 子 VM 内部会话 → 更深 VM 练习”的完整链。它证明链路可重复运行，不证明任意真实模型都能生成等价代码。`tests/test_demos.py` 会在临时端口自动执行这条链。

## 实时日志

`capabilities.py` 顶部的两个常量控制 **stderr** 日志：

```python
LOG_LLM = True
LOG_LLM_FULL_JSON = False
```

`LOG_LLM` 是总开关。默认精简模式为每次调用输出单行摘要：调用编号、模型、消息/工具数量、HTTP 状态、耗时、返回文本长度和工具调用数量；网络重试也会记录。把 `LOG_LLM_FULL_JSON` 改为 `True` 可额外输出完整请求/响应 JSON。日志立即 flush，且不会记录 Authorization 头或 API key。

完整 JSON 会包含提示词、模型生成的代码和工具结果，分享前需检查内容；需要分开保存时可使用 `2>llm.log`。root 的 `print()` 也会由 CLI 实时转发到 stdout，因此应用进度和宿主网络日志都不再需要等程序结束。

## 文件与职责

- `agent.sericite`：唯一手写的应用程序，即 root 环境；运行外层 LLM 会话、面向一个持久的第一层执行 VM 分发四个工具，并维持 `/control` 与 `/workspace` 的边界。
- `capabilities.py`：可信宿主适配；读取环境、HTTP 请求与协议规整，通过 `configure()` 返回 functions、demo 专用指令预算和 root VFS 初始文件。没有应用会话循环。
- `prompt_outer.txt` / `prompt_inner.txt`：两层模型提示词；外层只放 root 控制区，内层预置到模型工作区，内层不被告知继续授予递归能力。
- `mock_server.py`：本地 OpenAI 兼容桩。
- `.env.example`：环境变量模板。

`requests` 与 `python-dotenv` 只属于 `demo` extra，不是引擎或基础 CLI 的运行时依赖。通用参数、include、退出码和信任边界见 [CLI 参考](../../docs/cli-reference.zh-CN.md)；需要由既有 Python 系统掌管 VM 生命周期时，使用[宿主参考](../../docs/host-reference.zh-CN.md)中的嵌入 API。
