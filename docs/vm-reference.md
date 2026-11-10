# Sericite VM Reference

[中文](vm-reference.zh-CN.md)

This document is for **readers who need to create and drive child VMs inside Sericite scripts**. It covers the script-visible contracts for execution sessions, VFS transfer, VM states, driving methods, exec delivery, quotas, and function granting. For the Python host API, see the [Sericite-PY reference](sericite-py-reference.md).

## 1. What a VM is

A VM is a mutually isolated execution session: it cannot see its parent's variables, files, or handles, and cannot tell how deeply it is nested. Every session has its own module scope and cache, input queue, stdout, and cumulative execution ledger. Its attached VFS is an exclusively owned file world. The isolation promises are in the [security model](security.md) §2.

A VM is not single-use: the same session can be fed input, single-stepped by statement or instruction, snapshotted, receive new source through `exec()`, or be terminated. `run()`, `step()`, and repeated `exec()` do not start another session; create another VM when fresh variables, module caches, and execution ledgers are required.

## 2. Creating VMs and transferring VFSs

Inside a script, create a child VM with `VM(source=code, **options)` or `VM(entry_file=path, **options)`; the positional form `VM(code, ...)` is shorthand for `source=code`. Exactly one source kind must be selected:

```python
sub = VM(source=code, max_instructions=10000)  # quotas can only be tightened
sub = VM(code, output_writer=forward, buffer_output=False)
sub = VM(code, fs=workspace)                   # move in a detached VFS
sub = VM(entry_file="/project/main.sericite", fs=workspace)
```

A new VM has a blank VFS by default. `fs` accepts only a detached handle returned by `VFS()` or a terminal VM's `take_fs()`; successful attachment permanently consumes the old handle, and the new VM exclusively owns the VFS.

`source` executes string code with modules resolved from the workspace root. `entry_file` requires an explicit `fs`, reads and compiles that file during creation, and uses its directory as the module resolution root. A missing entry or a read/compile failure does not consume the VFS. The module root belongs to the session, persists across later `exec()` deliveries, and is neither carried by a transferred VFS nor implicitly inherited by child VMs. It affects only imports; file operations such as `read_file()` remain rooted at the whole workspace. See the [language reference](language-reference.md) §9 for path rules.

`output_writer` and `buffer_output` configure this VM's output; `functions` grants functions (section 6); the remaining options are quota fields. See section 4 for output forwarding and section 5 for quotas.

## 3. States and lifecycle

VM states are `ready`, `waiting_input`, `paused`, `done`, `error`, `resource_exhausted`, and `terminated`. `paused` is a recoverable, nonterminal state entered before a statement hits a breakpoint.

`terminate()` marks a `ready`, `waiting_input`, or `paused` VM as `terminated`; in any other state it is a silent no-op. Terminal VMs such as `done`/`error` can continue to accept `exec` deliveries while their VFS remains attached.

A VM holds resources that require release. It remains alive while it is reachable from a VM value or a granted function's environment, so terminal VMs remain available for debug snapshots and, while their VFS remains attached, further `exec` deliveries.

Once a VM becomes wholly unreachable, garbage collection eventually destroys it, including when self-references or cross-VM cycles are present. Automatic collection is not guaranteed at a particular statement or scope boundary; call `dispose()` when deterministic release is required.

`dispose()` accepts a VM in any state, including running or waiting for input. It terminates and unregisters the target and all live descendants, with no child-first requirement. It:

- immediately releases the `max_total_vms` slots held by the target and all its live descendants;
- stops a running target after the current instruction exits safely, without executing the target script's `finally` blocks;
- is idempotent — repeated disposal is a no-op;
- invalidates the VM value — any other method on a disposed VM fails with `runtime_error`.

`take_fs()` is available only in the `done`, `error`, `resource_exhausted`, or `terminated` terminal states. It atomically removes the VFS and returns a new detached handle. A running or `waiting_input` VM cannot surrender its VFS directly; terminate an abandoned input wait first. After removal, the old VM still supports snapshots, stdout, and disposal, but loses file access and accepts no further `exec()`. Old home functions and old VFS handles cannot reach the transferred world. If removal fails, the VFS remains with the original VM. Disposing of that VM does not affect an already detached VFS.

After the VM that owns a function's definition is destroyed, functions passed from it to other VMs become invalid too; calling one fails with a catchable `runtime_error`. See section 6 for granting semantics.

If resources are insufficient, `dispose()` fails before destroying anything. Disposal does not refund the parent's cumulative instruction or memory usage. Internal lifecycle and charging rules are in the [architecture notes](architecture.md) §5.4.

## 4. Driving methods

| Method | Purpose and result |
|---|---|
| `run(inputs=None) -> str` | Drive to completion, suspension, or failure and return stdout; `inputs` must be a string list/tuple and is validated as a batch before queueing |
| `exec(source) -> str` | Deliver new source into this VM and run it in the persistent module scope; returns only this delivery's output; see below |
| `feed_input(value)` | Queue one input string; resumes a VM waiting for input |
| `step() -> dict` | Execute one statement and return a snapshot |
| `step_instruction() -> dict` | Execute one internal instruction and return a snapshot |
| `snapshot() -> dict` | Return a safe snapshot without advancing execution |
| `add_breakpoint(line, path=None)` | Add a statement-entry line breakpoint; duplicate addition is a no-op |
| `remove_breakpoint(line, path=None)` | Remove a location; absence is a no-op |
| `breakpoints() -> list` | Return pure-data locations in insertion order |
| `stdout() -> str` | Return current stdout |
| `terminate()` | Terminate the VM; effective states and no-op semantics are in section 3 |
| `dispose()` | Forcibly destroy a VM in any state and all live descendants; see section 3 |
| `take_fs() -> VFS` | Atomically remove the VFS from a terminal VM and return a new detached handle; see section 3 |

VM values no longer provide script-side file proxies. File builtins always operate on the current session's exclusively owned VFS; the same methods on a detached handle operate on that detached workspace. See the [language reference](language-reference.md) §6 for paths, errors, and directory behavior.

```python
fs = VFS()
fs.write_file("/input.txt", "data")      # configure the detached workspace first
sub = VM(code, fs=fs, max_instructions=10000)
sub.feed_input("one line")               # feed input()
out = sub.run()
fs = sub.take_fs()
print(fs.read_file("/result.txt"))       # retrieve results after termination
```

The recommended workflow is: configure a detached VFS, move it into the VM, then take it back for result inspection after the session reaches a terminal state.

Running out of queued input with no further source is ordinary suspension (`waiting_input`), not an exception; an input source explicitly reporting closure (`input_error`) follows the normal catchable-error path. On failure, `sub.run()` propagates the child VM's error to the calling script under its original kind, and catchable kinds can still be caught.

After a child exhausts an execution budget and enters the terminal `resource_exhausted` state, a parent can catch that error; the parent's own or an ancestor's execution-budget errors remain uncatchable. File-operation constraints use a separate, recoverable error contract described in section 5 below.

A terminal VM can still be operated on, but two kinds of methods behave differently:

- methods that do not drive the VM (`snapshot`, `step`, `step_instruction`, `stdout`, `take_fs`, …) remain available; on a terminal VM, `step`/`step_instruction` only return a snapshot, and `take_fs` is charged only to the caller;
- driving methods (`feed_input`, `run` with inputs, `exec`, …) may fail because the VM's quota is exhausted.

The charging model — which operations are charged to whom — is in the [architecture](architecture.md) §5.4.

### Output forwarding and buffering

Every VM has independent `output_writer` and `buffer_output` settings. A child writer is explicitly configured by its parent and is never inherited implicitly:

```python
def forward(text):
    print(text, end="")

sub = VM('print("live")', output_writer=forward)
```

The writer:

- receives one string for each `print()` chunk, after output processing and buffering;
- follows granted-function semantics: it retains the definition side's module variables, closures, granted functions, and IO, and is constrained by both definition-side and caller resource limits;
- forwards through the parent's configured output chain when it calls the parent's `print()`;
- ignores its return value; errors propagate at the triggering `print()` under the usual rules;
- must finish synchronously — attempting to suspend it on `input()` raises `runtime_error` at that `print()`.

`buffer_output=True` is the default and preserves complete stdout for `run()`/`exec()`/`stdout()` and snapshots. With `buffer_output=False`, output is still forwarded but not retained: those buffered-output views are empty. Output and writer settings persist across `exec` deliveries.

### exec: delivering new source into an existing VM

`exec(source)` gives a VM a new program while keeping its world:

- **The retained world**: the fresh module frame reuses the previous module scope, so module-level names (variables, functions, schemas) persist; the filesystem, module resolution root, input queue, granted functions, and imported-module cache are untouched.
- **States and discarding**: delivery is accepted from any state except `terminated`, after VFS removal through `take_fs()`, or while the VM is being driven (`run()`/`exec()`/`step()` in progress). An unfinished program — never started, waiting for input, or paused at a breakpoint — is discarded, a previous error is cleared, and old debugging frames are replaced, so call `snapshot()` first if you need them. Breakpoint configuration persists, and main-source locations bind to the new delivery as described below.
- **Compilation atomicity**: compilation completes before any state changes; source that fails to compile leaves the VM exactly as it was, including its paused scene and breakpoint binding.
- **Lifetime quotas**: instruction, memory, and output consumption accumulate across deliveries, not per delivery.

### Breakpoints

The direct controller holding a VM handle can set statement-entry line breakpoints on its target:

```python
sub = VM("x = 1\nx += 1\nprint(x)")
sub.add_breakpoint(2)                    # current main source
sub.add_breakpoint(5, "/util.sericite")  # a logical file owned by the target
sub.run()                                # returns before line 2 executes
snapshot = sub.snapshot()                # state == "paused"
sub.run()                                # executes line 2 and continues
```

`line` must be a positive integer; `path` is `None` or a logical path normalized under VFS rules. Addition and removal are idempotent. `breakpoints()` returns pure-data `{"line": int, "path": str | None}` entries in insertion order. Breakpoints can be managed in running, waiting, paused, and terminal states as long as the VM has not been disposed; `max_breakpoints` bounds their count.

Breakpoint semantics are:

- The VM enters `paused` before the statement's first instruction, preserving its PC, frames, locals, and stdout. `run()` returns current stdout normally; no exception or `except/finally` runs, and the unexecuted instruction is not charged.
- Calling `run()`, `step()`, or `step_instruction()` from `paused` resumes with a one-time exemption for the current breakpoint. A later loop iteration hits it again. Statement stepping keeps its existing boundary, but another breakpoint inside a call can interrupt it.
- `path=None` matches the current main source and its functions. After successful `exec()`, it binds by line to the new main source and does not hit functions left by older deliveries.
- An explicit `path` matches the target VM's own entry file and imported modules. Granted code defined by another VM never hits the target's breakpoints, even at the same path and line.
- Only actual statement entries are breakable: blank lines, comments, non-start lines of multiline statements, and `pass` (which emits no instruction) do not hit. Multiple instruction-producing statements on one line hit separately.
- Pausing does not propagate through the creation chain. When the child's `run()` returns, its direct parent may inspect and resume it or continue its own program; ancestors and the host enter no global pause.
- Adding a new location beyond `max_breakpoints` raises the ordinary catchable `breakpoint_limit_error` without modifying the table or terminating caller or target. The controller may remove an old location and retry; actual caller instruction or memory exhaustion remains `resource_exhausted`.

### Snapshots

A snapshot returned by `step()`, `step_instruction()`, or `snapshot()` contains the script-safe view:

| Field | Meaning |
|---|---|
| `state` | Current state |
| `last_line` / `next_line` | Previous and next logical source lines |
| `locals` | Safe copies of user-visible local values |
| `stdout` | Current output |
| `error` | `kind`, `message`, `line`, `column`, and `frames`, or `None` |
| `breakpoint` | The actual `line`/`path` hit at a breakpoint pause, otherwise `None` |
| `instruction_count` | Current instruction/work ledger |

Complex values have node and depth budgets. Cycles and shared structures use placeholders rather than exponential expansion. Snapshots do not expose operable child VM values.

`error.frames` is that VM's call stack. Each entry is `{"function": str, "line": int | None}`; ordering and line redaction follow the script error record — see the [language reference](language-reference.md) §5.

## 5. Quotas

Each VM's resource quotas are defined by the following fields. Every field has a default; defaults target development and debugging, not safe execution of untrusted code.

| Field | Default | Meaning |
|---|---:|---|
| `max_instructions` | 1,000,000 | Instruction and discounted-work limit |
| `max_output_bytes` | 1,048,576 | stdout bytes in UTF-8 |
| `max_frames` | 100 | Call-frame limit |
| `max_list_size` | 100,000 | Slots per list/tuple |
| `max_dict_size` | 100,000 | Entries per dict |
| `max_string_bytes` | 1,048,576 | Size per string |
| `max_int_bits` | 4096 | Integer bit width |
| `max_total_bytes` | 67,108,864 | Approximate memory high-water mark |
| `max_total_vms` | 1000 | Live, not-yet-disposed VMs across the runtime, including the entry VM; disposal releases a slot |
| `max_descendant_vms` | 1000 | Live descendants throughout a VM's whole subtree, excluding itself; disposal releases a slot |
| `max_vm_depth` | 8 | VM nesting depth |
| `max_breakpoints` | 100 | Breakpoint locations retained by the current VM |
| `max_fs_files` | 1000 | Maximum total VFS file count to which the current VM may grow the world |
| `max_fs_file_bytes` | 1,048,576 | Maximum UTF-8 file size the current VM may write or copy |
| `max_fs_storage_bytes` | 67,108,864 | Approximate total VFS storage to which the current VM may grow the world, including text, paths, and directory metadata |

Despite its historical name, `max_string_bytes` limits characters per string; per-file and output quotas are measured in UTF-8 bytes. Total file storage uses the memory model's approximate-byte convention.

The three file fields are **VM constraints on file operations**, not accounts held by the VFS:

- Limits from the current VM and the actual call chain tighten together. Rejection uses the ordinary, catchable `file_limit_error` and does not terminate the execution session.
- Each constraint compares the corresponding current usage before and after an operation. An already over-limit world can still be read, shrunk, or operated on without further increasing that usage; adding files, enlarging files, and renames that increase path or directory metadata must still pass the relevant checks.
- Mutations complete path and resource checks before commit, so failure leaves no partial change. Failed attempts and retries remain normally metered.

Only the cumulative fields `max_instructions`, `max_output_bytes`, and `max_total_bytes` accept `-1` for no local cap. Every other field, including the live-count quotas `max_total_vms` and `max_descendant_vms`, is structural and must be a non-negative finite integer; every field rejects other negative values and non-integer values.

Creation checks `max_descendant_vms` on every ancestor, so a tree of child VMs cannot bypass a cap at any layer. An untrusted child reaching its own descendant limit terminates with `resource_exhausted`, which a surviving parent can catch; `max_total_vms` remains the runtime-wide backstop.

The direct-child quota `max_child_vms` has been removed. To prevent a VM from creating any descendants, set that VM's own `max_descendant_vms` to `0`; this does not prevent its parent from creating it.

When a script creates a child VM, the `VM()` quota keyword arguments correspond one-to-one with this table and can only tighten it. Combining a request with the inherited ceiling:

- a requested `-1` inherits the parent's effective value;
- a finite request under an unlimited parent applies that finite cap;
- only two unlimited values combine into an unlimited result, so a finite ancestor always remains a hard ceiling.

Granted functions are also constrained by both definition-side and caller quotas.

An unlimited quota disables only the limit check; usage is still recorded.

A child VM's instruction, memory, and creation consumption also counts against relevant ancestors. The full charging model is in the [architecture notes](architecture.md) §5.

## 6. Granting functions

A script can grant functions it defined with `def` — or granted functions it already holds — to the next layer with `functions={"name": fn}`:

```python
def double(x):
    return x * 2
sub = VM("print(double(21))", functions={"double": double})
sub.run()                        # prints 42
```

A granted sericite function:

- retains its definition-side module variables, closures, and grant environment;
- uses the definition side's environment for `print`, file operations, child-VM creation, and import, including its filesystem and module cache;
- is constrained by both definition-side and caller resource limits.

Records passed between parent and child VMs through granted functions are shared by reference, and their field contracts still hold. Errors in the receiving VM use only granted names and structural descriptions, never definition-side function names or type labels.

A granted function's parameter names are part of its public call signature and may be used as keyword arguments by the receiving VM; definition-side parameter names remain hidden in error messages.

Granting or re-granting a function grants the world reachable through it — including captured VM values, which carry their `terminate()`/`dispose()` authority. Grant only functions whose reachable state the child VM may observe or modify. The mechanism and its design invariants are in the [architecture notes](architecture.md), invariant 13 and section 5.4.
