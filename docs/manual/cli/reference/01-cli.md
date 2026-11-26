# CLI Reference

This document defines the shared behavior of `sericite` and `python -m sericite`, for checking options, configuration, diagnostics, and exit behavior. For examples organized by task, see the [CLI guides](../README.md#guides).

## Commands and options

```text
sericite [-h] [--version] [--addons FILE]
         [(SOURCE_FILE | -c SOURCE) [ARG ...]]
```

| Option | Meaning |
|---|---|
| `-h`, `--help` | Show help and exit |
| `--version` | Show the runtime version and exit |
| `SOURCE_FILE` | Read and run a UTF-8 source file and its statically reachable modules; `-` reads the complete program from stdin |
| `-c SOURCE`, `--command SOURCE` | Execute a source string directly |
| `ARG ...` | Arguments passed to the script, no longer interpreted by the command line |
| `--addons FILE` | Call `configure()` in a trusted Python file to configure the entry program |

Omitting both `SOURCE_FILE` and `-c` enters the REPL. `.sericite` is a conventional suffix; the command line does not enforce it. File paths resolve against the current working directory.

CLI options go before the source entry. Everything after the entry belongs to the script, including `--flag` and a standalone `--`. Writing `--` before the entry explicitly ends CLI options and can also pass a filename that begins with a dash; this `--` is consumed by the CLI and does not enter `argv`.

### `argv`

The entry program starts with a string-list variable named `argv`:

| Entry | Initial value |
|---|---|
| File mode | `[SOURCE_FILE, *ARG]`, keeping the entry path as written in the command |
| `-c` mode | `["-c", *ARG]` |
| stdin source mode | `["-", *ARG]` |
| REPL | `[]` |

`argv` is an ordinary module variable: it can be read, modified, or rebound, and it persists across REPL entries. Child VMs do not inherit it implicitly.

### Source encoding

The main file, statically reachable modules, and stdin source are decoded as UTF-8, with one optional leading UTF-8 BOM ignored; line and column positions in diagnostics are computed from the text after that BOM is removed.

## Multi-file projects

File mode treats the entry file's directory as the project root. The CLI copies the entry file and the statically import-reachable `.sericite` files into the entry VM's virtual file system (VFS), keeping their paths relative to the project root, then executes the entry.

Project loading follows these rules:

- Only statically import-reachable source is copied, not the whole directory. Unreferenced sources and data files do not enter the VFS through this mechanism.
- The startup scan collects imports from the syntax, including imports inside functions and conditional branches; actual modules are still loaded only when execution reaches the import statement.
- Candidate files whose resolved symlinks escape the entry directory are not loaded.
- Actual imports read only the VFS and never return to the real disk to find modules. Changes made to virtual files while running are not written back to the project directory.
- Imports that are not executed stay lazy; missing, invalid, or circular modules fail according to the language rules only when execution actually reaches them.
- `-c`, stdin, and the REPL do not scan the current directory and import only from the existing VFS; modules can be preset through the addon `files`.

For module resolution and import semantics, see [modules and packages](../../scripting/reference/01-language.md#modules-and-packages).

The file entry writes the project snapshot first, then the addon `files`. When both contain the same virtual path, the configured content overrides the project snapshot.

## Addon configuration

The Python file given to `--addons FILE` must define a callable zero-argument `configure()`. Loading the file executes its top-level Python code; the CLI then calls `configure()` once.

`configure()` must return a dict. All three keys below are optional; an empty dict is equivalent to no configuration:

| Key | Type and purpose |
|---|---|
| `addons` | `dict[str, callable]`; uses the keys as import names and grants Python callables to the entry program |
| `limits` | `SericiteLimits`; the entry program's complete quota configuration |
| `files` | `dict[str, str]`; virtual paths and plain-text contents written to the VFS before running |

Unknown keys, a missing or non-callable `configure()`, a non-dict return, or invalid field types all cause startup to fail. Addon import names are still validated by the language rules; `files` remains subject to the file-count, per-file-size, and total-storage limits.

Scripts use granted functions through `from __addon__ import name`. Every source module that needs an addon must import it itself; see [`__addon__`: the capability entry point](../../scripting/reference/01-language.md#__addon__-the-capability-entry-point).

The startup order is fixed:

```text
Read source and build the project snapshot
→ Run the Python configuration file and configure()
→ Create the entry VM and compile the entry source
→ Write the project files and configured files
→ Run the Sericite program
```

The configuration file can use `__file__` to locate and read its own resources, then put the text into `files`. It is not a Sericite module, and its directory does not need to be a Python package. The CLI provides no additional Sericite module search path.

The configuration file can only prepare the entry program; it cannot take over the REPL loop or control execution step by step. When an existing application needs to manage VM lifecycles, use the Python embedding API rather than extending the CLI configuration.

### Data and trust boundary

> **An addon configuration file has full host privileges. Trust it the same way you trust any Python file you run.**

The configuration file and the Python functions it grants can import third-party libraries, read environment variables and the real disk, and access the network. They run outside the Sericite sandbox, and their CPU, memory, blocking, and external side effects are not constrained by engine quotas. Only the operator should select the configuration file; never let a model or Sericite source decide which one to load.

Arguments and return values between host and script are deep-copied in both directions; only `None`, booleans, numbers, strings, and lists, dicts, and tuples recursively built from these pure data are allowed. An arbitrary Python object does not enter the script merely because an addon returns it.

The engine guarantees that ungranted capabilities are unreachable, but it does not judge for capability implementers whether an operation is safe. Before executing untrusted code, validate arguments and limit resources for your addons yourself; for genuinely adversarial code, you also need independent operating-system-level isolation.

## REPL

With neither `SOURCE_FILE` nor `-c`, the CLI creates a persistent session and enters an interactive loop:

- `>>>` waits for a new entry and `...` waits for a multiline statement to finish; blank input is not executed.
- Variables, functions, schemas, imported modules, and virtual files persist across entries.
- A single expression echoes a non-`None` result with `repr`; other statements show only their own output. `_` holds the most recent expression result.
- A single compile or runtime error is written to stderr and entry continues afterward; the session state already established is not rebuilt because of it.
- A startup failure in the addon configuration or the entry VM still makes the command exit with status code 1.
- EOF ends the REPL normally with exit code 0.

The REPL provides no history, completion, advanced line editing, or debugging commands.

## Input and output

The CLI standard streams inherit the runtime environment's encoding and are not actively reconfigured. In a non-UTF-8 environment such as Windows, set `$env:PYTHONUTF8 = "1"` in the current PowerShell session; the UTF-8 reading rules for source files are unaffected by this setting.

- Script `input()` reads stdin line by line and strips the trailing newline; EOF raises a catchable `input_error`.
- `sericite -` first consumes all of stdin as source and only then starts executing, so `input()` in that source cannot continue reading data from the same stdin.
- REPL commands and script `input()` share stdin. After one command calls `input()`, the next line is first consumed as script data.
- Every entry-program `print()` writes to stdout immediately and flushes, including unterminated output with `end=""`. The CLI keeps no additional program-output buffer.
- Only the entry program's output is connected to the host stdout automatically. Child VM output is obtained or forwarded explicitly by the parent through the VM interface; see the [VM reference](../../scripting/reference/06-vm.md).

A closed downstream stdout pipe means the external consumer has ended: the CLI stops the current execution, discards further output, and exits quietly with 0. This is not a script error, and execution of Sericite `finally` blocks is not guaranteed.

## Error diagnostics

Compile and runtime errors are written to stderr; content already written to stdout before the program failed is not lost. The first line of an error gives the source location, error kind, and message; when a call stack exists, each frame points from the caller to the actual error point and uses the source location that defines that code.

| Source | Name in diagnostics |
|---|---|
| Entry file | The path given on the command line |
| Project-imported module | A virtual path such as `/pkg/mod.sericite` |
| `-c` command string | `<command>` |
| stdin source and REPL input | `<stdin>` |

A syntax error found in the entry file during startup has only a single-line diagnostic and no call stack. Errors in imported modules occur when the import actually executes, may carry a call stack, and can be caught according to the language rules.

In the REPL, each frame maps to the entry that defined its code. When the source cannot be determined, `<sericite>` and `line ?` are shown; code defined in another workspace does not disclose its line and shows `line ?`.

For script exceptions and error kinds, see [errors and exceptions](../../scripting/reference/05-errors.md).

## Exit codes

| Exit code | Meaning |
|---:|---|
| 0 | The program completed normally, the REPL ended with EOF, or the downstream stdout pipe closed |
| 1 | File or addon-configuration loading/validation failed, entry VM startup failed, or one-shot execution failed |
| 2 | Command-line usage error, such as an unrecognized CLI option |

A one-shot program that does not catch `input_error` exits with 1; an ordinary single-entry error in the REPL does not end the session and does not by itself make the whole process exit with 1. Script arguments after the entry do not produce exit code 2 even if they look like CLI options.

Process-level events such as `KeyboardInterrupt` and `SystemExit` are not swallowed as ordinary script or configuration errors.
