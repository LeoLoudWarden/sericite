# Sericite CLI Reference

[中文](cli-reference.zh-CN.md)

This document is for operators running Sericite programs directly. It describes the shared behavior of `sericite` and `python -m sericite`.

## 1. Ways to run

```bash
sericite
sericite app.sericite
sericite --capabilities capabilities.py app.sericite
```

- **REPL**: start an interactive session on a persistent root when no source entry is given.
- **Plain CLI**: run a Sericite program using only built-in capabilities.
- **CLI + capabilities**: a Python file supplies trusted FFI, limits, and initial VFS files while the application itself runs in the root Sericite VM; this also works with the REPL.
- **Python embedding**: an existing host uses `SericiteEngine` directly without the CLI; see the [Sericite-PY reference](sericite-py-reference.md).

`sericite` is the installed command; use `uv run sericite` in a source checkout. `python -m sericite` uses the same entry point.

## 2. Commands and options

```text
sericite [-h] [--version] [--capabilities FILE] [--include FILE ...]
         [(SOURCE_FILE | -c SOURCE) [ARG ...]]
```

| Option | Meaning |
|---|---|
| `-h`, `--help` | Show help and exit |
| `--version` | Show the runtime version |
| `SOURCE_FILE` | Read and run a UTF-8 source file; `-` reads all source from stdin; omit it for the REPL |
| `-c SOURCE`, `--command SOURCE` | Execute a source string directly |
| `ARG ...` | Arguments passed to the script without CLI interpretation |
| `--capabilities FILE` | Call `configure()` in a trusted Python file to configure the root VM |
| `--include FILE` | Prepend a source file before the main source or REPL; repeat in the desired order |

`SOURCE_FILE` and `-c` are mutually exclusive; omitting both enters the REPL. Put CLI options before the source entry. Everything after the entry belongs to the script, including dash-prefixed values such as `--flag` and a standalone `--`. Use `--` before the entry to end CLI options explicitly or to pass a filename beginning with a dash; that pre-entry separator is consumed by the CLI and does not enter `argv`. Paths resolve against the current working directory; `.sericite` is a convention, not an enforced suffix.

Main and included files are decoded as UTF-8, with one optional leading UTF-8 BOM ignored. Stdin source follows the same rule. Only a BOM at the start of the text is removed, so line and column positions are unchanged and any additional BOM remains ordinary source input.

```bash
sericite -c 'print("hello")'
sericite -c 'print(argv)' first --flag
printf 'print("hello")\n' | sericite -
sericite --include base.sericite --include util.sericite app.sericite first
sericite --capabilities capabilities.py -c 'run()'
```

There is currently no individual command-line flag for each limit. `python -m sericite` accepts the same options.

### REPL

With neither `SOURCE_FILE` nor `-c`, the CLI creates a persistent root, runs the includes, and enters an interactive loop:

- `>>>` waits for a new entry and `...` waits for a multiline statement to finish; blank input is not executed.
- Variables, functions, schemas, and the VFS persist across entries, each delivered through the root's `exec()`.
- A single expression echoes its result with `repr`; other statements produce only their own output.
- A compilation or runtime error goes to stderr and the session continues. An include or capability startup failure still exits with status 1.
- EOF exits the REPL normally with status 0. Script `input()` still reads host stdin; EOF raises a catchable `input_error`. If the script does not catch it, the error is printed and the session continues.

History, completion, advanced line editing, and debugging commands are not included.

### Script argv

The root module starts with a string-list variable named `argv`:

- `[SOURCE_FILE, *ARG]` in file mode;
- `["-c", *ARG]` in command mode;
- `["-", *ARG]` for stdin source;
- `[]` in the REPL.

It is an ordinary module variable: it can be read, modified, or rebound, and it persists across `exec()` deliveries. Child VMs do not inherit it implicitly. Embedded roots can set it with `create_root(argv=...)`; see the [Sericite-PY reference](sericite-py-reference.md) §2.

## 3. Includes: source composition in one root

`--include` is a CLI code-reuse facility, not Sericite `import` — a future module system is a separate design, with no promise of include-compatible semantics:

1. One-shot mode reads every include in option order, followed by the main file, command, or stdin source. The REPL startup unit contains only includes.
2. Combine all text into **one compilation unit**, running in one root VM and one module-global scope.
3. Functions, variables, and side effects are shared in order; the main source or later REPL entries can use included names directly.
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

Error diagnostics mark positions by source of origin:

- includes and the main file map back to the original file and its local line number;
- a command string appears as `<command>` and stdin source as `<stdin>`;
- nested VMs retain `<sericite:vm_N>`.

Runtime errors append a traceback after the one-line summary. For example, `sericite --include runtime.sericite -c 'outer()'` prints:

```text
/path/runtime.sericite:2: name_error: name 'missing' is not defined
Traceback (most recent call last):
  File "<command>", line 1, in <module>
  File "/path/runtime.sericite", line 5, in outer
  File "/path/runtime.sericite", line 2, in inner
```

Traceback frame lines follow the same source rules (`<command>` in the example is the `-c` source):

- in the REPL, each frame maps to the input that defined its code; the current input's line adjustment applies only to that input;
- functions defined in includes always keep the include filename and local line;
- when the source is unavailable, the CLI shows `<sericite>` and `line ?`; frames defined in another VM do not disclose their line and show `line ?` (redaction rules are in the [language reference](language-reference.md) §5).

Errors rejected before VM execution begins have no traceback and retain the single-line diagnostic.

## 4. Capabilities: trusted Python startup configuration

### 4.1 Configuration entry point

The file passed to `--capabilities FILE` must define a zero-argument `configure()`. Loading the file executes its top-level code (`runpy.run_path`); the CLI then calls `configure()` once, before creating the engine or executing any Sericite code:

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

- Startup fails on unknown keys, a missing or non-callable `configure()`, a non-dict return, or invalid field types.
- The engine still validates grant names in `functions`.
- `files` uses the public VM handle and remains subject to file-count, per-file-byte, and other limits.
- A trusted long-running root may set cumulative quotas to `-1`; structural quotas remain finite. See the [security model](security.md) §3 for the resource-safety implications.

See the [Sericite-PY reference](sericite-py-reference.md) for the FFI rules and the [VM reference](vm-reference.md) §5 for quota fields and unlimited-inheritance rules; they are not duplicated here.

A capability file can use `__file__` to locate its resources. It is not a Sericite module, its directory need not be a Python package, and the CLI does not create a Sericite module search path.

### 4.2 Trust boundary

> **A capability file has full host privileges. Trust it as you would any Python file you execute.**

- It can import third-party libraries, read environment variables and the real disk, and access the network.
- Its Python does **not** run inside the Sericite sandbox, and its CPU, memory, and external side effects are not metered by the engine (cost responsibility: [Sericite-PY reference](sericite-py-reference.md) §5.4).
- Only the operator may select this file; never let a model or Sericite source choose it.

Main and included sources still run in the root VM and gain no host privileges merely because a capability file exists. They can call only explicitly granted functions. `files` initializes only the root's in-memory VFS; it does not map the real disk.

The execution order is fixed:

```text
read source → run configure() → create and compile root → seed VFS → run → output
```

A capability file cannot take over the session loop or VM driving. Use the Python API for that embedding style rather than adding lifecycle hooks to the CLI.

## 5. Input, output, and exit codes

- In file, `-c`, and REPL modes, script `input()` reads host stdin line by line. EOF raises a catchable `input_error`; an uncaught error in one-shot mode is printed with its traceback and exits with status 1.
- `sericite -` consumes all stdin as source, so runtime `input()` sees the closed stream and raises `input_error`.
- Every root `print()` writes immediately to host stdout and flushes, including unterminated output with `end=""`; there is no need to wait for program exit. The CLI does not retain a duplicate root stdout buffer. Child output remains explicit: a parent obtains it through APIs such as `sub.run()` (see the [VM reference](vm-reference.md) §4 for output forwarding).
- If a downstream stdout pipe closes, the CLI discards further output and exits quietly with status 0 instead of turning the host `BrokenPipeError` into a script error.
- Compile/runtime errors go to stderr without discarding root output already produced. Configuration errors also go only to stderr. One-shot mode exits after an error; the REPL continues after an entry error.

| Exit code | Meaning |
|---:|---|
| 0 | Root completed normally, the REPL ended with EOF, or the downstream stdout pipe closed |
| 1 | File/configuration loading or validation failed, one-shot execution or REPL startup failed, or one-shot input was exhausted (`input_error`) |
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
