# Engine and limits

This document defines `SericiteEngine` and `SericiteLimits`. They and the other public types touched here can all be imported directly from the top-level `sericite` package.

## SericiteEngine

```python
SericiteEngine(limits: SericiteLimits | None = None)
```

Create an engine. An engine executes the root VMs created through it, as well as all script descendants of those VMs.

`limits` is the complete quota set used by default for new root VMs; `None` means use the defaults of `SericiteLimits()`. Passing any other type raises `type_error`. `SericiteLimits` is immutable; you can later pick a different complete configuration for a particular creation through the root's `limits` parameter.

The engine has no third-party runtime dependencies and does not use Python `exec()` or `eval()` to execute Sericite source. The internal structure of compilation and execution is not part of the host API.

## SericiteEngine.create_root

```python
engine.create_root(
    source: str | None = None,
    inputs: Iterable[str] | None = None,
    input_provider: Callable[[], str | None] | None = None,
    limits: SericiteLimits | None = None,
    addons: dict[str, Callable[..., object]] | None = None,
    output_writer: Callable[[str], object] | None = None,
    buffer_output: bool = True,
    argv: Iterable[str] | None = None,
    fs: VFSHandle | None = None,
    entry_file: str | None = None,
) -> VMHandle
```

Compile and create a root VM, returning the `VMHandle` bound to it. Do not instantiate `VMHandle` directly.

### Program source

`source` and `entry_file` must be provided exactly one at a time:

| Parameter | Contract |
|---|---|
| `source` | A Sericite source string. Modules resolve from the workspace root `/`. At most 4 MiB after UTF-8 encoding; exceeding it raises `syntax_error` |
| `entry_file` | The path of an entry file in the workspace. A valid `fs` whose file tree is detached must be provided at the same time; the entry's directory is the module resolution root |
| `fs` | An optional `VFSHandle`. After a successful creation, the detached workspace is moved exclusively into the root and the old handle becomes invalid; when omitted, an empty VFS is created |

File functions are always rooted at the workspace root; the module resolution root only affects imports. Reading `entry_file`, its path, and file errors follow the [VFS and files rules](03-vfs-and-files.md).

A failed creation does not invalidate `fs`. `fs` must belong to the current engine, be a valid handle, and have its file tree detached; cross-engine or otherwise invalid handles are rejected. Entry reading and compilation failures also preserve workspace ownership.

### Input and output

| Parameter | Default | Contract |
|---|---|---|
| `inputs` | `None` | An iterable of preset input strings; copied at creation and queued in order |
| `input_provider` | `None` | A zero-argument host function called after the queue is exhausted, returning the next line string or `None` |
| `output_writer` | `None` | A host function called with this chunk of text after each root virtual-stdout commit |
| `buffer_output` | `True` | Whether to retain root stdout in memory; must be strictly `bool` |

`inputs` accepts any iterable of strings, including lists, tuples, and generators. Passing a string directly queues it character by character; to provide one line of input, use a container such as `[line]`. `argv` also accepts an iterable of strings but explicitly rejects a single string. All elements of both must be strings; the elements are read and copied at creation, so later changes to the original container do not affect the VM.

When the provider returns `None`, raises `EOFError`, or raises `StopIteration`, the VM enters a recoverable `waiting_input`. A trailing newline on a returned line is removed. When the input source is permanently closed, the provider should raise `SericiteError(kind="input_error")` rather than using `None` to mean a permanent error.

The string the writer receives includes this `print()` call's separator and `end`. Output metering, the limit check, and optional buffering happen before forwarding; the writer's return value is ignored. With `buffer_output=False`, the buffered views of `run()`, `stdout()`, and snapshots are empty, but the writer and observation events still see committed output, and the output limit continues to apply.

A root's input provider and output writer are not automatically inherited by script descendants. They are trusted host callbacks, and their internal resource consumption and external side effects are the host's responsibility.

### Capabilities, arguments, and limits

| Parameter | Default | Contract |
|---|---|---|
| `addons` | `None` | A dictionary from string import names to Python callables, granted through `__addon__` |
| `argv` | `None` | An iterable of strings for the root's initial `argv`; an empty list when omitted |
| `limits` | `None` | The complete `SericiteLimits` used by this root; `None` uses the engine's default configuration |

`create_root(limits=...)` replaces the whole configuration rather than merging field by field with the engine defaults. A root's descendants follow the script VM rules and can only tighten quotas.

`argv` is the root's initial module variable and does not automatically appear in child VMs. It may share a name with an addon import; if an import would rebind a local built-in, the receiver needs an import alias.

For the complete validation, data, and exception contract of addons, see the [addon reference](04-addons.md).

### Creation failure

Wrong parameter shapes are usually reported as `SericiteError(kind="type_error")`. Unknown Python keyword arguments are rejected by Python itself with `TypeError`.

The VM creation and observation events are committed only after parameter validation, entry reading, and compilation all succeed. A failed creation produces no `vm.created` and should not leave a usable new root handle. Source or entry compilation errors use `syntax_error`; file reads use the corresponding file errors.

## SericiteEngine.create_vfs

```python
engine.create_vfs() -> VFSHandle
```

Create an empty detached workspace. The root directory `/` always exists. The returned handle can only be used in the current engine; you can preset content through its file methods and then hand it to `create_root(fs=...)`.

Do not instantiate `VFSHandle` directly. File writes on a detached handle use the file constraints in the engine's default `limits`; once attached to a VM, host management through `VMHandle` uses that VM's quotas. See [VFS and files](03-vfs-and-files.md) for details.

## SericiteEngine.observe

```python
engine.observe(
    sink: Callable[[SericiteEvent], object],
) -> SericiteObservation
```

Register an observation session that receives root and descendant events committed by this engine afterward. A non-callable sink raises `type_error`. For the complete interface, see the [observation reference](05-observation.md).

## SericiteLimits

```python
SericiteLimits(
    max_instructions: int = 1_000_000,
    max_output_bytes: int = 1_048_576,
    max_frames: int = 100,
    max_list_size: int = 100_000,
    max_dict_size: int = 100_000,
    max_string_bytes: int = 1_048_576,
    max_int_bits: int = 4096,
    max_total_bytes: int = 67_108_864,
    max_descendant_vms: int = 1000,
    max_vm_depth: int = 8,
    max_fs_files: int = 1000,
    max_fs_file_bytes: int = 1_048_576,
    max_fs_storage_bytes: int = 67_108_864,
)
```

This is an immutable dataclass. All fields have defaults; evaluate whether these values fit the task before using them. The defaults are intended for development and debugging, not a safety recommendation for running untrusted code.

| Field | Default | What it limits |
|---|---:|---|
| `max_instructions` | 1,000,000 | Instructions and size-scaled work |
| `max_output_bytes` | 1,048,576 | Cumulative committed stdout UTF-8 bytes per VM |
| `max_frames` | 100 | Call-frame count |
| `max_list_size` | 100,000 | Slots in a single list/tuple; also part of the addon boundary size constraint |
| `max_dict_size` | 100,000 | Items in a single dict; also part of the addon boundary size constraint |
| `max_string_bytes` | 1,048,576 | Characters in a single string; the name keeps the historical "bytes" wording |
| `max_int_bits` | 4096 | Integer bit width |
| `max_total_bytes` | 67,108,864 | Approximate high-water mark of memory usage |
| `max_descendant_vms` | 1000 | The whole live-descendant count of each VM, excluding itself |
| `max_vm_depth` | 8 | VM nesting depth, with the root at depth 0 |
| `max_fs_files` | 1000 | The total number of VFS files that file operations can expand to |
| `max_fs_file_bytes` | 1,048,576 | UTF-8 bytes of a single file that can be written or copied |
| `max_fs_storage_bytes` | 67,108,864 | The approximate total VFS storage that file operations can expand to |

All fields accept only strict integers; `bool` is not treated as an integer. Only `max_instructions`, `max_output_bytes`, and `max_total_bytes` accept `-1`, meaning no upper bound for that layer's corresponding cumulative quota; the other fields must be non-negative finite integers. Invalid values raise `type_error`; unknown fields are rejected by Python with `TypeError`.

### Inheritance and cross-layer constraints

When a script creates a child VM, each quota takes the stricter of the parent's limit and the requested value:

- Requesting `-1` does not remove a finite ancestor limit;
- a cumulative use is unbounded only when every relevant layer is unbounded;
- a child VM's instruction, memory, and creation consumption is also charged to its relevant ancestors, and a finite ancestor is always a hard limit;
- `max_descendant_vms=0` forbids that VM from creating any descendant, without affecting its parent creating it;
- unlimited quotas only disable the limit check; they do not stop accounting, and they do not mean physical resources are infinite.

For the complete script-side inheritance rules, see [VM limits](../../scripting/reference/06-vm.md#limits); for the charging model and approximate cost boundaries, see the [architecture notes](../../../architecture.md#5-resource-quotas).

The three `max_fs_*` fields constrain the file world that one actual call chain can expand to; they are not quotas carried permanently with the VFS. When taking over an already-over-limit workspace, operations that shrink it or do not expand the over-limit items further may still be allowed; a constraint that refuses a change uses the ordinary, catchable `file_limit_error`, unlike the `resource_exhausted` of an exhausted execution quota.
