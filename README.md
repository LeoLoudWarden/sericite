# Sericite

[![CI](https://github.com/LeoLoudWarden/sericite/actions/workflows/ci.yml/badge.svg)](https://github.com/LeoLoudWarden/sericite/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sericite)](https://pypi.org/project/sericite/)
[![Python](https://img.shields.io/pypi/pyversions/sericite)](https://pypi.org/project/sericite/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/LeoLoudWarden/sericite/blob/main/LICENSE)

**Sericite** is a scripting language and its execution engine, built around a single idea: creating a fully isolated, arbitrarily nestable runtime environment should be a cheap, first-class operation in the language itself.

Syntax borrows a subset of Python, but Sericite source is compiled into Sericite's own instruction stream and executed by the Sericite engine — never through `exec`/`eval`. Every VM starts with zero capabilities: its own virtual IO, its own in-memory filesystem, and the ability to create child VMs. Everything else (network, host data, whatever you choose) is granted explicitly, layer by layer, through FFI.

[中文文档](https://github.com/LeoLoudWarden/sericite/blob/main/README.zh-CN.md)

## Status

Pre-1.0 prototype. The engine is a Python reference implementation (codename **Sericite-PY**): zero runtime dependencies, Python ≥ 3.12. APIs and semantics may change before 1.0.

> **Security note.** Sericite is designed for isolation, but the current prototype runs in the host process and has not been formally audited. Do not rely on it as the *only* boundary when executing adversarial code. See the [security model](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.md) for exactly what is and is not guaranteed.

## Install

```bash
pip install sericite
```

The distribution is named `sericite`; the import package is `sericite`.

## Quick start

As a CLI:

```bash
sericite -c 'print("hello from sericite")'
printf 'print("hello from sericite")\n' > hello.sericite
sericite hello.sericite        # hello from sericite
sericite                       # start the REPL; EOF exits
sericite -c 'print(argv)' first second
```

For source reuse and root-application capabilities:

```bash
sericite --include base.sericite app.sericite
sericite --capabilities capabilities.py app.sericite
```

Includes compose source in order in one root scope; capabilities are operator-trusted Python configuration limited to FFI, limits, and initial VFS files. See the [CLI reference](https://github.com/LeoLoudWarden/sericite/blob/main/docs/cli-reference.md) for the contract and the [root-agent demo](https://github.com/LeoLoudWarden/sericite/blob/main/demos/root-agent/README.md) for a complete application. Embed Python when an existing host needs to own VM lifecycles:

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("""
sub = VM("print('hello from a child VM')")
print(sub.run())
""")
print(vm.run(), end="")
```

Grant a capability to a VM (FFI):

```python
def double(x):
    return x * 2

vm = engine.create_root("print(double(21))", functions={"double": double})
print(vm.run(), end="")    # 42
```

## What a Sericite VM is

A VM is a cheap, self-contained workspace:

- it cannot see its parent's variables, files, or handles, and cannot tell how deep it is nested;
- it has its own empty in-memory filesystem (text only — structurally unable to touch the real disk);
- resource quotas (instructions, memory, output, child VMs, nesting depth, …) can only be tightened, never loosened, and a child's consumption is charged to all its ancestors;
- its parent can preset files, feed input, single-step it statement by statement or instruction by instruction, snapshot its state, or terminate it;
- it can create its own child VMs — isolation is recursive, because untrusted code is.

Cheap is measured, not just claimed: in the current Python prototype, creating a child VM from inside a script costs ~0.088 ms — the same order as spawning a thread, one to two orders of magnitude below a process. More measurements and reproduction scripts are in the [architecture notes](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.md) §6 and [benchmarks/](https://github.com/LeoLoudWarden/sericite/tree/main/benchmarks).

## Records: type names are compile-time error labels

Since 0.4, Sericite has user-defined objects with members. Its view of types follows the same discipline as VM isolation: **structure travels across layers; names stay local to a layer.**

- A schema (the structural contract defined by `class`) is anonymous: two isomorphic schemas defined separately are equal — there are no nominal types;
- A record carries only data and contracts. A type name is a compile-time, scope-local transparent alias (like an Elm `type alias`) used solely in error text — it plays no role in equality or contract checks and is erased beyond its scope;
- Naming is a local act of the receiver: the same value may carry different names in different scopes, or none at all.

Rationale: [design notes §3.4](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.md); full semantics and examples: [language reference §7](https://github.com/LeoLoudWarden/sericite/blob/main/docs/language-reference.md).

## Documentation

| English | 中文 |
|---|---|
| [Design notes](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.md) | [设计说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.zh-CN.md) |
| [Prior art](https://github.com/LeoLoudWarden/sericite/blob/main/docs/prior-art.md) | [先例与相关工作](https://github.com/LeoLoudWarden/sericite/blob/main/docs/prior-art.zh-CN.md) |
| [CLI reference](https://github.com/LeoLoudWarden/sericite/blob/main/docs/cli-reference.md) | [CLI 参考](https://github.com/LeoLoudWarden/sericite/blob/main/docs/cli-reference.zh-CN.md) |
| [Language reference](https://github.com/LeoLoudWarden/sericite/blob/main/docs/language-reference.md) | [语言参考](https://github.com/LeoLoudWarden/sericite/blob/main/docs/language-reference.zh-CN.md) |
| [VM reference](https://github.com/LeoLoudWarden/sericite/blob/main/docs/vm-reference.md) | [虚拟机参考](https://github.com/LeoLoudWarden/sericite/blob/main/docs/vm-reference.zh-CN.md) |
| [Sericite-PY reference](https://github.com/LeoLoudWarden/sericite/blob/main/docs/sericite-py-reference.md) | [Sericite-PY 参考](https://github.com/LeoLoudWarden/sericite/blob/main/docs/sericite-py-reference.zh-CN.md) |
| [Architecture](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.md) | [架构说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.zh-CN.md) |
| [Security model](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.md) | [安全模型](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.zh-CN.md) |
| [Build journal](https://github.com/LeoLoudWarden/sericite/blob/main/docs/stages/README.md) | [构建手记](https://github.com/LeoLoudWarden/sericite/blob/main/docs/stages/README.zh-CN.md) |
| [Behind the scenes](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/README.md) | [幕后](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/README.zh-CN.md) |

What each document covers and whom it serves is maintained in the [documentation index](https://github.com/LeoLoudWarden/sericite/blob/main/docs/README.md). The build-journal and behind-the-scenes articles are Chinese-only (their index pages have English versions); full translations are not planned — they are frozen history.

## How this project was built

Sericite was developed with AI assistance throughout — design discussion, implementation, testing, adversarial review, and documentation drafting. What the AI did, what the author did, and how outputs were verified are documented in [AI-assisted development](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/ai-assisted-development.md) (English summary; [full record 中文](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/ai-assisted-development.zh-CN.md)), with selected conversation records alongside.

## Roadmap

- More list/dict methods, string methods, and additional ergonomic syntax
- Performance benchmarks: VM creation, per-instruction execution, and debugging costs measured (see [benchmarks/](https://github.com/LeoLoudWarden/sericite/tree/main/benchmarks)); broader workload coverage still pending
- A normative language spec and a conformance test suite, so a future non-Python engine can be validated against them
- Evaluation of a native engine (the package name is language-level on purpose: `sericite` survives an engine rewrite)

## The name

Sericite (绢云母) is the finest-grained member of the mica family: thin silky scales that stack into sheets, and an insulator like every mica — the name keeps the three promises the project is named after: layering, insulation, lightness. (The project was briefly named Mica/MicaLang and renamed after finding the name taken.) The full story is in the [design notes](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.md) §6.

## License

[Apache-2.0](https://github.com/LeoLoudWarden/sericite/blob/main/LICENSE) — see [NOTICE](https://github.com/LeoLoudWarden/sericite/blob/main/NOTICE).
