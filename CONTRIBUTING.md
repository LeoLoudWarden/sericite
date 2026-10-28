# 贡献指南

English readers: this project's development workflow is currently documented in Chinese. An English version is planned.

## 开发环境

- Python ≥ 3.12，包管理用 [uv](https://docs.astral.sh/uv/)。
- 引擎本体零第三方依赖；`demo` 的依赖在 `pyproject.toml` 的 `demo` extra 里。

## 验证

修改引擎、编译器或脚本接口后，必须先运行回归套件：

```bash
uv sync --extra demo
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests
```

lint 与格式检查由 CI 强制执行（ruff，配置见 `pyproject.toml`）。仓库采用 `src/` 布局，直接运行 `python -m unittest` 前需要先安装本项目（`uv sync` 会自动处理）。

## 发版

1. 更新 `src/sericite/__init__.py` 的 `__version__`。
2. 在 `CHANGELOG.md` 的 `[Unreleased]` 下新增 `## [X.Y.Z] - YYYY-MM-DD` 节。
3. 新 minor 版本在 `SECURITY.md` 的支持版本表加一行（patch 版本不动）。
4. 打 tag 并推送：`git tag vX.Y.Z && git push origin vX.Y.Z`。

`release.yml` 会先校验 tag 与 `__version__`、CHANGELOG 节、`SECURITY.md` 的 minor 行是否一致；任一项不符则构建失败，不会发布。

## 设计纪律

- 理念问题以 [`docs/design.zh-CN.md`](docs/design.zh-CN.md) 为准。改理念先改它，不要在别处另造表述。
- 架构不变量见 [`docs/architecture.zh-CN.md`](docs/architecture.zh-CN.md)。新语法必须先过编译器白名单，禁止引入 `exec`/`eval`。
- 不给引擎加网络/设备等内建能力；能力的正确形态是 FFI 授予。安全边界见 [`docs/security.zh-CN.md`](docs/security.zh-CN.md)。
- 修改 CLI 命令、include、能力配置或退出码时，同步更新中英文 [`docs/cli-reference.zh-CN.md`](docs/cli-reference.zh-CN.md) 与端到端测试。完整验证需安装 `demo` extra；离线 root-agent 测试不得依赖真实 API。

## 文档流程

本项目的说明性文档遵循一条规则：**AI 可以起草，入库前必须经作者人工打磨**。如果你提交的 PR 改动文档，请确保文本由人通读并修改过，而不是直接提交模型输出。

文档语言规范：**中文文档统一使用 `.zh-CN.md` 后缀，英文文档统一使用 `.md` 后缀，同一文件内不混排两种语言**；同名文档的中英文版互链。例外：`CHANGELOG.md`、`SECURITY.md`、`CONTRIBUTING.md` 等受平台或社区约定固定文件名的文档，保留固定文件名，正文以中文书写，不拆分双语版本。

代码语言规范：**Python 源码与示例中的注释和 docstring 统一使用英文**。字符串内容（demo 提示词、测试夹具数据等）不是注释，语言按内容需要保留。

## 提交信息

使用中文，一句话说明这次提交做了什么，格式参考已有历史（如 `docs: 文档初始化——设计理念、语言参考与构建手记框架`）。
