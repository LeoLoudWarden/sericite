# 文档索引

[English index](README.md)

Sericite 的文档按读者任务和变化频率分层：使用参考跟随公开接口，实现文档跟随代码，设计文档解释长期边界，历史写定后冻结。文件保持稳定的扁平路径，分类由本索引承担。

## 入门与示例

- [项目 README](../README.zh-CN.md)：项目定位、安装与快速上手。
- [完整演示](../demos/README.zh-CN.md)：root 驱动的 LLM 应用及离线验证；小型语言片段另见 `examples/`。

## 使用参考

| 文档 | 读者与内容 | English |
|---|---|---|
| [CLI 参考](cli-reference.zh-CN.md) | 直接运行程序：命令、include、可信能力配置、退出码 | [cli-reference.md](cli-reference.md) |
| [语言参考](language-reference.zh-CN.md) | 编写脚本：语言子集、内建、record、VM 与异常语义 | [language-reference.md](language-reference.md) |
| [宿主参考](host-reference.zh-CN.md) | 嵌入 Python：引擎 API、VM 驱动、FFI、调试与错误处理 | [host-reference.md](host-reference.md) |

写脚本先读语言参考；运行 root 应用读 CLI 参考；需要由既有 Python 系统掌管 VM 生命周期时读宿主参考。

## 设计与边界

| 文档 | 内容 | English |
|---|---|---|
| [设计说明](design.zh-CN.md) | Sericite 是什么、为什么存在、边界划在哪里 | [design.md](design.md) |
| [安全模型](security.zh-CN.md) | 威胁模型；引擎和能力实现者各自保证什么 | [security.md](security.md) |
| [先例与相关工作](prior-art.zh-CN.md) | Safe-Tcl 证明了什么、停在哪里，Sericite 补什么 | [prior-art.md](prior-art.md) |

执行不可信代码前先读安全模型。security 中的威胁模型属于设计承诺，配额与已知边界属于实现现状。

## 实现

- [架构说明](architecture.zh-CN.md)（[English](architecture.md)）：执行管线、模块结构、设计不变量、资源记账和当前实现边界。修改引擎前阅读。

## 历史

- [构建手记](stages/README.zh-CN.md)：Sericite 0.1.0 的逐阶段构建过程与可运行检查点。
- [幕后](behind-the-scenes/README.zh-CN.md)：项目由来与 AI 辅助开发过程。

这两组正文仅中文，索引页有英文版；不计划全文翻译。它们是冻结的历史，不用于描述当前 CLI 或 API。
