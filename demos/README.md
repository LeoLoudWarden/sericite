# Sericite Application Demos

[中文](README.zh-CN.md)

`demos/` contains complete applications spanning multiple components; `examples/` contains small, directly runnable language snippets.

| Demo | Form | What it shows |
|---|---|---|
| [root-agent](root-agent/README.md) | Thin Python capabilities + root Sericite application | Multi-layer LLM sessions and nested VMs, with an offline stub |
| [sorting-arena](sorting-arena/README.md) | Thin Python seeding + root Sericite judge | Untrusted-code tournament; correctness, instruction-count ranking, and multiple elimination paths |
| [sericite-debugger](sericite-debugger/README.md) | Pure root Sericite debugger | Statement/instruction stepping, watchpoints, and D(D(P)) self-debugging |

See the [CLI reference](../docs/cli-reference.md) for invocation and the general configuration contract. To embed VMs in an existing Python lifecycle, use the host API in the [Sericite-PY reference](../docs/sericite-py-reference.md).
