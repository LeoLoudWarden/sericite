# Sericite VM Reference

[中文](vm-reference.zh-CN.md)

This document is for **anyone who creates and drives VMs**: creating child VMs inside a Sericite script, or driving any VM through the host API. The contracts for VM states, driving methods, exec delivery, quotas, and function granting live here.

A VM value inside a script and a host-side `VMHandle` expose the same set of driving methods, and driving semantics are identical. Examples below use `sub.`; on the host side, substitute your own handle variable. One deliberate asymmetry: snapshots returned to the host carry additional host-only diagnostic fields (§4).

## 1. What a VM is

A VM is a mutually isolated workspace: it cannot see its parent's variables, files, or handles, and cannot tell how deeply it is nested. Every VM has its own module scope, virtual filesystem, input queue, and stdout; the isolation promises are in the [security model](security.md) §2.

A VM is not single-use: the same VM can be fed input, have files preset and retrieved, be single-stepped by statement or instruction, be snapshotted, receive new source deliveries, or be terminated at any time.

## 2. Creating VMs

Inside a script, create a child VM with `VM(code, **options)`:

```python
sub = VM(code, max_instructions=10000)   # quotas can only be tightened
sub = VM(code, output_writer=forward, buffer_output=False)
```

`output_writer` and `buffer_output` configure this VM's output; `functions` grants functions (section 6); the remaining options are quota fields. See section 4 for output forwarding and section 5 for quotas.

Root VMs are not created by scripts: the CLI creates one when running a program directly (see the [CLI reference](cli-reference.md)); in Python embedding, `SericiteEngine.create_root()` creates it (see the [Sericite-PY reference](sericite-py-reference.md)).

## 3. States and lifecycle

VM states are `ready`, `waiting_input`, `done`, `error`, `resource_exhausted`, and `terminated`.

`terminate()` marks a `ready` or `waiting_input` VM as `terminated`; in any other state it is a silent no-op — terminal VMs such as `done`/`error` still accept `exec` deliveries.

Terminal VM contexts remain available for debugging and further `exec` deliveries until explicitly disposed.

`dispose()` releases a terminal VM with no live children, so contexts are released child-first. It:

- removes the VM's frames, IO/VFS, grants, and accounting routes;
- is idempotent — repeated disposal is a no-op;
- invalidates the handle — any other method on a disposed handle fails with `runtime_error`.

Disposal does not refund quotas: VM IDs are never reused, and the parent's ledgers, `child_count`, `max_child_vms`, and the engine's cumulative `max_total_vms` are unchanged.

## 4. Driving methods

| Method | Purpose and result |
|---|---|
| `run(inputs=None) -> str` | Drive to completion, suspension, or failure and return stdout; `inputs` must be a string list/tuple and is validated as a batch before queueing |
| `exec(source) -> str` | Deliver new source into this VM and run it in the persistent module scope; returns only this delivery's output; see below |
| `feed_input(value)` | Queue one input string; resumes a VM waiting for input |
| `step() -> dict` | Execute one statement and return a snapshot |
| `step_instruction() -> dict` | Execute one internal instruction and return a snapshot |
| `snapshot() -> dict` | Return a safe snapshot without advancing execution |
| `stdout() -> str` | Return current stdout |
| `terminate()` | Terminate the VM; effective states and no-op semantics are in section 3 |
| `dispose()` | Explicitly release a terminal VM with no live children; see section 3 |
| `read_file(path) -> str` | Read a text file from this VM |
| `write_file(path, text)` | Write a text file into this VM |
| `list_dir(path) -> list[str]` | Return sorted direct children of a directory |
| `path_exists(path) -> bool` | Check whether a file or directory exists |

```python
sub = VM(code, max_instructions=10000)
sub.write_file("/input.txt", "data")     # preset a file for it
sub.feed_input("one line")               # feed input()
out = sub.run()
print(sub.read_file("/result.txt"))      # retrieve the file it wrote
```

Running out of queued input with no further provider is ordinary suspension (`waiting_input`), not an exception. On failure, host-side `run()` raises `SericiteError` to the host; in-script `sub.run()` propagates the child VM's error to the calling script under its original kind, and catchable kinds can still be caught. After a child enters the terminal `resource_exhausted` state, a parent can catch that error; the parent's own or an ancestor's quota errors remain uncatchable (full rules in the [language reference](language-reference.md) §5).

Handle operations on a terminal VM are charged in two ways depending on whether they drive the target:

- read-only operations (`snapshot`, `step`, `step_instruction`, VFS reads, …) are charged only to the caller and are not blocked by the target's exhausted accounts; terminal stepping returns a snapshot without re-driving the target;
- write or driving operations (`write_file`, `feed_input`, `run` with inputs, `exec`, …) remain jointly metered by target and caller and may be rejected by an exhausted target.

If such an operation exhausts the target's own quota, a non-terminal target enters `resource_exhausted` and the error can be caught by the living caller. A caller or shared-ancestor quota failure remains uncatchable and is not attributed to the target.

The recommended workflow remains: preset files and inputs before execution, and read results afterward.

### Output forwarding and buffering

Every VM has independent `output_writer` and `buffer_output` settings. A child writer is explicitly configured by its parent and is never inherited implicitly:

```python
def forward(text):
    print(text, end="")

sub = VM('print("live")', output_writer=forward)
```

The writer:

- receives one string for each `print()` chunk, after output accounting and buffering;
- follows granted-function semantics: execution uses the actual caller's frame stack and quotas, while module variables, closures, grants, and IO remain those of the definition side;
- forwards through the parent's configured output chain when it calls the parent's `print()`;
- ignores its return value; errors propagate at the triggering `print()` under the usual rules;
- must finish synchronously — attempting to suspend it on `input()` raises `runtime_error` at that `print()`.

`buffer_output=True` is the default and preserves complete stdout for `run()`/`exec()`/`stdout()` and snapshots. With `buffer_output=False`, output is still metered and forwarded but not retained: those buffered-output views are empty. Output and writer settings persist across `exec` deliveries.

### exec: delivering new source into an existing VM

`exec(source)` gives a VM a new program while keeping its world:

- **The retained world**: the fresh module frame reuses the previous module scope, so module-level names (variables, functions, schemas) persist; the VFS, input queue, and granted functions are untouched.
- **States and discarding**: delivery is accepted from any state except `terminated` or while the VM is being driven (`run()`/`exec()`/`step()` in progress). A program that has not finished — never started, or suspended on input — is discarded, a previous error is cleared, and old debugging frames are replaced, so call `snapshot()` first if you need them.
- **Compilation atomicity**: compilation completes before any state changes; source that fails to compile leaves the VM exactly as it was.
- **Lifetime quotas**: instruction, memory, and output consumption accumulate across deliveries, not per delivery.

### Snapshots

A snapshot returned by `step()`, `step_instruction()`, or `snapshot()` contains the script-safe view:

| Field | Meaning |
|---|---|
| `state` | Current state |
| `last_line` / `next_line` | Previous and next logical source lines |
| `locals` | Safe copies of user-visible local values |
| `stdout` | Current output |
| `error` | `kind`, `message`, `line`, `column`, and `frames`, or `None` |
| `instruction_count` | Current instruction/work ledger |

Complex values have node and depth budgets. Cycles and shared structures use placeholders rather than exponential expansion. Snapshots do not expose live child handles or host objects.

`error.frames` is that VM's call stack, ordered from the outermost call to the error site. Each entry has `function` (string) and `line` (integer or `None`); `line` is `None` for a frame defined in another VM (redacted).

When one of these methods is called from the host (on a `VMHandle`), the returned dict is a strict superset of the script-safe view above, adding host-only diagnostic fields:

| Field | Meaning |
|---|---|
| `vm_id` | Engine-local identifier |
| `parent_id` | Engine-local identifier of the parent VM; `None` for a root |
| `depth` | Nesting depth; a root is 0 |
| `child_count` | Cumulative count of direct children created |

A script's own calls always return the safe view above and can never see these fields.

## 5. Quotas

Each VM's resource quotas are defined by the following fields. Every field has a default; defaults target development and debugging, not safe execution of untrusted code.

| Field | Default | Meaning |
|---|---:|---|
| `max_instructions` | 1,000,000 | Instruction and discounted-work limit |
| `max_output_bytes` | 1,048,576 | stdout bytes in UTF-8 |
| `max_frames` | 100 | Call-frame limit |
| `max_child_vms` | 100 | Cumulative direct children per VM |
| `max_list_size` | 100,000 | Slots per list |
| `max_dict_size` | 100,000 | Entries per dict |
| `max_string_bytes` | 1,048,576 | Size per string |
| `max_int_bits` | 4096 | Integer bit width |
| `max_total_bytes` | 67,108,864 | Approximate memory high-water mark |
| `max_total_vms` | 1000 | Cumulative successful VMs per engine, including disposed VMs |
| `max_vm_depth` | 8 | VM nesting depth |
| `max_fs_files` | 1000 | Files per VM |
| `max_fs_file_bytes` | 1,048,576 | UTF-8 bytes per file |

The cumulative fields `max_instructions`, `max_output_bytes`, `max_total_bytes`, `max_child_vms`, and `max_total_vms` accept `-1` for no local cap.

All structural fields must be non-negative finite integers. Cumulative fields additionally accept `-1`; any other negative value, and any non-integer value, is rejected for every field.

When a script creates a child VM, the `VM()` quota keyword arguments correspond one-to-one with this table and can only tighten it. Combining a request with the inherited ceiling:

- a requested `-1` inherits the parent's effective value;
- a finite request under an unlimited parent applies that finite cap;
- only two unlimited values combine into an unlimited result, so a finite ancestor always remains a hard ceiling.

The same rule applies when home and caller limits are combined for granted functions.

Unlimited skips only the limit check, not accounting: diagnostic ledgers continue to grow.

Instruction, memory, and child-VM consumption is charged to relevant ancestors through causal routes. The charging model is in the [architecture notes](architecture.md) §5; a Python host configures the same fields for a root via `SericiteLimits` — see the [Sericite-PY reference](sericite-py-reference.md) §3.

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
- still resolves world services such as printing, VFS, and child creation to the defining world (home);
- executes its body on the caller's frame stack;
- is jointly constrained — world services and target execution — by causal routes spanning home/target and caller, with shared ancestors charged once;
- passes result ownership to the actual caller.

Granting or re-granting a function grants the world reachable through it — including captured VM handles, which carry their `terminate()`/`dispose()` authority. Grant only functions whose reachable state the child VM may observe or modify. VM handles themselves cannot cross FFI into the host. The mechanism and its design invariants are in the [architecture notes](architecture.md), invariant 13 and section 5.4; granting Python functions to a root from the host (FFI) is covered by the [Sericite-PY reference](sericite-py-reference.md) §5.
