# Sericite-PY Host Reference

[中文](host-reference.zh-CN.md)

This document is for **Python hosts using Sericite-PY**: creating and driving VMs, configuring quotas, granting FFI capabilities, accessing virtual files, debugging, and handling errors. If you are writing **Sericite scripts**, read the [language reference](language-reference.md). To run scripts directly or let a root Sericite program own the application flow, read the [CLI reference](cli-reference.md) instead of writing a Python launcher. Internal cost contracts are covered by the [architecture notes](architecture.md).

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

`create_root()` compiles the source and returns a `VMHandle`; a handle can only be driven by the engine that created it. A VM is an isolated workspace — the isolation promises are in the [security model](security.md) §2.

## 2. Engines and quotas

### 2.1 Creating an engine and root VM

```python
SericiteEngine(limits=None)
engine.create_root(
    source,
    inputs=None,
    input_provider=None,
    limits=None,
    functions=None,
    output_writer=None,
)
```

- `source`: Sericite source text, capped at 4MB in UTF-8.
- `limits`: the root's `SericiteLimits`. The engine constructor supplies the default; passing it again to `create_root()` replaces the whole configuration for that root rather than merging individual fields.
- `inputs`: an iterable of strings queued in order.
- `input_provider`: a host callable invoked after the queue is exhausted, returning the next string or `None`. Returning `None`, raising `EOFError`, or raising `StopIteration` moves the VM to `waiting_input`.
- `functions`: host capabilities granted to the script; see section 5.
- `output_writer`: an optional host callable invoked with each text chunk written to root's virtual stdout, for live forwarding. Buffered stdout and `run()`'s return value are unchanged; output accounting and limits still apply first, and child VMs never inherit the callback.

### 2.2 `SericiteLimits`

Every field has a default. Defaults target development and debugging, not safe execution of untrusted code.

| Field | Default | Meaning |
|---|---:|---|
| `max_instructions` | 1,000,000 | Instruction and discounted-work limit |
| `max_output_bytes` | 1,048,576 | stdout bytes in UTF-8 |
| `max_frames` | 100 | Call-frame limit |
| `max_child_vms` | 100 | Direct children per VM |
| `max_list_size` | 100,000 | Slots per list |
| `max_dict_size` | 100,000 | Entries per dict |
| `max_string_bytes` | 1,048,576 | Size per string |
| `max_int_bits` | 4096 | Integer bit width |
| `max_total_bytes` | 67,108,864 | Approximate memory high-water mark |
| `max_total_vms` | 1000 | Cumulative VMs per engine, including terminal VMs |
| `max_vm_depth` | 8 | VM nesting depth |
| `max_fs_files` | 1000 | Files per VM |
| `max_fs_file_bytes` | 1,048,576 | UTF-8 bytes per file |

Child VMs created by scripts can only tighten these limits. Instruction, memory, and child-VM consumption is charged to relevant ancestors through causal routes.

## 3. Driving a VM: `VMHandle`

### 3.1 Methods

| Method | Purpose and result |
|---|---|
| `run(inputs=None) -> str` | Drive to completion, suspension, or failure and return stdout; `inputs` must be a string list/tuple and is validated as a batch before queueing |
| `exec(source) -> str` | Deliver new source into this VM and run it in the persistent module scope; returns only this delivery's output; see section 4 |
| `feed_input(value)` | Queue one input string; resumes a VM waiting for input |
| `step() -> dict` | Execute one statement and return a snapshot |
| `step_instruction() -> dict` | Execute one internal instruction and return a snapshot |
| `snapshot() -> dict` | Return a safe snapshot without advancing execution |
| `stdout() -> str` | Return current stdout |
| `terminate()` | Mark a `ready` or `waiting_input` VM as `terminated` |
| `read_file(path) -> str` | Read a text file from this VM |
| `write_file(path, text)` | Write a text file into this VM |
| `list_dir(path) -> list[str]` | Return sorted direct children of a directory |
| `path_exists(path) -> bool` | Check whether a file or directory exists |

If execution fails, `run()` raises `SericiteError` to the host. Running out of queued input is ordinary suspension, not an exception.

### 3.2 Host management is not script accounting

The host is a trusted manager:

- Direct `feed_input()`, `write_file()`, file reads, stdout access, and snapshots do not enter the script's memory ledger;
- Resource-specific limits such as file count, file bytes, and output bytes still apply;
- Instructions and dynamic operations executed by `run()`, `exec()`, `step()`, and `step_instruction()` always remain subject to VM quotas.

This does **not** mean host calls make VM execution free. It means: **management actions are not script-caused work, while actual VM execution is still metered.**

## 4. States, snapshots, and lifecycle

VM states are `ready`, `waiting_input`, `done`, `error`, `resource_exhausted`, and `terminated`.

A snapshot contains:

| Field | Meaning |
|---|---|
| `vm_id` | Engine-local identifier |
| `state` | Current state |
| `last_line` / `next_line` | Previous and next logical source lines |
| `locals` | Safe copies of user-visible local values |
| `stdout` | Current output |
| `error` | `kind`, `message`, `line`, and `column`, or `None` |
| `instruction_count` | Current instruction/work ledger |

Complex values have node and depth budgets. Cycles and shared structures use placeholders rather than exponential expansion. Snapshots do not expose live child handles or host objects.

`exec(source)` gives a VM a new program while keeping its world: the fresh module frame reuses the previous module scope, so module-level names (variables, functions, schemas) persist, and the VFS, input queue, and granted functions are untouched. Delivery is accepted from any state except `terminated` (and never while running); a program that has not finished — never started, or suspended on input — is discarded, a previous error is cleared, and old debugging frames are replaced, so call `snapshot()` first if you need them. Compilation completes before any state changes, so source that fails to compile leaves the VM exactly as it was. Quotas are lifetime budgets: instruction, memory, and output consumption accumulate across deliveries, not per delivery.

Terminal VM contexts remain available for debugging. The engine owns all contexts, and `max_total_vms` caps their cumulative number. Release the whole engine when its VM tree is no longer needed.

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
- `list` and `dict`; a host-returned tuple becomes a list;
- Dict keys obey the same type whitelist.

Records/schemas, VM handles, functions, and other host objects cannot cross. Call `unwrap()` in the script to turn a record into a dict first. Container sizes, strings, integer width, total nodes, and nesting depth are bounded, and the copying work itself is charged per node against engine quotas.

### 5.3 Exceptions and reentrancy

- The FFI exception contract: a well-behaved host callback either returns a result or raises `SericiteError` with a contract kind (`file_not_found`, `runtime_error`, …) — this says "I'm alive, and this job cannot be delivered." A `SericiteError` propagates unchanged and is catchable by the script under its kind, so the host must keep secrets out of its message.
- Any **other** `Exception` escaping a host callback is a governance failure: the callback's internal state is no longer trustworthy. The engine kills the VM with the **uncatchable** `host_error` — message: only the host exception's type name, never its text — and returns control to the host.
- Scripts cannot catch this failure — not even with a bare `except:` — and cannot probe host exception types through it. Catch your own exceptions inside the callback and translate the ones scripts may see into contract kinds.
- `SystemExit`, `KeyboardInterrupt`, and other `BaseException`s are process-level events addressed to the host: they propagate out of `run()` unchanged. Do not grant functions whose libraries can call `sys.exit()` on adversarial input paths — same discipline as not granting functions that can be driven to delete files.
- Do not call `run()`, `step()`, or another driving method on the same VM from inside its callback; nested dispatch is rejected.

### 5.4 Cost responsibility

**CPU, memory, blocking, and external side effects inside a host callback are not metered by the engine.** Only dispatch and engine-side boundary conversion are charged.

FFI is therefore an explicit trust commitment. Validate arguments and bound input sizes, call rates, and external resources in the capability itself. Do not grant unnecessary access to networks, files, or secrets.

## 6. Nested VMs and grant semantics

Scripts create child VMs with `VM(code, **limits)` and can grant Sericite functions or existing granted functions to the next layer with `functions={"name": fn}`.

- A granted function retains its definition-side module variables, closures, and grant environment;
- World services such as printing, VFS, and child creation still resolve to the defining world (home);
- The function body executes on the caller's frame stack;
- World services and target execution are jointly constrained by causal routes spanning home/target and caller, with shared ancestors charged once;
- Result ownership enters the actual caller.

Granting or re-granting a function grants the world reachable through it. VM handles themselves cannot cross FFI into the host. The mechanism and its design invariants are in the [architecture notes](architecture.md), invariant 13 and section 5.4.

## 7. Host-side error handling

```python
from sericite import SericiteError

try:
    vm.run()
except SericiteError as exc:
    print(exc.kind, exc.message, exc.filename, exc.line, exc.column)
```

`resource_exhausted`, `internal_error`, and `host_error` are uncatchable only by **Sericite scripts**; hosts can and should handle them. See the [language reference](language-reference.md) for the registry of syntax, validation, runtime, and FFI error kinds.

## 8. Host checklist for untrusted code

- Tighten quotas explicitly at every VM layer instead of relying on defaults.
- Add process, container, or another OS-level boundary in production; do not treat the in-process Python engine as the only isolation boundary.
- Grant only necessary FFI and enforce argument, rate, and external-resource limits inside each capability.
- Use the public `VMHandle` API for host management; never expose internal contexts or private implementation objects to untrusted Python.
- Snapshots and errors may be forwarded to higher layers, but do not put host secrets into `SericiteError` messages.
