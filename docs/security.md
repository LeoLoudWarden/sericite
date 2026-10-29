# Sericite Security Model

This document describes Sericite's threat model: what the engine guarantees, what it does not, known limitations, and how to report security issues. **If you plan to run untrusted code with Sericite, read this document first.**

## 1. Threat model

The target scenario: a host program receives a **not-fully-trusted script** (e.g. LLM-generated code, user-submitted scripts), needs to execute it, but must not allow it to read or write host state, consume unbounded resources, or learn anything about the environment it runs in.

Defense comes in two layers, and so does responsibility:

- **The engine is responsible for isolation itself holding** (section 2).
- **The capability's implementer is responsible for the capability's safety**: if you grant a VM a function via FFI, whether that function is safe inside is on you. The engine's philosophy is to keep its kernel minimal, to reduce exploitable surface inside the language itself.

## 2. What the engine guarantees

By design promise (and covered by regression tests), a script inside a VM:

- **cannot see** ungranted parent variables, parent files, host objects, or Python reflection entry points;
- **cannot tell** how deeply it is nested; error and debug views contain only logical source locations and safe values — no host tracebacks or real paths leak through;
- **cannot bypass** configured resource quotas: a child VM's consumption is charged to all its ancestors, and requesting unlimited cumulative quotas cannot remove a finite ancestor ceiling — structural resources always remain capped;
- **cannot swallow** `resource_exhausted` or `internal_error` — these two kinds are not catchable by script try/except, so quotas cannot be eaten by the script;
- **cannot receive** raw host exceptions: a host exception outside the FFI contract kills the VM with the uncatchable `host_error` — the message carries only the host exception's type name, never its text, the script cannot catch it, and it cannot be used to probe host exception types. The full FFI exception contract is in the [Sericite-PY reference](sericite-py-reference.md) §5.3;
- **cannot see** other layers' names: records/schemas carry no names; compile-time labels such as class names and annotation names are visible only in the error messages of the VM that defined them. A granted function reporting an error inside your VM does so under its granted name with structural descriptions — definition-side function names and type labels never appear.

Isolation holds on the premise of a single execution path: all VMs are driven by the same engine through one dispatch loop, and scripts cannot reach the host around the compiler's whitelist.

## 3. What the engine does not guarantee

Each of the following matters equally; evaluate them before use:

1. **The current engine is implemented in Python and runs in the host's process.** Implementation flaws in the engine or CPython itself could, in theory, break isolation. Sericite has not been through a formal external security audit — before 0.1.0 it only received internal and third-party adversarial review (section 4). **Against truly adversarial code, do not treat Sericite as your only isolation boundary**: production deployments should add an OS-level layer (separate process, container, etc.) around Sericite. Sericite's job is language-level behavioral constraint and resource governance.
2. **Host function execution time and memory are not metered.** FFI functions are trusted code; their CPU/memory cost is the host's own discipline. A malicious or runaway host function is outside quota coverage.
3. **The cost model is approximate.** Memory accounting uses approximate byte counts and only ever increases (high-water mark); O(n) operations are charged to the instruction count at a discounted rate. It defends against *unbounded growth*, not exact measurement.
4. **Default quotas are not safe values.** Defaults target development and debugging; tighten them explicitly when running untrusted code.
5. **Granting a function also grants its definition-side state.** A sericite function granted between VMs retains by reference its defining module variables, closure cells, and already-granted function environment — a function value carries its whole world with it: the state, IO/VFS, and child-VM capabilities reachable from its defining world. World services still resolve to home, while execution is jointly constrained by a causal route spanning home and caller, with shared ancestors charged once. Records likewise pass across VMs through granted functions by reference — handing out a record shares its mutable payload. Captured VM handles also convey their lifecycle authority. Grant only functions and state the child VM is allowed to influence. See the [architecture notes](architecture.md) and the [VM reference](vm-reference.md) §6.
6. **CLI Python capability configuration lives entirely outside the sandbox.** A `--capabilities` file and its third-party dependencies have full host privileges; the operator must explicitly trust and select them, and models and scripts must not choose them. The behavioral contract is in the [CLI reference](cli-reference.md) §4.
7. **Unlimited quotas do not create unlimited physical resources.** Setting a cumulative field to `-1` transfers CPU and memory responsibility to the trusted host or parent. Never grant unlimited quotas to untrusted code; add an OS-level resource boundary as well when appropriate.

## 4. Review so far

Before 0.1.0 the prototype went through one round of adversarial security review (independent internal audit plus a third-party perspective), with the scenario set as "an LLM produces arbitrary malicious code executed via `sericite_exec`". Coverage: isolation escape (whitelist / dunder / attribute access), denial of service (unbounded resource growth, snapshot amplification, compounding via tree-shaped child-VM creation), information leak (FFI messages, error views, snapshot contents), compile-time attacks (recursion stack overflow, oversized source). All findings were fixed and pinned with regression tests.

The 0.4.0 release (records and annotation contracts) received a follow-up differential review to the same standard, covering: closedness of attribute dispatch, cross-VM label leakage, quota accounting of contract checks, and host-internal information leaks. Its findings were fixed in 0.4.1 and pinned with regression tests (see CHANGELOG).

For responsible disclosure, concrete attack payloads are not listed in public documents. If you need to evaluate whether a class of attack is covered, open an issue or ask privately (next section).

## 5. Known semantic deviations

The engine has a list of known semantic deviations — behaviors that differ from intuition or from Python as deliberate prototype trade-offs. They are not security holes, but you should know them before writing programs that depend on exact semantics. The full list is in the "known boundaries" section of the [architecture notes](architecture.md).

## 6. Reporting security issues

Please use GitHub's private vulnerability reporting (repository page → Security → Report a vulnerability) and do not disclose details publicly before a fix is released. Examples of what falls within the engine's responsibility are in [SECURITY.md](../SECURITY.md) at the repository root.

## 7. Usage advice

- When running untrusted code, set quotas explicitly at every VM layer; do not rely on defaults.
- Grant only the capabilities a script actually needs; validate inputs and bound resources inside the functions you grant.
- Treat Sericite as the language layer of a defense-in-depth setup, not the only boundary.
