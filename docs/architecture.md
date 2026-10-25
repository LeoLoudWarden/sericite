# Sericite Architecture Notes

This document describes the internal structure and current implementation status of Sericite-PY (the Python reference implementation). For the design rationale see [design](design.md); for language behavior see the [language reference](language-reference.md); for security boundaries see the [security model](security.md).

## 1. Execution pipeline

```text
source → ast.parse → node-whitelist validation → compile to internal instruction stream → engine dispatch loop, one instruction at a time
```

`exec`/`eval` are never used. Source execution naturally passes through the unified metering, IO, and debugging control plane, rather than "a few dangerous names being banned".

## 2. Module structure

| Module | Responsibility |
|---|---|
| `isa` | Instruction, code-unit, and exception-handler-table definitions (stack machine) |
| `compiler` | AST whitelist and except-kind validation + compilation to the instruction stream (the only entry point for source code); includes static stack-depth analysis so the stack can be safely truncated on exception catch |
| `engine` | Dispatch loop, frames/evaluation stack, operator semantics, exception unwinding (across frames and VMs), built-ins, VM lifecycle, resource quotas, debug snapshots |
| `vfs` | Per-VM private virtual filesystem (pure memory, text only; flat path dictionary, implicit directories) |
| `io` | Per-VM virtual input and output (with output byte cap) |
| `errors` | `SericiteError` and the central error-kind registry |
| `cli` / `__main__` | Command-line entry points |

## 3. Design invariants

Anyone modifying the engine must preserve the following invariants (numbered for reference only):

1. All VMs must be executed directly by the same `SericiteEngine`; never wrap another interpreter layer per nesting level. A nested VM is just another execution context in the same engine — this is the structural foundation of "creating a child VM is cheap" (measured in [benchmarks/vm_creation.py](https://github.com/LeoLoudWarden/sericite/blob/main/benchmarks/vm_creation.py)).
2. A child VM must not implicitly read its parent's or the host's stdin, nor write directly to the host's stdout; a child VM's filesystem starts fresh and empty, sharing no files with its parent.
3. A child VM by default cannot obtain parent locals, parent handles, host objects, or Python reflection entry points.
4. Script capabilities are provided through controlled native functions and VM handle methods; arbitrary Python attributes must not be exposed.
5. Execution must go through the internal instruction stream and the unified dispatch loop; `run()`, `step()`, and `step_instruction()` share the same execution path — no bypassing execution semantics.
6. New syntax must first pass the compiler whitelist and then be compiled to instructions; introducing `exec`/`eval` for convenience is forbidden.
7. Error and debug views may only contain logical source locations and safe values; host tracebacks and real paths must not leak by default; a script cannot tell its own nesting depth.
8. When adding a capability, consider isolation, resource accounting, lifecycle, and debugging semantics together — not just making the syntax runnable. Resource consumption must be meterable at instruction level; a child VM's consumption must be charged to its ancestors.
9. Sericite value semantics are defined by engine helper functions and do not directly inherit Python operators' implicit behavior (e.g. bool does not participate in arithmetic).
10. `resource_exhausted` and `internal_error` must not be catchable by script `try/except` — quotas must not be swallowed by scripts.
11. The VM-handle method whitelist has exactly one source (defined on the compiler side); the engine references it, and the two sides must not diverge.
12. The host boundary (FFI) must deep-copy in both directions with a type whitelist (None/bool/int/float/str/list/dict, recursive): handles, functions, records/schemas, and host-native objects must never cross; host exceptions must be sanitized into `ffi_error`, with messages containing only the host exception's type name, not its text (to prevent leaking host paths or internal information). Functions granted between VMs are passed by reference within the same engine trust domain, not copied.
13. A granted sericite function executes on the **calling VM's frame stack** (instructions charged to the caller and its ancestors), but retains the **defining function's closure cells, the defining VM's module variables, the defining side's granted-function environment, and the defining VM's builtin services** (IO / filesystem / child-VM creation all resolve back to the defining VM — the function's home); the reverse or cross combinations are not allowed. Re-granting must preserve all of these definition-side environments.
14. Every resource that can grow must have a quota (see next section). `run()` does not take per-statement snapshots — snapshots are only produced on explicit `step()/snapshot()` calls; the debugging path must not become a resource bypass. Host `RecursionError` is always converted to `resource_exhausted`, `OverflowError` to `conversion_error`; host exceptions must never leak to scripts or callers in native form. O(n)-and-above operations must be charged against the instruction quota at a scale-proportional rate, and newly created objects must be accounted. World-service consumption triggered through a granted function belongs to the defining VM (home), but must also be mirrored causally into the triggering caller's quotas (the mirror stops at home and never double-counts it); a child VM created through a granted function is an empty world whose tree position (parent/depth/child count) attaches causally under the triggering caller, with quotas equal to the elementwise minimum of home's and the caller's.
15. The dispatch entry has re-entrancy protection: the same VM must not be driven by two dispatch loops at once (e.g. the host calling `step()` on the same VM from inside an `input_provider`/FFI callback).
16. Only structure crosses VMs: records/schemas carry no names (schema equality compares the structure of field sets and contracts); class names, annotation names, and other labels are compile-time, scope-local diagnostic data, baked only into the current layer's CodeUnit instructions and metadata, and expire at scope exit. Errors raised by foreign code (a CodeUnit whose `origin_vm` differs) in the current VM — attribute hints, parameter/return contracts, arity — must fall back to structural descriptions and the granted name; definition-side function names, type labels, and parameter names (replaced by positional indices) must not appear. New value forms or cross-layer channels must likewise guarantee that names do not cross layers with values.

## 4. Script interface

Built-in functions:

- `input()`: read one line of the current VM's input.
- `print(value, ...)`: write to the current VM's stdout buffer.
- `len(x)`, `int(x)`, `float(x)`, `str(x)`, `range(...)`, `keys(d)`.
- `read_file(path)`, `write_file(path, text)`, `list_dir(path)`, `path_exists(path)`: operate on this VM's private filesystem (text only).
- `VM(code, **limits)`: create a child VM, optionally with resource-quota arguments (tightening only); the special argument `functions={name: fn}` grants functions (sericite functions or already-held granted functions) to the child VM.
- Host injection: `SericiteEngine.create_root(source, functions={name: python_callable})` grants host functions to the root VM.

VM handle methods (identical on the script and host sides): `run(inputs)`, `feed_input(text)`, `step()`, `step_instruction()`, `snapshot()`, `stdout()`, `terminate()`, plus `read_file` / `write_file` / `list_dir` / `path_exists` (configure/read that VM's filesystem).

VM states: `ready`, `waiting_input`, `done`, `error`, `resource_exhausted`, `terminated`.

Error kinds: `runtime_error`, `syntax_error`, `validation_error`, `type_error`, `zero_division`, `conversion_error`, `index_error`, `key_error`, `name_error`, `arity_error`, `raise_error`, `file_not_found`, `is_directory`, `not_directory`, `ffi_error`, `input_error`, `attribute_error`, `contract_error`, `resource_exhausted`, `internal_error`. The `errors` module is their single registry. All except `resource_exhausted`/`internal_error` can be caught by `try/except` with kind filtering; the compiler rejects unknown filter names as `validation_error`.

## 5. Resource quotas

Quotas are defined by `SericiteLimits`: `max_instructions`, `max_output_bytes`, `max_frames`, `max_child_vms`, `max_list_size`, `max_dict_size`, `max_string_bytes`, `max_int_bits`, `max_total_bytes`, `max_total_vms`, `max_vm_depth`, `max_fs_files`, `max_fs_file_bytes`.

Rules:

- A child VM inherits its parent's quotas by default; `VM()` arguments can only tighten them.
- Total source length has a fixed cap of 4MB (in UTF-8 bytes).
- Besides instruction count, bulk operations (container comparison/membership, concatenation, serialization, compiling child-VM source, VM-method return values) are charged to `instruction_count` at a scale-proportional rate.
- Closure cells and captured environments are charged to `max_total_bytes`; snapshots expose their user-visible values rather than internal cell objects.
- A child VM's instruction and memory consumption is charged to all ancestors; exceeding the quota at any ring of the ancestor chain fails.

## 6. Measured performance

Latest recorded runs use an Intel i3-9100 on Linux x86_64. Instruction and debugging figures are from CPython 3.13.13 on 2026-10-23; VM-creation figures are the existing CPython 3.13/3.14 results recorded in the reproduction script. All values are medians.

| Operation | Measured cost | Reproduction |
|---|---:|---|
| Create a child VM inside a script | ~50 µs/VM | [vm_creation.py](../benchmarks/vm_creation.py) |
| Create and run a root VM from the host | ~42 µs/VM | [vm_creation.py](../benchmarks/vm_creation.py) |
| Execute a representative counting loop with `run()` | ~0.65 µs/instruction | [instruction.py](../benchmarks/instruction.py) |
| Drive the same loop with `step_instruction()` | ~1.86 µs/instruction (2.92× `run()`) | [debugging.py](../benchmarks/debugging.py) |
| Drive the same loop with `step()` | ~4.91 µs/step call (~1.09 µs/instruction) | [debugging.py](../benchmarks/debugging.py) |

The instruction figure is a workload-weighted average, not a uniform per-opcode cost; VM creation and compilation are excluded. Stepping figures include single-step control and a safe snapshot after every step, for a workload with one simple local variable. These are measurements of the Python prototype, not performance guarantees; future engine changes require re-measurement.

## 7. Current prototype capability overview

- Built-in types: int, float, str, bool, None, list, dict; operators, comparisons, membership, short-circuit logic.
- Records and schemas: `class` defines a runtime structural contract (fields + per-field contracts), dot member access, fixed shape, `wrap`/`unwrap` conversion to and from dicts; annotations (parameters / return / annotated assignment) execute as real runtime contracts with blame-style errors; class and annotation names are compile-time labels used only in error text.
- Control flow: `if/elif/else`, `while`, `for`, `break/continue`, `try/except/else/finally`, `raise`, ternary expressions.
- Functions: definitions, recursion, positional and keyword arguments, default arguments, decorators, independent call frames, lexical closures with by-reference capture.
- VMs within VMs: any layer can create child VMs; a child cannot tell its depth; the parent can preset files, feed input, single-step (statement- and instruction-level), snapshot, and terminate.
- Capability granting (FFI): the host injects functions into the root VM; any layer can grant functions to the next layer down; bidirectional deep copy across the host boundary with a pure-data type whitelist.
- Resource governance: see the previous section. The prototype went through one round of adversarial security review (including an independent third-party perspective); all discovered denial-of-service and information-leak paths were fixed and locked in with regression tests.
- Every VM has its own private virtual filesystem, configurable before the run and harvestable after.

Deliberate trade-offs: list/dict methods, variadic arguments, chained comparisons, `import` are not yet supported — these are usability or expressiveness matters, to be added on demand; they do not affect the design's main line.

## 8. Known limits and semantic deviations

- Host-function execution time and memory are self-policed by the host and not metered (each FFI call counts as 1 instruction); host return structures are bounded by a node budget and depth limit.
- The total memory ledger is approximate (strings counted as chars ×4, list slots ×8, dict entries ×16), monotonically increasing (high-water mark), with no simulated release — conservative but safe.
- When a `finally` copy raises again, the outer `finally` may execute one extra time.
- After a nested `except` inside `except`, a bare `raise` may re-raise an object other than the outermost one.
- `for` iterates lists as a live view and dicts as a key snapshot.
- A VM's execution context is retained on the engine after reaching a terminal state (for debug snapshots); the engine-level `max_total_vms` caps the growth of their number, and terminal-state release is left to a future version.
- Quota checks happen when each layer accounts its own charges: while a descendant VM runs, its ancestors' counters are pushed up without immediate validation, so a small overrun (on the order of one call chain) can occur before triggering.
- In cross-sibling scenarios (one child VM's function re-granted to another), mirror charging is counted twice at the common ancestor — this over-counts (conservative) and does not enable quota escape.

## 9. Explicitly not supported yet

List/dict/string methods, variadic/keyword-only parameters, `**` unpacking, chained comparisons, slicing, tuples, f-strings, `import`, `del`, class field defaults/methods/inheritance.
