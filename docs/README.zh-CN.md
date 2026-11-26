# 文档索引

[English index](README.md)

Sericite 的文档按读者任务和变化频率分层：用户手册跟随公开接口，实现文档跟随代码，设计文档解释长期边界，历史写定后冻结。本索引为各套手册和其他文档提供分类与层次。

## 入门与示例

- [项目 README](../README.zh-CN.md)：项目定位、安装与简短的可运行导览。
- [完整演示](../demos/README.zh-CN.md)：root 驱动的 LLM 应用及离线验证；小型语言片段另见 `examples/`。

## 用户手册

每套手册都包含按任务组织的指南，以及供精确查询契约的 API 参考。三套手册的共同说明与安全使用总则见[手册总入口](manual/README.zh-CN.md)（[English](manual/README.md)）。

| 手册 | 读者与内容 | English |
|---|---|---|
| [脚本手册](manual/scripting/README.zh-CN.md) | 脚本作者：语言、内建、record、异常、文件、VM 与 VFS | [Scripting manual](manual/scripting/README.md) |
| [命令行手册](manual/cli/README.zh-CN.md) | 运行程序的操作者：命令、多文件项目、可信 addon 配置、退出码 | [CLI manual](manual/cli/README.md) |
| [Python 宿主手册](manual/host-python/README.zh-CN.md) | Python 嵌入者：引擎 API、VM 生命周期、VFS、addon、观察与宿主诊断 | [Python host manual](manual/host-python/README.md) |

脚本手册可以独立阅读：编写脚本不要求理解命令行或 Python 宿主细节。需要从终端运行程序时读命令行手册；需要由既有 Python 应用创建、驱动或检查 VM 时读 Python 宿主手册。

## 设计与边界

| 文档 | 内容 | English |
|---|---|---|
| [设计说明](design.zh-CN.md) | Sericite 是什么、为什么存在、边界划在哪里 | [design.md](design.md) |
| [安全模型](security.zh-CN.md) | 威胁模型；引擎和能力实现者各自保证什么 | [security.md](security.md) |
| [先例与相关工作](prior-art.zh-CN.md) | Safe-Tcl 证明了什么、停在哪里，Sericite 补什么 | [prior-art.md](prior-art.md) |

执行不可信代码前先读安全模型。

## 实现

- [架构说明](architecture.zh-CN.md)（[English](architecture.md)）：执行管线、模块结构、设计不变量、资源记账和当前实现边界。修改引擎前阅读。

## 历史

- [构建手记](stages/README.zh-CN.md)：Sericite 0.1.0 的逐阶段构建过程与可运行检查点。
- [幕后](behind-the-scenes/README.zh-CN.md)：项目由来与 AI 辅助开发过程。

这两组正文仅中文，索引页有英文版；不计划全文翻译。它们是冻结的历史，不用于描述当前 CLI 或 API。
