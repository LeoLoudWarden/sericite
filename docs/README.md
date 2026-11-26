# Documentation Index

[中文索引](README.zh-CN.md)

Sericite's documentation is organized by reader task and rate of change: user manuals follow public interfaces, implementation notes follow code, design documents explain durable boundaries, and history freezes once written. This index provides the hierarchy across the manuals and supporting documents.

## Start and examples

- [Project README](../README.md): positioning, installation, and a short runnable introduction.
- [Application demos](../demos/README.md): a root-driven LLM application with offline verification; see `examples/` for small language snippets.

## User manuals

Each manual provides task-organized guides and an API reference for looking up precise contracts. For the shared introduction and safety essentials, see the [manual home](manual/README.md) ([中文](manual/README.zh-CN.md)).

| Manual | Audience and contents | 中文 |
|---|---|---|
| [Scripting manual](manual/scripting/README.md) | Script authors: language, built-ins, records, errors, files, VMs, and VFSs | [脚本手册](manual/scripting/README.zh-CN.md) |
| [CLI manual](manual/cli/README.md) | Program operators: commands, multi-file projects, trusted addon configuration, and exit codes | [命令行手册](manual/cli/README.zh-CN.md) |
| [Python host manual](manual/host-python/README.md) | Python embedders: engine API, VM lifecycle, VFSs, addons, observation, and host diagnostics | [Python 宿主手册](manual/host-python/README.zh-CN.md) |

The scripting manual can be read independently: writing scripts does not require the CLI or Python host details. Read the CLI manual to run programs from a terminal, and the Python host manual when an existing Python application needs to create, drive, or inspect VMs.

## Design and boundaries

| Document | Contents | 中文 |
|---|---|---|
| [Design notes](design.md) | What Sericite is, why it exists, and where its boundaries lie | [design.zh-CN.md](design.zh-CN.md) |
| [Security model](security.md) | Threat model and the respective responsibilities of engine and capability implementers | [security.zh-CN.md](security.zh-CN.md) |
| [Prior art](prior-art.md) | What Safe-Tcl proved, where it stopped, and what Sericite adds | [prior-art.zh-CN.md](prior-art.zh-CN.md) |

Read the security model before executing untrusted code.

## Implementation

- [Architecture](architecture.md) ([中文](architecture.zh-CN.md)): execution pipeline, module structure, invariants, resource accounting, and current implementation limits. Read this before changing the engine.

## History

- [Build journal](stages/README.md): the stage-by-stage construction of Sericite 0.1.0 and runnable checkpoints.
- [Behind the scenes](behind-the-scenes/README.md): the project's origin and AI-assisted development process.

The long-form articles in these two groups are Chinese-only, with English index pages; full translations are not planned. They are frozen history, not descriptions of the current CLI or API.
