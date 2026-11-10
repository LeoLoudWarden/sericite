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
- `functions`: host capabilities granted to the script; see section 6.
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

The `VMHandle` driving methods (`run`/`exec`/`step`/snapshots/`take_fs`/`dispose`, …) share their states and contracts with VM values inside scripts; see the [VM reference](vm-reference.md) §§3–4. A host can also set a breakpoint and resume directly:

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("x = 1\nx += 1\nprint(x)")
vm.add_breakpoint(2)
vm.run()
assert vm.snapshot()["state"] == "paused"
assert vm.snapshot()["locals"]["x"] == 1
assert vm.run() == "2\n"
```

A host can hold and manage a workspace between execution sessions:

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

- Direct `feed_input()`, breakpoint management, file operations through `VMHandle`/`VFSHandle`, stdout access, snapshots, and `dispose()` do not enter script accounting;
- Resource-specific limits such as file count, per-file bytes, total file storage, output bytes, and `max_breakpoints` still apply;
- Instructions and dynamic operations executed by `run()`, `exec()`, `step()`, and `step_instruction()` always remain subject to VM quotas.

This does **not** mean host calls make VM execution free. It means: **management actions are not script-caused work, while actual VM execution is still metered.** See the [architecture notes](architecture.md) §5 for the script accounting model.

## 5. Observing VM activity

A Python host can observe every VM in an engine, including descendants created inside scripts, without granting a script any new capability. Observation is host-only: no Sericite builtin or VM-handle method exposes these events to scripts.

### 5.1 Subscribing and event shape

```python
from sericite import SericiteEngine

engine = SericiteEngine()
events = []
with engine.observe(events.append) as observation:
    root = engine.create_root("print('hello')")
    root.run()
    snapshot = observation.snapshot(events[0].vm_id)

assert [event.kind for event in events] == [
    "vm.created",
    "vm.output",
    "vm.state_changed",
]
assert snapshot["stdout"] == "hello\n"
```

`engine.observe(sink)` registers a callable and returns a `SericiteObservation`. A non-callable sink raises `type_error`. The observation is a context manager; leaving the `with` block closes it. It receives only events produced after registration, not a replay of existing VMs or old events.

Each sink call receives a `SericiteEvent`, also exported from the top-level `sericite` package:

| Field | Meaning |
|---|---|
| `sequence` | Monotonically increasing event sequence within this engine |
| `kind` | One of the event kinds below |
| `vm_id` | Engine-local ID of the VM that produced the event |
| `parent_id` | Engine-local parent ID, or `None` for a root |
| `depth` | VM nesting depth; a root is 0 |
| `data` | Event-specific host-side values described below |

### 5.2 Event kinds and committed state

| Kind | `data` and timing |
|---|---|
| `vm.created` | `state`, `filename`, `limits`, and `functions`. `limits` is the VM's `SericiteLimits`; `functions` is a sorted tuple of granted names. Emitted only after creation, registration, parent/ancestor counts, and VFS attachment have all committed. Failed creation emits no event. |
| `vm.state_changed` | `old_state`, `new_state`, and `reason`. A breakpoint pause also carries `breakpoint={"line": int, "path": str | None}`; a terminal error carries `error_kind`. Emitted after the new state and its debugging scene have committed, and only when the state actually changes. |
| `vm.output` | `text`, one committed virtual-stdout chunk. Emitted after output accounting and stdout buffering, but before output forwarding and script output writers. Output rejected by the output limit emits no event. |
| `vm.disposed` | `reason` and `state`. Explicit disposal uses `reason="dispose"` and `state="terminated"`; automatic collection uses `reason="gc"` and preserves the state before collection. |

Observable state-change reasons are `exec`, `resume`, `breakpoint`, `input`, `output_writer`, `return`, `error`, `terminate`, and `dispose`. Caught script errors do not by themselves produce a terminal state change. Repeated disposal of an already disposed VM produces no additional event.

Output events belong to the VM whose virtual stdout actually committed the text. If a child forwards output through its parent, each real VM write produces its own event. With `buffer_output=False`, `data["text"]` still reports the committed output even though buffered views such as snapshot `stdout` remain empty. A later output-writer failure does not retract an already emitted output event.

### 5.3 Delivery, failure, and reentrancy

Ordinary events are delivered synchronously as execution commits them. Observation does not execute script code and does not change VM instruction or memory accounts. Every open observation registered before an event receives the same fact, but each receives an independent event object and deep copy of nested `data`; mutating one delivery does not affect another observer or the engine.

`close()` is idempotent and immediately stops later deliveries, including deliveries still waiting in the current dispatch. The `closed` property reports closure. Closing one observation does not close others.

If a sink raises an ordinary `Exception`, the engine closes only that observation and continues the VM and other observers. `failed` then reports `True`, and `failure` contains the host-side string `"ExceptionType: message"`; if rendering the exception itself fails, it contains only the exception class name. These failures do not follow the FFI `host_error` contract. `KeyboardInterrupt`, `SystemExit`, and other `BaseException`s remain process-level events and propagate to the host.

An observation callback must not reenter operations on the same engine. Creating VMs or VFSs, driving or disposing VMs, VFS operations, registering another observation, and `poll()` all raise `runtime_error` when attempted from its callback. The permitted operations are closing observations and read-only `observation.snapshot(vm_id)`. Operations on a different engine are not governed by this restriction.

### 5.4 Garbage collection and read-only snapshots

Automatic collection needs special delivery treatment: a Python finalizer unregisters the VM and queues a pure-data tombstone, but never invokes an observation sink. Queued `vm.disposed(reason="gc")` events are delivered by `observation.poll()` or a later safe engine entry that flushes observation events. Their sequence relative to later events is preserved. Call `poll()` when the host wants explicit delivery rather than relying on another engine operation.

A closed observation receives no further tombstones. An observation registered after a tombstone was queued does not receive that old event. Explicit disposal does not also queue a GC event. Pending tombstones and observation-callback work are host-side costs, not script-metered execution.

`observation.snapshot(vm_id)` returns the same host-side snapshot shape as `VMHandle.snapshot()` in section 4, for any live VM in the same engine. It works for descendants not directly held by the host and inside an observation callback, where it reflects the committed scene associated with the event. It returns safe values only: no operable VM handle, no internal context, and no cached reference that keeps the VM alive. Mutating the returned dictionary does not modify the VM.

`vm_id` must be a non-negative `int` (`bool` is rejected); invalid types raise `type_error`. An unknown or already disposed ID raises `runtime_error`, as does calling `snapshot()` on a closed observation. In particular, a `vm.disposed` notification arrives after unregistration, so its target is no longer available for snapshots.

## 6. FFI: granting host capabilities

### 6.1 Granting functions

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

### 6.2 Data boundary

Arguments and results are deep-copied in both directions and restricted to recursive pure data:

- `None`, `bool`, `int`, `float`, and `str`;
- `list`, `dict`, and `tuple`; list/tuple types are preserved in both directions;
- Dict keys obey the same type whitelist.

Records/schemas, module objects, VM/VFS handles, functions, and other host objects cannot cross; attempting to do so raises `ffi_error`. Call `unwrap()` in the script to turn a record into a dict first. Container sizes, strings, integer width, total nodes, and nesting depth are bounded, and the copying work itself is charged per node against engine quotas.

### 6.3 Exceptions and reentrancy

- The FFI exception contract: a well-behaved host callback either returns a result or raises `SericiteError` with a contract kind (`file_not_found`, `runtime_error`, …) — this says "I'm alive, and this job cannot be delivered." A `SericiteError` propagates under its original kind, with catchability governed by the language rules; ordinary catchable kinds can be handled by the script, so the host must keep secrets out of the message.
- `resource_exhausted` is special: if a host callback raises it, the engine treats it as the VM's own quota exhaustion — the VM enters the terminal `resource_exhausted` state, and the script cannot catch it. If the script should be able to recover from such a failure, raise an ordinary contract kind such as `runtime_error` or `ffi_error` inside the callback instead.
- Any **other** `Exception` escaping a host callback is a governance failure: the callback's internal state is no longer trustworthy. The engine kills the VM with the **uncatchable** `host_error` — message: only the host exception's type name, never its text — and returns control to the host.
- Scripts cannot catch this failure — not even with a bare `except:` — and cannot probe host exception types through it. Catch your own exceptions inside the callback and translate the ones scripts may see into contract kinds.
- `SystemExit`, `KeyboardInterrupt`, and other `BaseException`s are process-level events addressed to the host: they propagate out of `run()` unchanged. Do not grant functions whose libraries can call `sys.exit()` on adversarial input paths — same discipline as not granting functions that can be driven to delete files.
- Do not call `run()`, `step()`, or another driving method on the same VM from inside its callback; nested dispatch is rejected.

### 6.4 Cost responsibility

**CPU, memory, blocking, and external side effects inside a host callback are not metered by the engine.** Only dispatch and engine-side boundary conversion are charged.

FFI is therefore an explicit trust commitment. Validate arguments and bound input sizes, call rates, and external resources in the capability itself. Do not grant unnecessary access to networks, files, or secrets.

## 7. Host-side error handling

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

## 8. Host checklist for untrusted code

- Tighten quotas explicitly at every VM layer instead of relying on defaults.
- Add process, container, or another OS-level boundary in production; do not treat the in-process Python engine as the only isolation boundary.
- Grant only necessary FFI and enforce argument, rate, and external-resource limits inside each capability.
- Use the public `VMHandle`/`VFSHandle` APIs for host management; never expose internal contexts or private implementation objects to untrusted Python.
- Keep observation sinks bounded and nonblocking, close them when finished, and poll for delayed GC notifications when needed.
- Snapshots and errors may be forwarded to higher layers, but do not put host secrets into `SericiteError` messages.
