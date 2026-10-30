# Sericite 完整演示

[English](README.md)

`demos/` 收录跨多个组件的完整应用场景；`examples/` 则是可直接运行的小型语言特性片段。

| 演示 | 形态 | 内容 |
|---|---|---|
| [root-agent](root-agent/README.zh-CN.md) | 薄 Python 能力配置 + root Sericite 应用 | 多层 LLM 会话与嵌套 VM；含离线桩 |
| [sorting-arena](sorting-arena/README.zh-CN.md) | 薄 Python 播种 + root Sericite 裁判 | 不可信代码竞赛；正确性、指令数排名与多种淘汰 |
| [sericite-debugger](sericite-debugger/README.zh-CN.md) | 纯 root Sericite 调试器 | 语句/指令单步、watchpoint 与 D(D(P)) 自调试 |

运行方式与通用配置契约见 [CLI 参考](../docs/cli-reference.zh-CN.md)。

需要把 VM 嵌入既有 Python 生命周期时，使用 [Sericite-PY 参考](../docs/sericite-py-reference.zh-CN.md)中的宿主 API。
