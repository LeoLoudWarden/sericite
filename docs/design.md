# Sericite Design Notes

This document explains what Sericite is, why it exists, and where its design boundaries are drawn. For the language itself see the [language reference](language-reference.md); for the engine's internal structure and current implementation status see the [architecture notes](architecture.md) ([中文](architecture.zh-CN.md)).

## 1. What Sericite is

Sericite is a scripting language, together with its execution engine. Its syntax borrows a subset of Python (it reads like Python), but source code is compiled into Sericite's own instruction stream and executed instruction by instruction by the Sericite engine — never through the host's `exec`/`eval`. (The *host* is the program running the Sericite engine.)

The language exists for exactly one reason: **to create fully isolated runtime environments, at very low cost, within the language's own domain — and to nest them arbitrarily.**

Its worldview in one sentence: you live in a universe, and you can create another universe inside it; to the universe you create, you are its god — and the universe you live in may have its own god, but you can never know.

## 2. Why it is needed: the cost spectrum of virtualization

"Carving out an isolated space inside a running system" is not new; existing solutions spread across a cost spectrum:

- Hardware-level virtualization: emulate full hardware, install an OS, pay heavily in disk and memory.
- Container-level virtualization: better, but still requires initializing a whole container environment.
- Process-level isolation: relies on the OS to police each process's permissions.

Process-level isolation looks sufficient, but has two fundamental problems.

**First, the process is too heavy a unit for the OS to govern.** Every IO or syscall a process makes presents the kernel with a very complex "menu". The kernel lacks the evidence to judge whether a given call is malicious, so it cannot police at fine granularity. The result: OS-level process policing is itself riddled with holes, and privilege escalation happens regularly.

**Second, kernel-space solutions are not light enough, and history has long shown user space is cheaper.** Recall the evolution of concurrency: why threads when we had processes? Because creating processes is expensive, passing data between them is expensive, everything is expensive. Why coroutines when we had threads? Because thread switching still traps into the kernel, and when the internet brought thousands of concurrent tasks, that was still too expensive. Every step in this evolution goes the same way: **whatever can be solved in user space should not be pushed to the kernel; do not treat the OS — an overworked, hole-ridden butler — as an omnipotent nanny.**

One more step in this direction is where Sericite sits: **virtualization implemented entirely in user space, inside the language itself.** Creating a child VM in Sericite should feel as cheap as creating a sub-table in Lua. Isolation no longer depends on emulating hardware, booting containers, or requesting processes — it is a built-in capability of the language runtime.

You might ask: hasn't this been done? The honest answer is yes — once, almost exactly. Tcl has had safe interpreters as a language built-in since Tcl 7.5 (1996), descending from Borenstein and Rose's 1992 Safe-Tcl, built for "active email". A safe interpreter starts with zero capabilities; the master grants mediated capabilities back through aliases; safe interpreters can create their own children, forming a hierarchy. Isolation as a first-class, nestable language operation with explicit capability granting is a thirty-year-old validated mechanism, not a new speculation.

But Safe-Tcl stopped halfway: resource governance and a kill-key were promised in 1998, arrived only years later in partial form, and never became cross-layer quota accounting. Sericite's position in this lineage is precise: keep the validated core (zero capabilities by default, explicit granting, recursive nesting), and supply the missing half — the quota tree, and the child VM as an inspectable object (stepping, snapshots, termination). WASM runtimes, microVM sandboxes, gVisor, and Starlark each solve adjacent points on the cost spectrum; see [prior art and related work](prior-art.md) for the full comparison.

Why insist on *arbitrary nesting* rather than one layer? Because the need for isolation is recursive: your program receives an untrusted script and runs it in isolation — and that script, once running, needs to execute code it obtained dynamically. Untrustworthiness in the real world is passed down layer by layer; the isolation mechanism should be able to follow it, not just guard the front gate.

## 3. Core ideas

### 3.1 Minimal, lightweight, complete runtime isolation

A Sericite VM has no permissions by default. Built-in capabilities are deliberately compressed to very few:

- Basic input/output (each VM has its own virtual IO);
- A purely in-memory virtual filesystem (text only; physically unable to touch the real disk);
- Creating child VMs.

The virtual filesystem is the ceiling of built-in capability. Nothing more is given.

### 3.2 Capabilities are granted, not built in

A VM is of course not limited to built-ins — but that goes down a different road: **capability granting (FFI)**. The host writes functions in the host language (Python, in the current reference implementation) and injects them into the VMs it creates; likewise, any VM can write functions in its own world and grant them to the next layer down. Capabilities travel along the creation chain, layer by layer, explicitly, defaulting to zero.

Why not build network access into the VM? Because that road ends in absurdity: build in HTTP, then what about raw TCP? UDP? Bluetooth, serial ports, optical drives, microphones, cameras? — there is no end to what would need adapting. And even if all of it were adapted, every VM would grow its own network logic, Bluetooth logic, device logic — which amounts to re-simulating an entire set of physical hardware inside the language, precisely betraying the "minimal and lightweight" foundation.

So capabilities like network access belong outside, injected via FFI, not built into the engine.

This mechanism is already working in the prototype: the host injects Python functions into the root VM, and any VM can grant functions it defined with `def` (or granted functions it already holds) to the next layer. Across the host boundary, arguments and return values are deep-copied in both directions and restricted to pure data types — no shared mutable objects exist between VM and host. A host callback signals failure by raising a `SericiteError` with a contract kind; any host exception outside the contract terminates the VM with the uncatchable `host_error`. The full exception contract is in the [Sericite-PY reference](sericite-py-reference.md), section 5.3.

### 3.3 Division of security responsibility

This design splits security responsibility into two clearly bounded halves:

- **The engine is responsible for isolation itself holding.** A child VM cannot read or write parent variables or files, cannot tell how deep it is nested, cannot reach host objects or reflection entry points, and cannot bypass resource quotas. That is Sericite's design promise.
- **The capability's implementer is responsible for the capability's safety.** If you grant a VM a function via FFI, whether that function is safe inside is on you. The engine's philosophy is to keep the kernel minimal — at least not to bury landmines inside itself.

### 3.4 Structure crosses layers; names stay layer-local

The record/schema design (`class` defines a structural contract; dot member access) follows the same discipline as capability granting: **only structure crosses layers; names, capabilities, and state must each enter a layer through a door visible in that layer's own code.**

Three corollaries:

**No nominal types.** Nominal identity is decided by a creation event, and in a world of nested layers and per-layer granting it collides with identity walls everywhere — is the parent VM's `Point` the same type as a child VM's identical `Point`? With structural semantics, schemas compare by field set and contracts, are comparable across layers by nature, and the question dissolves. This also preserves the invariant that sandbox output is enumerable pure data: names never pollute values.

**Labels are compile-time, scope-local diagnostics and never enter values.** A name is a lexical fact, not a fact about a value: once a value escapes the scope that defined it (returned from a factory, passed across VMs), it has no name at all. If values carried long-lived names, an error raised in a child layer would display a symbol that appears nowhere in the child's source — and since a child VM's error messages are data it can catch, that name becomes an information channel nobody explicitly opened. A name that travels with values will eventually be used as identity (comparison, dispatch, serialization), and nominal typing returns through the back door. So class names and annotation names live only at compile time, serve only error text, and are erased at scope exit. Each layer names things explicitly at its own entry points (`r2: T2 = make()`); naming is the receiver's local act, not an inheritance shipped with the goods.

**Granted functions respect the same boundary in their errors.** A granted function retains its full definition-side environment when executing in a child VM (that is the explicitly granted capability), but its error text uses only the granted name (the key in `functions={"f": ...}`) and structural descriptions — definition-side function names and type labels never appear in the child layer. Undefined-name errors likewise omit definition-side local, closure, and module variable names. The name on the door is part of the door; the internal names of what is behind it are not.

## 4. Sericite's relationship with LLMs

A common misreading must be corrected: **Sericite is not "a tool for LLMs".**

The real relationship is this: LLM applications are Sericite's most direct and realistic current driver — when a system must dynamically face hundreds or thousands of generated scripts, all of which must run in isolation, "cheap, nestable isolation" goes from nice-to-have to hard requirement. Sericite was born of this era's demand.

But the relationship is one-directional: **the scenario chose Sericite; Sericite's design is not coupled to the scenario.** The Sericite engine does not know what an LLM is, has no LLM-related built-ins, and does not depend on any model service in any form; without the LLM scenario, the proposition of "cheap, nestable, user-space isolation" still stands. You can, at the application layer, hang the Sericite engine behind a tool like `sericite_exec` on some LLM service's tool list — the engine itself does not care how you use it.

## 5. Prototype vs. design: distinguishing "where we are going" from "where we are"

When reading this project, always separate two levels:

- **Design**: the goals and boundaries described in sections 1–4 above. This is where the project is going.
- **Prototype**: the code in the repository is the reference implementation (codename Sericite-PY), written in Python. It is a work-in-progress draft, meant to answer "once this design lands, what does the syntax and usage actually look like" — to fix the language's blueprint.

So "the prototype is currently incomplete" and "whether the design holds" are two different things. Missing features will be added; the prototype's implementation limits (for example, it currently runs in the host's process) are the state of construction, not a retreat from the design.

The same distinction applies to "cost": the claim in section 2 that "creating a child VM should be as cheap as creating a table" is a design goal and direction of effort — but "cheap" now has first measurements behind it. On the current Python prototype, creating a child VM via `VM()` inside a script costs about 0.088 ms — the same order as spawning a thread, and one to two orders of magnitude below a process. To be clear: these are measurements of the reference prototype, not a performance guarantee. The full measurements and reproduction scripts are in the [architecture notes](architecture.md), section 6; any future engine rewrite must re-measure.

As for the future release form — whether the engine base stays in Python or migrates to another language to produce a standalone binary runtime (say, a `sericite` executable) — no conclusion for now. Preliminary judgment: Python as a base is not bad; even if a migration happens later, the functional shape stays roughly the same: Sericite's built-ins are few, and everything else is injected in cooperation with other languages. Either way, a complete prototype must exist as the blueprint before rebuilding it on another base.

## 6. Why the name

Sericite (绢云母) is the finest-grained member of the mica family: thin silky scales that stack into sheets, every sheet still a complete layer, and an insulator like every mica. The name states three of the language's design promises: layering, insulation, lightness.

- **Layering**: sericite scales stack sheet upon sheet, and every sheet is still a complete layer. This mirrors the goal of nested virtualization.
- **Insulation**: like every mica, sericite is an electrical insulator; layers do not conduct into each other. This mirrors the goal of isolation.
- **Lightness**: the finest scales of the mica family — light and transparent. This mirrors the goals of "very low cost" and "imperceptible nesting".

A note: the project was briefly named Mica/MicaLang. It was renamed after discovering the name was occupied multiple times over, including an actively developed commercial language publishing Docker images under the `micalang` namespace. The repository and package name is `sericite`.

## 7. One-sentence summary

Sericite borrows Python's syntax shell to do something Python cannot: **make "creating a fully isolated universe" an ordinary script statement, cheap enough to use casually, nestable layer upon layer, with layers unaware of each other.** It is a language whose central proposition is "user-space virtualization", not an accessory tool for LLMs — the LLM era merely made the problem it solves more conspicuous.
