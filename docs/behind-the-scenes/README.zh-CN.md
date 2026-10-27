# 幕后

[English index](README.md)

> **更名说明（2026-10-22）**：本文成文于项目名为 Mica 的时期，文中 Mica 即今 Sericite（发行包与 CLI 为 `sericite`，扩展名 `.sericite`）。本文为历史记录，正文保留当时的名字与命令，阅读时将 `mica`/`micalang` 对应为 `sericite` 即可。

这里放三篇文章，记录这个项目在代码之外的部分：它从哪里来，以及它是怎么被写出来的。

| 文章 | 内容 |
|---|---|
| [origin.zh-CN.md](origin.zh-CN.md) | 《原动力：Mica 之前》。项目立项前的探索过程：为什么需要它、为什么已有方案不够 |
| [ai-assisted-development.zh-CN.md](ai-assisted-development.zh-CN.md)（[英文摘要](ai-assisted-development.md)） | 《AI 辅助开发说明》。这个项目如何使用 AI：用了什么、怎么分工、怎么验证 |
| [conversation.zh-CN.md](conversation.zh-CN.md) | 《开发对话选编》。开发过程中与 AI 对话的主线摘录 |

## 编辑原则

这三篇文章是**选编，不是全文**。取舍标准如下，供读者判断可信度：

- 删除的内容（涉及私人信息等）用 `[...]` 标出。
- AI 的回复保留原意，不通顺处只做最小修改，不事后美化结论。
- 选编偏向**决策与转折**：哪些方案被提出、哪些被否掉、为什么。日常的细节往返不收录。
- 被否掉的方案和走过的弯路如实保留。这个项目的价值有一半在"为什么不那样做"里。

