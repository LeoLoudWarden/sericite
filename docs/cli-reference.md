# Sericite CLI Reference

[中文](cli-reference.zh-CN.md)

This document is for operators running Sericite programs directly. It describes the shared behavior of `sericite` and `python -m sericite`.

## 1. Ways to run

```bash
sericite
sericite app.sericite
sericite --capabilities capabilities.py app.sericite
```

- **REPL**: start a persistent interactive session when no source entry is given.
- **Plain CLI**: run a Sericite program using only built-in capabilities.
- **CLI + capabilities**: a Python file supplies trusted functions, limits, and initial files while the application itself runs in an isolated Sericite environment; this also works with the REPL.
- **Python embedding**: an existing host uses `SericiteEngine` directly without the CLI; see the [Sericite-PY reference](sericite-py-reference.md).

`sericite` is the installed command; use `uv run sericite` in a source checkout. `python -m sericite` uses the same entry point.

## 2. Commands and options

```text
sericite [-h] [--version] [--capabilities FILE]
         [(SOURCE_FILE | -c SOURCE) [ARG ...]]
```

| Option | Meaning |
|---|---|
| `-h`, `--help` | Show help and exit |
| `--version` | Show the runtime version |
| `SOURCE_FILE` | Read and run a UTF-8 source file and its statically reachable modules; `-` reads all source from stdin; omit it for the REPL |
| `-c SOURCE`, `--command SOURCE` | Execute a source string directly |
| `ARG ...` | Arguments passed to the script without CLI interpretation |
| `--capabilities FILE` | Call `configure()` in a trusted Python file to configure the entry program |

`SOURCE_FILE` and `-c` are mutually exclusive; omitting both enters the REPL. Put CLI options before the source entry. Everything after the entry belongs to the script, including dash-prefixed values such as `--flag` and a standalone `--`.

A `--` before the entry explicitly ends CLI options and can pass a filename beginning with a dash. That pre-entry `--` is consumed by the CLI and does not enter `argv`. Paths resolve against the current working directory; `.sericite` is a convention, not an enforced suffix.

The main file, statically reachable modules, and stdin source are decoded as UTF-8, with one optional leading UTF-8 BOM ignored; line and column positions are counted after that BOM is removed.

```bash
sericite -c 'print("hello")'
sericite -c 'print(argv)' first --flag
printf 'print("hello")\n' | sericite -
sericite app.sericite first
sericite --capabilities capabilities.py -c 'run()'
```

There is currently no individual command-line flag for each limit. `python -m sericite` accepts the same options.

### REPL

With neither `SOURCE_FILE` nor `-c`, the CLI creates a persistent session and enters an interactive loop:

- `>>>` waits for a new entry and `...` waits for a multiline statement to finish; blank input is not executed.
- Variables, functions, schemas, imported modules, and files persist across entries.
- A single expression echoes its result with `repr`; other statements produce only their own output.
- A compilation or runtime error goes to stderr and the session continues. A capability startup failure still exits with status 1.
- EOF exits the REPL normally with status 0.

History, completion, advanced line editing, and debugging commands are not included.

### Script argv

The entry program starts with a string-list variable named `argv`:

- `[SOURCE_FILE, *ARG]` in file mode;
- `["-c", *ARG]` in command mode;
- `["-", *ARG]` for stdin source;
- `[]` in the REPL.

It is an ordinary module variable: it can be read, modified, or rebound, and it persists across entries. Child VMs do not inherit it implicitly. Embedded roots can set it with `create_root(argv=...)`; see the [Sericite-PY reference](sericite-py-reference.md) §2.

### Error diagnostics and source mapping

In diagnostics, the entry uses the path supplied by the operator, while imported modules use virtual paths such as `/pkg/mod.sericite`. Commands appear as `<command>` and stdin as `<stdin>`. Each traceback frame uses its own file and local line number.

In the REPL, each frame maps to the input that defined its code, and the current input's line adjustment applies only to that input. Unknown sources show `<sericite>` and `line ?`; code defined in another workspace does not disclose its line and shows `line ?` (redaction rules are in the [language reference](language-reference.md) §5).

Syntax errors found in the entry during startup have no traceback and retain the single-line diagnostic. Errors in imported modules can be caught according to the language rules and carry a traceback.

## 3. Multi-file projects and import

File mode treats the entry file's directory as the project root. The CLI copies the entry and statically import-reachable `.sericite` files into the program's virtual filesystem (VFS) at the same relative paths, then executes the entry normally:

```text
project/
  main.sericite
  math_utils.sericite
```

```python
# main.sericite
from math_utils import double
print(double(21))
```

```bash
sericite project/main.sericite
# 42
```

Packages, dotted modules, and relative imports use the same VFS paths; see the [language reference](language-reference.md) §9 for language semantics. Project loading has these boundaries:

- Only statically reachable sources are copied, not the whole directory; unreferenced sources and data files read with `read_file()` do not enter the VFS through this mechanism.
- Candidate files whose resolved symlinks escape the entry directory are not loaded.
- Copying creates a startup snapshot. Actual imports still read only the VFS and never dynamically read the real disk when execution reaches the statement.
- Imports that are not executed remain lazy; missing, invalid, or circular modules fail according to the language rules only when reached.
- `-c`, stdin, and the REPL do not create a directory snapshot and import only from the existing VFS; `--capabilities` can preset modules through `files`.
- Project files are written first and capability `files` second, so the latter can explicitly override the same VFS path.

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
| `functions` | `dict[str, callable]`; Python functions granted to the entry program, using the normal FFI data and exception contracts |
| `limits` | `SericiteLimits`; the complete limits configuration for the entry program |
| `files` | `dict[str, str]`; virtual paths and text written to the program VFS before execution |

- Startup fails on unknown keys, a missing or non-callable `configure()`, a non-dict return, or invalid field types.
- Grant names in `functions` are still validated by the language rules.
- `files` remains subject to file-count, per-file-byte, and other limits.
- A trusted long-running program may set cumulative quotas to `-1`; live VM counts and other structural quotas remain finite. See the [security model](security.md) §3 for the resource-safety implications.

See the [Sericite-PY reference](sericite-py-reference.md) for the FFI rules and the [VM reference](vm-reference.md) §5 for quota fields and unlimited-inheritance rules; they are not duplicated here.

A capability file can use `__file__` to locate its resources. It is not a Sericite module, its directory need not be a Python package, and the CLI does not create a Sericite module search path.

### 4.2 Trust boundary

> **A capability file has full host privileges. Trust it as you would any Python file you execute.**

- It can import third-party libraries, read environment variables and the real disk, and access the network.
- Its Python does **not** run inside the Sericite sandbox, and its CPU, memory, and external side effects are not metered by the engine (cost responsibility: [Sericite-PY reference](sericite-py-reference.md) §6.4).
- Only the operator may select this file; never let a model or Sericite source choose it.

Main and imported sources still run in the same Sericite workspace and gain no host privileges merely because a capability file exists. They can call only explicitly granted functions. `files` initializes only the program's in-memory VFS; it does not map the real disk.

The execution order is fixed:

```text
read source and snapshot project VFS → run configure() → create and compile the entry program → seed/override VFS → run → output
```

A capability file cannot take over the session loop or execution flow. Use the Python API for that embedding style rather than adding lifecycle hooks to the CLI.

## 5. Input, output, and exit codes

The CLI standard streams inherit the runtime environment's encoding rather than being reconfigured. In a non-UTF-8 environment such as Windows, you can set `$env:PYTHONUTF8 = "1"` in the current PowerShell session and then run the same CLI commands with UTF-8 standard streams. This setting only configures the runtime environment: source files still follow the UTF-8 contract in §2, and the embedding API's strings, virtual IO, and callback interfaces are unchanged.

- Script `input()` reads standard input line by line; EOF raises a catchable `input_error`. If uncaught in one-shot mode, the traceback is printed and the process exits with status 1; if uncaught in the REPL, the error is printed and the session continues.
- `sericite -` consumes all stdin as source, so runtime `input()` sees the closed stream and raises `input_error`.
- Every program `print()` writes immediately to standard output and flushes, including unterminated output with `end=""`; there is no need to wait for program exit. The CLI does not retain a duplicate program-output buffer. Child output remains explicit: a parent obtains it through APIs such as `sub.run()` (see the [VM reference](vm-reference.md) §4 for output forwarding).
- If a downstream standard-output pipe closes, the external output consumer has ended: the CLI stops the current execution, including nested VM output forwarding, discards further output, and exits quietly with status 0. This is external CLI termination, not a Sericite script error; Sericite `finally` blocks are not guaranteed to run.
- Compile/runtime errors go to stderr without discarding output the program already produced. Configuration errors also go only to stderr. One-shot mode exits after an error; the REPL continues after an entry error.

| Exit code | Meaning |
|---:|---|
| 0 | The program completed normally, the REPL ended with EOF, or the downstream standard-output pipe closed |
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

For a complete application, see [`demos/root-agent/`](../demos/root-agent/README.md).
