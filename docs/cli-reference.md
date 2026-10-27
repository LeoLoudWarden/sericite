# Sericite CLI Reference

[中文](cli-reference.zh-CN.md)

This document is for operators running Sericite programs directly. It describes the shared behavior of `sericite` and `python -m sericite`. See the [language reference](language-reference.md) for script semantics, or the [host reference](host-reference.md) to embed the engine and drive VMs from Python.

## 1. Three ways to run

```bash
sericite app.sericite
sericite --capabilities capabilities.py app.sericite
```

- **Plain CLI**: run a Sericite program using only built-in capabilities.
- **CLI + capabilities**: a Python file supplies trusted FFI, limits, and initial VFS files while the application itself runs in the root Sericite VM.
- **Python embedding**: an existing host uses `SericiteEngine` directly without the CLI; see the host reference.

`sericite` is the installed command; use `uv run sericite` in a source checkout. `python -m sericite` uses the same entry point.

## 2. Commands and options

```text
sericite [-h] [--version] [--capabilities FILE] [--include FILE ...]
         (SOURCE_FILE | -c SOURCE)
```

| Option | Meaning |
|---|---|
| `-h`, `--help` | Show help and exit |
| `--version` | Show the runtime version |
| `SOURCE_FILE` | Read and run a UTF-8 source file; `-` reads all source from stdin |
| `-c SOURCE`, `--command SOURCE` | Execute a source string directly |
| `--capabilities FILE` | Call `configure()` in a trusted Python file to configure the root VM |
| `--include FILE` | Prepend a source file; repeat in the desired order |

`SOURCE_FILE` and `-c` are mutually exclusive, and one is required. Paths resolve against the current working directory; use `--` before a filename beginning with a dash. `.sericite` is a convention, not an enforced suffix.

```bash
sericite -c 'print("hello")'
printf 'print("hello")\n' | sericite -
sericite --include base.sericite --include util.sericite app.sericite
sericite --capabilities capabilities.py -c 'run()'
```

There is currently no REPL, script argv, or individual command-line flag for each limit. `python -m sericite` accepts the same options.

## 3. Includes: source composition in one root

`--include` is a CLI code-reuse facility, not Sericite `import`:

1. Read every include in option order, followed by the main file, command, or stdin source.
2. Combine all text into **one compilation unit**, running in one root VM and one module-global scope.
3. Functions, variables, and side effects are shared in order; the main source can call included functions directly.
4. There is no deduplication, cache, namespace, or child VM. Repeating an include repeats its execution.
5. Execution starts only after the combined source compiles. If any part fails compilation, no part has run.
6. The combined source remains subject to the engine's 4MB limit.

For example, `math_utils.sericite`:

```python
def double(x):
    return x * 2
```

Run:

```bash
sericite --include math_utils.sericite -c 'print(double(21))'
# 42
```

Root error locations map back to the original include/main file and its local line number. Commands appear as `<command>` and stdin as `<stdin>`; nested VMs retain `<sericite:vm_N>`. A future module system is a separate design, with no promise of include-compatible semantics.

## 4. Capabilities: trusted Python startup configuration

### 4.1 Configuration entry point

The file passed to `--capabilities FILE` must define a zero-argument `configure()`. The CLI calls it once before creating the engine or executing any Sericite code:

```python
from sericite import SericiteLimits


def double(x):
    return x * 2


def configure():
    return {
        "functions": {"double": double},
        "limits": SericiteLimits(max_instructions=100_000),
        "files": {"/message.txt": "hello from the initial VFS"},
    }
```

It returns a dict. Every key is optional; an empty dict is equivalent to no configuration:

| Key | Type and purpose |
|---|---|
| `functions` | `dict[str, callable]`; host functions granted to root, using the normal FFI data and exception contracts |
| `limits` | `SericiteLimits`; the complete limits configuration for this root |
| `files` | `dict[str, str]`; virtual paths and text written to the root VFS before execution |

Startup fails on unknown keys, a missing or non-callable `configure()`, a non-dict return, or invalid field types. The engine still validates grant names. `files` uses the public VM handle and remains subject to file-count, per-file-byte, and other limits. See the [host reference](host-reference.md) for those authoritative rules.

A capability file can use `__file__` to locate its resources. It is not a Sericite module, its directory need not be a Python package, and the CLI does not create a Sericite module search path.

### 4.2 Trust boundary

> **A capability file has full host privileges. Trust it as you would any Python file you execute.**

It can import third-party libraries, read environment variables and the real disk, and access the network. Its Python does **not** run inside the Sericite sandbox, and its CPU, memory, and external side effects are not metered by the engine. Only the operator may select this file; never let a model or Sericite source choose it.

Main and included sources still run in the root VM and gain no host privileges merely because a capability file exists. They can call only explicitly granted functions. `files` initializes only the root's in-memory VFS; it does not map the real disk.

The execution order is fixed:

```text
read source → run configure() → create and compile root → seed VFS → run → output
```

A capability file cannot take over the session loop or VM driving. Use the Python API for that embedding style rather than adding lifecycle hooks to the CLI.

## 5. Input, output, and exit codes

- In file and `-c` modes, script `input()` reads host stdin line by line. Requesting more input after EOF fails with `input_error`.
- `sericite -` consumes all stdin as source, so that stdin cannot also supply runtime input.
- Every root `print()` writes immediately to host stdout and flushes, including unterminated output with `end=""`; there is no need to wait for program exit. Child output remains explicit: a parent obtains it through APIs such as `sub.run()`.
- Compile/runtime errors go to stderr without discarding root output already produced. Configuration errors also go only to stderr.

| Exit code | Meaning |
|---:|---|
| 0 | Root completed normally |
| 1 | File/configuration loading or validation failed, compilation/runtime failed, or input was exhausted |
| 2 | Command-line usage error |

Process-level events such as `KeyboardInterrupt` and `SystemExit` are not swallowed as ordinary script or configuration errors.

## 6. `.sericite` in editors

Sericite borrows a Python syntax subset. Until a dedicated extension is available, a VS Code workspace can use:

```json
{
  "files.associations": {
    "*.sericite": "python"
  }
}
```

This provides highlighting, indentation, and bracket matching only. Python linters do not understand Sericite's allowlist, built-ins, or runtime contracts and cannot replace real compilation diagnostics from the CLI.

For a complete root-driven application, see [`demos/root-agent/`](../demos/root-agent/README.md).
