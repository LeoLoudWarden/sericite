# Building Mica from Scratch

[中文索引](README.zh-CN.md)

> **Rename note (2026-10-22):** this series was written while the project was named Mica; in the articles, Mica means today's Sericite (distribution package and CLI `sericite`, extension `.sericite`). The articles keep the names and commands of their time — just read `mica`/`micalang` as `sericite`. The articles themselves are in Chinese; this page is the English index.

This series tells how Mica 0.1.0 was built: from an AST prototype that could execute two statements, to an engine with a compiler, a virtual filesystem, capability granting, and resource quotas, to a complete LLM code-execution demo. Each stage corresponds to a git tag you can check out and actually run.

**Before reading this series, read the [design notes](../design.md) first** — that document is about the "why"; this one is about "how, step by step".

## Two declarations

**This series is a reconstructed teaching history.** The code at each stage comes from the real development history, but the commit order and document structure were rearranged for teaching; it is not a day-by-day timeline. The original development process records are in [behind-the-scenes](../behind-the-scenes/README.md).

**This series is frozen at 0.1.0.** The articles describe how 0.1.0 was built; they are not current API documentation. Language behavior is governed by the [scripting manual](../manual/scripting/README.md), and the current implementation by the [architecture notes](../architecture.md). Later changes go into the CHANGELOG, not back into these articles.

## Prerequisites

- You can write Python (Mica's syntax is a Python subset, and the reference implementation is Python).
- A rough idea of what "an interpreter" is suffices; no compiler-theory background needed — the concepts used (instruction streams, stack machines, exception tables) are explained when they come up.

## Stage table

| Stage | Content | What runs at the end | tag |
|---|---|---|---|
| 0 | Documentation first: write down the design ideas | — (no code) | `stage-0` |
| 1 | Minimal loop: AST whitelist + statement-stepping VM | `input`/`print`, string concatenation, root VM creating and single-stepping a child VM | `stage-1` |
| 2 | A real engine: compile to instruction stream, unified dispatch loop | conditionals, loops, functions, recursion | `stage-2` |
| 3 | Workspace: private virtual filesystem, VM lifecycle | each VM has its own file space; preset before the run, harvest after | `stage-3` |
| 4 | Data and capability: dict, FFI capability granting | host/parent VMs grant functions to the next layer, bidirectional deep copy across boundaries | `stage-4` |
| 5 | Hardening + usability: quota system, for/try/finally/raise | resources stay bounded under adversarial input; the language suffices for real scripts | `stage-5` |
| 6 | Finale: a real use case | HTTP capability granting + multi-layer virtualized LLM code-execution demo | `stage-6` |

The stage articles (中文):

1. [Stage 1: A Minimal Usable VM](01-minimal-vm.zh-CN.md)
2. [Stage 2: Compiler and Stack Machine](02-real-engine.zh-CN.md)
3. [Stage 3: A Workspace for Every VM](03-workspace.zh-CN.md)
4. [Stage 4: Data Structures and Capability Granting](04-dict-and-ffi.zh-CN.md)
5. [Stage 5: Security Review First, Then Syntax](05-security-and-usability.zh-CN.md)
6. [Stage 6: A Real Use Case](06-demo.zh-CN.md)

## How to read this series

These are not six milestone reports, but six coherent build tutorials. Each follows the same thread:

what gap the previous stage left → what question this step must answer → which paths were considered and why this one was chosen → walking through the key code together → how to verify it yourself.

Every code snippet is quoted unchanged from the real snapshot at the corresponding tag; you can `git checkout` at any time to compare against the full picture.

The six articles are connected: each opens by picking up the question its predecessor ended with, and ends by handing a new question to the next. Reading in order is smoothest; reading a single stage on its own also works if you only care about one mechanism.

## How to follow along

```bash
git checkout stage-1        # check out the complete code of a stage
python -m unittest discover -s tests   # run that stage's test suite
```

The code at every tag was fully runnable at the time, with its test suite passing. To compare two stages, use `git diff stage-1 stage-2`.

Note: the `stage-1` through `stage-6` snapshots keep the flat layout of their time (`mica/` at the repository root); the 0.1.0 release-polish commits moved the code to `src/mica/`, and the 0.2.0 rename made it `src/sericite/`. File paths in the articles (e.g. `mica/engine.py`) correspond to the stage snapshots; on `main`, map them to `src/sericite/engine.py`.

## For those who want to replicate

If you want to replicate this approach in your own project, pay special attention to the "forks and trade-offs" part of each article — that is where rejected options and the reasons for rejecting them are recorded. Code goes stale; trade-offs don't.

Equally worth a close read is the "what pits remain" section at the end of each article: this project never hides its half-finished state, and those honestly recorded deviations and debts teach more than the smooth parts.
