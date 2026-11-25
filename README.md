# Sericite

[![CI](https://github.com/LeoLoudWarden/sericite/actions/workflows/ci.yml/badge.svg)](https://github.com/LeoLoudWarden/sericite/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sericite)](https://pypi.org/project/sericite/)
[![Python](https://img.shields.io/pypi/pyversions/sericite)](https://pypi.org/project/sericite/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/LeoLoudWarden/sericite/blob/main/LICENSE)

**Sericite** is a scripting language and execution engine built around one idea: creating a fully isolated, arbitrarily nestable VM should be a cheap, first-class operation in the language itself.

Its syntax is a Python subset, but source code runs as Sericite's own instruction stream — never through Python `exec`/`eval`.

[中文文档](https://github.com/LeoLoudWarden/sericite/blob/main/README.zh-CN.md)

## Status

Pre-1.0 prototype. The engine is a Python reference implementation (codename **Sericite-PY**) with zero runtime dependencies; Python ≥ 3.12 is required. APIs and semantics may change before 1.0.

> **Security note.** Sericite is designed for isolation, but the current prototype runs in the host process and has not been formally audited. Do not rely on it as the *only* boundary when executing adversarial code. See the [security model](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.md) for exactly what is and is not guaranteed.

## Install

```bash
pip install sericite
```

## Your first isolated program

Create `play.sericite`. A fresh VM looks for a file written before it existed, then leaves an answer in its own workspace:

```python
write_file("/before.txt", "already here")

vm = VM("""
print(path_exists("/before.txt"))
write_file("/answer.txt", "42")
""")

print(vm.run(), end="")
workspace = vm.take_fs()
print(workspace.read_file("/answer.txt"))
```

Run it:

```bash
sericite play.sericite
```

Output:

```text
False
42
```

## An arena for untrusted code

Nine mutually untrusted programs enter a sorting tournament. Correct algorithms compete on instruction count; attempts to steal the answer, infinite loops, and output floods are disqualified without stopping the judge.

```bash
git clone https://github.com/LeoLoudWarden/sericite.git
cd sericite
sericite --addons demos/sorting-arena/addons.py demos/sorting-arena/arena.sericite
```

An output excerpt (each run uses fresh random test cases):

```text
  RANK  CONTESTANT                  TOTAL INSTRUCTIONS
  1     quicksort               15,383
  ...
  DQ    answer-thief            file_not_found
  DQ    output-flood            resource_exhausted
  DQ    infinite-loop           resource_exhausted
  ...
  The arena survived every submission. The scoreboard only counts correct code.
```

[How it works](https://github.com/LeoLoudWarden/sericite/blob/main/demos/sorting-arena/README.md)

## Learn more

| Next step | English | 中文 |
|---|---|---|
| Explore more complete applications | [More demos](https://github.com/LeoLoudWarden/sericite/blob/main/demos/README.md) | [更多演示](https://github.com/LeoLoudWarden/sericite/blob/main/demos/README.zh-CN.md) |
| Write Sericite programs | [Sericite scripting manual](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/scripting/README.md) | [Sericite 脚本手册](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/scripting/README.zh-CN.md) |
| Run programs from a terminal | [Sericite CLI manual](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/cli/README.md) | [Sericite 命令行手册](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/cli/README.zh-CN.md) |
| Embed Sericite in a Python application | [Sericite-PY manual](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/host-python/README.md) | [Sericite-PY 手册](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/host-python/README.zh-CN.md) |

## Documentation

| English | 中文 |
|---|---|
| [Design notes](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.md) | [设计说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.zh-CN.md) |
| [Prior art](https://github.com/LeoLoudWarden/sericite/blob/main/docs/prior-art.md) | [先例与相关工作](https://github.com/LeoLoudWarden/sericite/blob/main/docs/prior-art.zh-CN.md) |
| [Architecture](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.md) | [架构说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.zh-CN.md) |
| [Security model](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.md) | [安全模型](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.zh-CN.md) |
| [Benchmarks](https://github.com/LeoLoudWarden/sericite/tree/main/benchmarks) | [性能基准](https://github.com/LeoLoudWarden/sericite/tree/main/benchmarks) |
| [Build journal](https://github.com/LeoLoudWarden/sericite/blob/main/docs/stages/README.md) | [构建手记](https://github.com/LeoLoudWarden/sericite/blob/main/docs/stages/README.zh-CN.md) |
| [Behind the scenes](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/README.md) | [幕后](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/README.zh-CN.md) |
| [AI-assisted development](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/ai-assisted-development.md) | [AI 辅助开发](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/ai-assisted-development.zh-CN.md) |

What each document covers and whom it serves is maintained in the [documentation index](https://github.com/LeoLoudWarden/sericite/blob/main/docs/README.md).

## Roadmap

- More list/dict methods, string methods, and additional ergonomic syntax
- Broader performance benchmark coverage
- A normative language spec and a conformance test suite for future engines
- Evaluation of a native engine

## The name

Sericite (绢云母) is a fine-grained mica: thin silky scales that stack into sheets and insulate. The name reflects layering, isolation, and lightness.

## License

[Apache-2.0](https://github.com/LeoLoudWarden/sericite/blob/main/LICENSE) — see [NOTICE](https://github.com/LeoLoudWarden/sericite/blob/main/NOTICE).
