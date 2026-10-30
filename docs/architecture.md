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
| `engine` | Dispatch loop, frames/evaluation stack, operator semantics, exception unwinding (across frames and VMs), built-ins, VM lifecycle and exec delivery, resource quotas, debug snapshots |
| `accounting` | Causal account routes, unified meters, atomic charging, and one-shot resource-mutation permits |
| `vfs` | Per-VM private virtual filesystem (pure memory, text only; flat file dictionary + direct-child directory tree and name metadata) |
| `io` | Per-VM virtual input and output (output byte cap and optional buffering; script input mutations require permits, while host preconfiguration uses explicit trusted channels). Output can be forwarded through an explicitly configured writer: script side in the [VM reference](vm-reference.md) §4, host-side root callback in the [Sericite-PY reference](sericite-py-reference.md) §2 |
| `errors` | `SericiteError` and the central error-kind registry |
| `cli` / `__main__` | Command-line entry points: source loading with include composition and source-line mapping, trusted capability-file loading, root argv initialization, one-shot execution and a REPL built on persistent `exec()`, and host-side diagnostics. Does not change compilation, dispatch, or isolation invariants (command-line contract: [CLI reference](cli-reference.md)) |

The `compiler` package is split into cohesive parts:

- `_rules`: whitelist tables, operator maps, reserved/VM-method names
- `_validate`: AST whitelist and except-kind validation
- `_scopes`: lexical scope/cell analysis
- `_stack`: static stack-depth analysis so the stack can be safely truncated on exception catch
- `_compiler`: the `_Compiler` emitting the instruction stream
- `__init__`: holds `compile_source`, which orchestrates the pipeline

The `engine` package is split into cohesive parts:

- `_model`: limits, frames, functions, schemas/records, native wrappers, VMContext/VMHandle
- `_values`: value semantics, rendering, contract helpers, FFI deep-copy
- `_core`: lifecycle, dispatch loop, exception unwinding, call machinery
- `_builtins`: built-in functions, child-VM creation
- `_operators`: operator/index/attribute semantics, container/record natives
- `_hostdbg`: VM-handle method charging, debug snapshots
- `__init__`: assembles `SericiteEngine` from these parts and re-exports the public API

## 3. Design invariants

Anyone modifying the engine must preserve the following invariants (numbered for reference only):

1. All VMs must be executed directly by the same `SericiteEngine`; never wrap another interpreter layer per nesting level. A nested VM is just another execution context in the same engine — this is the structural foundation of "creating a child VM is cheap" (measured in [benchmarks/vm_creation.py](https://github.com/LeoLoudWarden/sericite/blob/main/benchmarks/vm_creation.py)).
2. A child VM must not implicitly read its parent's or the host's stdin, nor write directly to the host's stdout; a child VM's filesystem starts fresh and empty, sharing no files with its parent.
3. A child VM by default cannot obtain parent locals, parent handles, host objects, or Python reflection entry points.
4. Script capabilities are provided through controlled native functions and VM handle methods; arbitrary Python attributes must not be exposed.
5. Execution must go through the internal instruction stream and the unified dispatch loop; `run()`, `exec()`, `step()`, and `step_instruction()` share the same execution path — no bypassing execution semantics. `run()` takes no per-statement snapshots; snapshots are produced only by explicit `step()/snapshot()` calls.
6. New syntax must first pass the compiler whitelist and then be compiled to instructions; introducing `exec`/`eval` for convenience is forbidden.
7.
  - a. Error and debug views may only contain logical source locations and safe values; host tracebacks and real paths must not leak by default; a script cannot tell its own nesting depth.
  - b. Host `RecursionError` becomes `resource_exhausted`, `OverflowError` becomes `conversion_error`, and raw host exceptions never enter scripts.
  - c. `SericiteError.filename` embeds the engine-local vm_id and is host-only. Script-facing error surfaces — the value bound by `except kind as e`, the snapshot `error` view, and message text — must contain no leak channel.
  - d. Capture call frames before exception unwinding and store them per VM. Same-VM rethrows preserve the original trace; cross-VM propagation neither joins nor overwrites another layer's trace.
  - e. Frame names follow invariant 16's sanitization; lines from code defined in another VM are redacted to `None`, and the error site's `error.line` uses the same sanitized error-site frame.
  - f. A corrupted caller `pc` degrades to an unknown line rather than raising a diagnostic-side exception.
  - g. Trace capture, snapshot formatting, and script record materialization are metered.
  - h. When diagnostic construction exhausts quotas: an ordinary error may become the current VM's `resource_exhausted`; if the original error is already `resource_exhausted`, `internal_error`, or `host_error`, preserve it and degrade to an empty trace instead of recursively replacing it.
8. When adding a capability, consider isolation, resource accounting, lifecycle, and debugging semantics together — not just making the syntax runnable. All dynamic consumption must go through the unified Meter and AccountRoute; a child VM's consumption must be charged to its ancestors.
9. Sericite value semantics are defined by engine helper functions and do not directly inherit Python operators' implicit behavior (e.g. bool does not participate in arithmetic).
10.
  - a. A `resource_exhausted` originating in the current VM or any of its ancestors must not be catchable by script `try/except` — a VM must not swallow its own or an ancestor's quotas.
  - b. A `resource_exhausted` arriving from another, terminated VM may be caught by a living parent.
  - c. `internal_error` is always uncatchable.
  - d. A cross-VM resource error internally records the VM that owns the actually exhausted account on the causal route, and that identifier must never enter script-visible values.
11. The VM-handle method whitelist has exactly one source (defined on the compiler side); the engine references it, and the two sides must not diverge.
12.
  - a. The host boundary (FFI) must deep-copy in both directions with a type whitelist (None/bool/int/float/str/list/dict, recursive): handles, functions, records/schemas, and host-native objects must never cross.
  - b. FFI exception contract: host callbacks signal failure only by raising `SericiteError` with a contract kind; any `Exception` outside the contract is a governance failure and kills the VM with the uncatchable `host_error`. The full contract is in the [Sericite-PY reference](sericite-py-reference.md), section 5.3.
  - c. Functions granted between VMs are passed by reference within the same engine trust domain, not copied.
13.
  - a. A granted sericite function executes on the **calling VM's frame stack**, with instructions charged to the caller and its ancestors.
  - b. The function also retains the **definition-side environment**: the defining function's closure cells, the defining VM's module variables, the definition side's granted-function environment, and the defining VM's builtin services (IO / filesystem / child-VM creation all resolve back to the defining VM — the function's home).
  - c. Reverse or cross combinations are not allowed; re-granting must preserve all of these definition-side environments.
  - d. A script output writer is invoked synchronously after output accounting. Its frames have an exception-unwinding boundary at the triggering `print()`, and writer suspension is rejected rather than suspending a native call midway.
14. Every resource that can grow must have a quota. Every instruction and dynamic operation must go through a Meter and AccountRoute; post-hoc charging, ledger-delta mirroring, and bypassing resource permits are forbidden. Debugging, errors, suspension, and cross-VM paths follow the same rule. See section 5 for the concrete contracts.
15. The dispatch entry has re-entrancy protection: the same VM must not be driven by two dispatch loops at once (e.g. the host calling `run()`, `exec()`, or `step()` on the same VM from inside an `input_provider`/FFI callback).
16.
  - a. Only structure crosses VMs: records/schemas carry no names, and schema equality compares the structure of field sets and contracts; class names, annotation names, and other labels are compile-time, scope-local diagnostic data that expires at scope exit.
  - b. Errors raised by foreign code (a CodeUnit whose `origin_vm` differs) in the current VM — attribute hints, parameter/return contracts, arity — must fall back to structural descriptions and the granted name; definition-side function names, type labels, and parameter names (replaced by positional indices) must not appear. Foreign `name_error` uses a generic undefined-name message without the definition-side local, closure, or module variable name;
  - c. New value forms or cross-layer channels must likewise guarantee that names do not cross layers with values. Design rationale is in [design](design.md) §3.4; script-visible semantics in the [language reference](language-reference.md) §7.

## 4. Script interface

The script-visible builtin functions and container methods are owned by the [language reference](language-reference.md) §6; VM-handle methods and VM states by the [VM reference](vm-reference.md) §§3–4. On the engine side, this interface carries only two internal responsibilities: the compiler-side whitelist is the single source of these names (invariant 11), and container/string methods dispatch through closed native paths that never expose arbitrary Python attributes. Charging rules for method calls are in section 5.

Error kinds are centrally registered in the `errors` module. The compiler rejects unknown filter names and always-uncatchable kinds; the runtime catchability of `resource_exhausted` is determined by its source VM (invariant 10). The full kind list is in the [language reference](language-reference.md) §5.

## 5. Resource quotas

Quotas are defined by `SericiteLimits`; the field list and defaults are in the [VM reference](vm-reference.md) §5. This section covers only the charging model.

### 5.1 Basic rules

- A child VM inherits its parent's quotas by default; `VM()` arguments can only tighten them.
- The cumulative quota fields accept `-1` for no local cap; structural fields always remain finite.
- Instruction, memory, and child-VM consumption is charged to all ancestors; exceeding the quota at any finite ring fails. Unlimited accounts still accumulate their ledgers.
- The memory ledger is an approximate, monotonically increasing high-water mark; closure cells and captured environments are included.
- O(n)-and-above work is charged to `instruction_count` at a scale-proportional rate, not treated as one instruction.

### 5.2 Time costs: prepaid or incremental

- The unified Meter handles the base cost of every instruction.
- Every native explicitly declares `home`, `work`, and `allocation`; constant costs must be explicit too.
- Predictable dynamic costs are charged before execution. Copying, rendering, comparison, snapshots, and other composite workloads are charged per node or small slice, never after completion.
- Validation, estimation, failures, and result construction are work too; they must not become free channels.

### 5.3 Space costs: owners and permits

- Script-driven IO/VFS mutations consume a one-shot `AllocationPermit`, bound to the owner, resource kind, and amount; permits cannot be reused or redirected.
- Logical allocations such as containers are metered by trusted primitives; Python containers need not be wrapped.
- Each charge checks every account on its route before committing anywhere. Rejected charges are not partially committed; charges for completed work are retained.
- Direct host preconfiguration and management use explicit trusted channels, which scripts cannot use to bypass permits.

### 5.4 Causal routes and result ownership

- An AccountRoute is constructed from caller, home, and target when a call begins; every instruction in that execution scope uses it.
- Shared ancestors are charged once per causal charge, with no special cross-sibling delta mirroring.
- VM-method execution is normally jointly constrained by target and caller; result ownership enters only the actual caller's route.
- Exception: read-only handle operations on a terminal target execute no target code and are charged only to the caller; write and driving operations do not use this exception.
- A child VM created through a granted function is an empty world attached causally under its initiator, with quotas tightened elementwise across home and caller.

### 5.5 Checklist for new language features

When adding an opcode, native, VM method, or cross-boundary channel, answer these questions in order:

1. **What is the work?** Include validation, sorting, copying, hashing, comparison, error text, and hidden complexity in host primitives.
2. **When is it charged?** Can it be prepaid? If not, is it split into interruptible slices rather than charged after completion?
3. **Who owns the resource?** Which owner accounts for new objects, queue entries, directories, or temporary structures, and is a permit required?
4. **Who triggers and receives it?** Are home, caller, target, and result ownership separately explicit?
5. **What about unusual paths?** Do failures, suspension, resumption, debugging, and cross-VM calls still use the same Meter and permits?
6. **Are tests isolated?** Use before/after checkpoints for small/large inputs, tight quotas, mid-operation failures, and pre-mutation blocking instead of only checking whole-VM totals.

## 6. Measured performance

Latest recorded runs use an Intel i3-9100 on Linux x86_64 with CPython 3.13.13 (2026-10-26). All values are medians.

| Operation | Measured cost | Reproduction |
|---|---:|---|
| Create a child VM inside a script | ~88 µs/VM | [vm_creation.py](../benchmarks/vm_creation.py) |
| Create and run a root VM from the host | ~61 µs/VM | [vm_creation.py](../benchmarks/vm_creation.py) |
| Execute a representative counting loop with `run()` | ~0.82 µs/instruction | [instruction.py](../benchmarks/instruction.py) |
| Drive the same loop with `step_instruction()` | ~2.60 µs/instruction (3.19× `run()`) | [debugging.py](../benchmarks/debugging.py) |
| Drive the same loop with `step()` | ~6.32 µs/step call (~1.40 µs/instruction) | [debugging.py](../benchmarks/debugging.py) |

Caveats:

- The instruction figure is a workload-weighted average, not a uniform per-opcode cost.
- VM creation and compilation are excluded from the table.
- Stepping figures include single-step control and a safe snapshot after every step.
- The workload has a single simple local variable.
- These are measurements of the Python prototype, not performance guarantees; future engine changes require re-measurement.

## 7. Current prototype capability overview

- Built-in types: int, float, str, bool, None, list, dict; operators, comparisons, membership, short-circuit logic.
- Records and schemas: `class` defines a runtime structural contract (fields + per-field contracts), dot member access, fixed shape, `wrap`/`unwrap` conversion to and from dicts; annotations (parameters / return / annotated assignment) execute as real runtime contracts with blame-style errors; class and annotation names are compile-time labels used only in error text.
- Control flow: `if/elif/else`, `while`, `for`, `break/continue`, `try/except/else/finally`, `raise`, ternary expressions.
- Functions: definitions, recursion, positional and keyword arguments, default arguments, decorators, independent call frames, lexical closures with by-reference capture.
- VMs within VMs: any layer can create child VMs; a child cannot tell its depth; the parent can preset files, feed input, single-step (statement- and instruction-level), snapshot, and terminate.
- Capability granting (FFI): the host injects functions into the root VM; any layer can grant functions to the next layer down; bidirectional deep copy across the host boundary with a pure-data type whitelist.
- Resource governance: see the previous section. The prototype went through one round of adversarial security review (including an independent third-party perspective); all discovered denial-of-service and information-leak paths were fixed and locked in with regression tests.
- Every VM has its own private virtual filesystem, configurable before the run and harvestable after.

Deliberate trade-offs: additional container methods, variadic arguments, chained comparisons, `import` are not yet supported — these are usability or expressiveness matters, to be added on demand; they do not affect the design's main line.

## 8. Known limits and semantic deviations

- Host callback execution time and memory are self-policed by the host and are not metered. Engine-side FFI argument/result copying is charged per node, and host return structures are also bounded by a node budget and depth limit.
- The total memory ledger is approximate (strings counted as chars ×4, list slots ×8, dict entries ×16), monotonically increasing (high-water mark), with no simulated release — conservative but safe.
- `repr` applies `max_string_bytes` to the fully rendered result, including quotes and escapes. An input string that is itself within the limit can therefore produce a `resource_exhausted` uncatchable in the current VM when its rendered result exceeds the limit; propagation to another VM follows the cross-VM resource-error rules (invariant 10).
- Recursive safe rendering uses placeholders for cycles and repeated references. Shared non-cyclic containers can therefore render as `[...]`, `{...}`, or `record(...)` instead of being expanded repeatedly.
- `for` iterates lists as a live view and dicts as a key snapshot.
- A VM's execution context is retained after reaching a terminal state for debug snapshots and further `exec` deliveries; release it with `dispose()` (contract in the [VM reference](vm-reference.md) §3).
- Each charge checks every account on its route before committing anywhere; a rejected new charge is not partially committed, while charges for completed work are retained.
- Cross-VM calls charge shared ancestors once; the full charging rules are in section 5.4.

## 9. Explicitly not supported yet

String, list, and dict methods outside the documented closed sets; variadic/keyword-only parameters, `**` unpacking, chained comparisons, slice assignment, tuples, `import`, `del`, class field defaults/methods/inheritance.
