# Documentation Index

[中文索引](README.zh-CN.md)

Sericite's documents have different natures, which determine when they change and whom they serve: design docs rarely change, references follow the language, implementation docs follow the code, and history freezes once written.

| Document | Category | Question it answers | 中文 |
|---|---|---|---|
| [design.md](design.md) | Design | What Sericite is, why it exists, where the boundaries are | [design.zh-CN.md](design.zh-CN.md) |
| [language-reference.md](language-reference.md) | Reference | The Sericite script language subset and semantics; read it and start writing | [language-reference.zh-CN.md](language-reference.zh-CN.md) |
| [host-reference.md](host-reference.md) | Reference | Python host API, VM driving, FFI, debugging, and error handling | [host-reference.zh-CN.md](host-reference.zh-CN.md) |
| [architecture.md](architecture.md) | Implementation | Engine structure, design invariants, quota system | [architecture.zh-CN.md](architecture.zh-CN.md) |
| [security.md](security.md) | Design+Implementation | Threat model; what is and is not guaranteed | [security.zh-CN.md](security.zh-CN.md) |
| [prior-art.md](prior-art.md) | Design | Prior art: what Safe-Tcl proved, where it stopped, what Sericite adds | [prior-art.zh-CN.md](prior-art.zh-CN.md) |
| [stages/](stages/README.md) | History | *Building Sericite from Scratch*: stage-by-stage build journal | 正文 [中文](stages/README.zh-CN.md) |
| [behind-the-scenes/](behind-the-scenes/README.md) | History | Origin story, AI-assisted development | 正文 [中文](behind-the-scenes/README.zh-CN.md) |

Note that security deliberately spans two categories: the *threat model* is a design promise (rarely changes), while *quotas and known boundaries* describe implementation status (follows the code).

Suggested reading order: **design** to understand the project; **language-reference** to write Sericite scripts; **host-reference** to use the engine from Python; **architecture** to work on the engine; **security** before running untrusted code; **stages** and **behind-the-scenes** (articles in Chinese, with English index pages) for how the project was built.
