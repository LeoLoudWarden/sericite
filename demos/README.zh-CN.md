# Sericite 完整演示

[English](README.md)

`demos/` 收录跨多个组件的完整应用场景；`examples/` 则是可直接运行的小型语言特性片段。

| 演示 | 形态 | 内容 |
|---|---|---|
| [root-agent](root-agent/README.zh-CN.md) | 薄 Python 能力配置 + root Sericite 应用 | 外层/内层 LLM 会话、嵌套 VM、逐层能力授予、VFS 文件收种；含离线桩 |

运行方式与通用配置契约见 [CLI 参考](../docs/cli-reference.zh-CN.md)。需要把 VM 嵌入既有 Python 生命周期时，仍应使用[宿主 API](../docs/host-reference.zh-CN.md)。
