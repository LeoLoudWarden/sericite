# Sericite-PY Reference

[中文](sericite-py-reference.zh-CN.md)

This document is for **Python hosts using the `sericite` library**: creating engines and root VMs, configuring quotas, granting FFI capabilities, and handling errors. Sericite-PY is the Python reference implementation of the Sericite language — the language itself does not depend on Python.

## 1. Quick start

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("""
name = input()
print("hello", name)
""")

output = vm.run(["world"])
assert output == "hello world\n"
```

`create_root()` compiles the source and returns a `VMHandle`; a handle can only be driven by the engine that created it.

## 2. Creating an engine and root VM

```python
SericiteEngine(limits=None)
engine.create_vfs() -> VFSHandle
engine.create_root(
    source=None,
    inputs=None,
    input_provider=None,
    limits=None,
    functions=None,
    output_writer=None,
    buffer_output=True,
    argv=None,
    fs=None,
    entry_file=None,
)
```

- `source`: Sericite source text, capped at 4MB in UTF-8. Exactly one of `source` and `entry_file` must be provided.
- `limits`: the root's `SericiteLimits`; see section 3.
- `inputs`: an iterable of strings queued in order.
- `input_provider`: a host callable invoked after the queue is exhausted, returning the next string or `None`. Returning `None`, raising `EOFError`, or raising `StopIteration` moves the VM to `waiting_input`; to report a permanently closed input source, raise `SericiteError(kind="input_error")`, which scripts can catch.
- `functions`: host capabilities granted to the script; see section 5.
- `output_writer`: an optional host callable invoked with each text chunk written to root's virtual stdout, for live forwarding. Output accounting and limits apply first, and child VMs never inherit the callback.
- `buffer_output`: whether root stdout is retained in memory, default `True`. With `False`, buffered output is not retained, which lets a long-running root avoid unbounded historical-output retention; full semantics are in the [VM reference](vm-reference.md) §4.
- `argv`: an iterable of strings used to initialize the root module's `argv` list; the default is an empty list. The engine copies it, so later host-side mutations are not shared. `argv` cannot be used as a grant name. Its semantics are in the [CLI reference](cli-reference.md) §2.
- `fs`: an optional detached `VFSHandle`. `engine.create_vfs()` creates an independent workspace; `create_root(..., fs=fs)` moves ownership only on success, leaving the handle usable on failure. A terminal VM's `take_fs()` returns a new detached handle.
- `entry_file`: reads and compiles an entry file from the `fs` workspace, using its directory as the module resolution root. It requires an explicit `fs` and cannot be combined with `source`. File operations remain rooted at the workspace. See the [VM reference](vm-reference.md) §§2–4 for loading timing and session ownership.

Invalid argument types raise `type_error` at the API boundary. Root arguments are validated before VM creation, so a failure registers no VM; `limits` may be `None` or a `SericiteLimits`, and `fs` must be an unconsumed handle belonging to the same engine.

## 3. Quotas: SericiteLimits

The `SericiteLimits` field list and defaults are in the [VM reference](vm-reference.md) §5; the `VM()` quota keyword arguments inside scripts correspond to them one-to-one. Every field has a default; defaults target development and debugging, not safe execution of untrusted code.

The engine constructor supplies the default quotas. Passing `limits` to `create_root()` replaces the whole configuration for that root rather than merging individual fields.

For a trusted, long-running root, cumulative quotas accept `-1` for no cap (the field list and combining/inheritance rules are in the [VM reference](vm-reference.md) §5); live VM counts and other structural limits must remain finite.

`-1` is an explicit trust decision: use it only for code you control. For what unlimited quotas do and do not mean for resource safety, see the [security model](security.md) §3.

## 4. Driving VMs and managing VFSs

The `VMHandle` driving methods (`run`/`exec`/`step`/snapshots/`take_fs`/`dispose`, …) share their states and contracts with VM values inside scripts; see the [VM reference](vm-reference.md) §§3–4. A host can hold and manage a workspace between execution sessions:

```python
from sericite import SericiteEngine

engine = SericiteEngine()
fs = engine.create_vfs()
fs.write_file("/input.txt", "hello")
vm = engine.create_root(
    "write_file('/output.txt', read_file('/input.txt') + '!')",
    fs=fs,
)
vm.run()
fs = vm.take_fs()
assert fs.read_file("/output.txt") == "hello!"
vm.dispose()
```

Host `VMHandle` file methods operate on the currently attached VFS, while the same `VFSHandle` methods operate on a detached workspace. Both are trusted host-management channels, not script-side VM file proxies; scripts operate only on the current session's VFS or a detached handle. See the [language reference](language-reference.md) §6 for path, directory, and public error semantics.

A host-side snapshot is a strict superset of the script-safe view, adding:

| Field | Meaning |
|---|---|
| `vm_id` | Engine-local identifier; never reused |
| `parent_id` | Engine-local identifier of the parent VM; `None` for a root |
| `depth` | Nesting depth; a root is 0 |
| `child_count` | Cumulative direct children created; disposing a child does not decrease it |

Script calls receive only the safe view and cannot see these host fields.

The host side also has one privilege — host management is not script accounting:

- Direct `feed_input()`, file operations through `VMHandle`/`VFSHandle`, stdout access, snapshots, and `dispose()` do not enter the script's memory ledger;
- Resource-specific limits such as file count, per-file bytes, total file storage, and output bytes still apply;
- Instructions and dynamic operations executed by `run()`, `exec()`, `step()`, and `step_instruction()` always remain subject to VM quotas.

This does **not** mean host calls make VM execution free. It means: **management actions are not script-caused work, while actual VM execution is still metered.** See the [architecture notes](architecture.md) §5 for the script accounting model.

## 5. FFI: granting host capabilities

### 5.1 Granting functions

```python
def double(value):
    return value * 2

engine = SericiteEngine()
vm = engine.create_root(
    "print(double(21))",
    functions={"double": double},
)
assert vm.run() == "42\n"
```

A granted name must be a valid identifier, must not start with `__`, and must not conflict with a builtin. Values must be callable. The whole table is validated when the root is created.

### 5.2 Data boundary

Arguments and results are deep-copied in both directions and restricted to recursive pure data:

- `None`, `bool`, `int`, `float`, and `str`;
- `list`, `dict`, and `tuple`; list/tuple types are preserved in both directions;
- Dict keys obey the same type whitelist.

Records/schemas, module objects, VM/VFS handles, functions, and other host objects cannot cross; attempting to do so raises `ffi_error`. Call `unwrap()` in the script to turn a record into a dict first. Container sizes, strings, integer width, total nodes, and nesting depth are bounded, and the copying work itself is charged per node against engine quotas.

### 5.3 Exceptions and reentrancy

- The FFI exception contract: a well-behaved host callback either returns a result or raises `SericiteError` with a contract kind (`file_not_found`, `runtime_error`, …) — this says "I'm alive, and this job cannot be delivered." A `SericiteError` propagates under its original kind, with catchability governed by the language rules; ordinary catchable kinds can be handled by the script, so the host must keep secrets out of the message.
- `resource_exhausted` is special: if a host callback raises it, the engine treats it as the VM's own quota exhaustion — the VM enters the terminal `resource_exhausted` state, and the script cannot catch it. If the script should be able to recover from such a failure, raise an ordinary contract kind such as `runtime_error` or `ffi_error` inside the callback instead.
- Any **other** `Exception` escaping a host callback is a governance failure: the callback's internal state is no longer trustworthy. The engine kills the VM with the **uncatchable** `host_error` — message: only the host exception's type name, never its text — and returns control to the host.
- Scripts cannot catch this failure — not even with a bare `except:` — and cannot probe host exception types through it. Catch your own exceptions inside the callback and translate the ones scripts may see into contract kinds.
- `SystemExit`, `KeyboardInterrupt`, and other `BaseException`s are process-level events addressed to the host: they propagate out of `run()` unchanged. Do not grant functions whose libraries can call `sys.exit()` on adversarial input paths — same discipline as not granting functions that can be driven to delete files.
- Do not call `run()`, `step()`, or another driving method on the same VM from inside its callback; nested dispatch is rejected.

### 5.4 Cost responsibility

**CPU, memory, blocking, and external side effects inside a host callback are not metered by the engine.** Only dispatch and engine-side boundary conversion are charged.

FFI is therefore an explicit trust commitment. Validate arguments and bound input sizes, call rates, and external resources in the capability itself. Do not grant unnecessary access to networks, files, or secrets.

## 6. Host-side error handling

```python
from sericite import SericiteError

try:
    vm.run()
except SericiteError as exc:
    print(exc.kind, exc.message, exc.filename, exc.line, exc.column)
    for frame in exc.frames:
        print(frame.function, frame.line)
```

`exc.frames` is the call stack of the VM where the error originated (the first VM that captured a trace), typed as `tuple[SericiteFrame, ...]`; ordering and redaction follow the script error record — see the [language reference](language-reference.md) §5.

Each frame is a `SericiteFrame` — a top-level host API imported from `sericite` like `SericiteError`:

- `function`: `str`, the function name;
- `line`: `int | None`, the line number; `None` for a frame from another VM (redacted).

A VM snapshot's `error.frames` instead describes the VM that owns that snapshot, but it has a different shape: a list of dicts (`{"function": str, "line": int | None}`), not `SericiteFrame` objects. Errors rejected before VM execution begins have no frames.

The script-side catchability of `resource_exhausted` (catchable only from code isolated behind `VM()`) and the `kind` registry are in the [language reference](language-reference.md) §5. File-operation constraint rejection instead uses the ordinary catchable `file_limit_error`; `internal_error` and `host_error` are always uncatchable by scripts. Hosts can and should handle `resource_exhausted`, `internal_error`, and `host_error`.

## 7. Host checklist for untrusted code

- Tighten quotas explicitly at every VM layer instead of relying on defaults.
- Add process, container, or another OS-level boundary in production; do not treat the in-process Python engine as the only isolation boundary.
- Grant only necessary FFI and enforce argument, rate, and external-resource limits inside each capability.
- Use the public `VMHandle`/`VFSHandle` APIs for host management; never expose internal contexts or private implementation objects to untrusted Python.
- Snapshots and errors may be forwarded to higher layers, but do not put host secrets into `SericiteError` messages.
