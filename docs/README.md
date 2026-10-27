# Documentation Index

[中文索引](README.zh-CN.md)

Sericite's documentation is organized by reader task and rate of change: usage references follow public interfaces, implementation notes follow code, design documents explain durable boundaries, and history freezes once written. Files keep stable flat paths; this index provides the hierarchy.

## Start and examples

- [Project README](../README.md): positioning, installation, and quick start.
- [Application demos](../demos/README.md): a root-driven LLM application with offline verification; see `examples/` for small language snippets.

## Usage references

| Document | Audience and contents | 中文 |
|---|---|---|
| [CLI reference](cli-reference.md) | Running programs: commands, includes, trusted capabilities, and exit codes | [cli-reference.zh-CN.md](cli-reference.zh-CN.md) |
| [Language reference](language-reference.md) | Writing scripts: syntax subset, built-ins, records, VMs, and errors | [language-reference.zh-CN.md](language-reference.zh-CN.md) |
| [VM reference](vm-reference.md) | Driving and debugging VMs: states, driving methods, exec delivery, quotas, grant semantics | [vm-reference.zh-CN.md](vm-reference.zh-CN.md) |
| [Sericite-PY reference](sericite-py-reference.md) | Python embedding: engine API, FFI, host-side error handling | [sericite-py-reference.zh-CN.md](sericite-py-reference.zh-CN.md) |

Read the language reference to write scripts, the CLI reference to run root applications, the VM reference to drive and debug VMs, and the Sericite-PY reference when an existing Python system owns VM lifecycles.

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
