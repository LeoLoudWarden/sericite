# Prior art and related work

Sericite does not claim that in-language isolation is a new idea. It claims the idea was proven once, abandoned unfinished for historical reasons, and is now worth completing. ([中文](prior-art.zh-CN.md))

## Safe-Tcl: the direct ancestor

Tcl has had safe interpreters as a language built-in since Tcl 7.5 (released 1996-04-21), descending from the Safe-Tcl prototype implemented by Nathaniel Borenstein and Marshall Rose in 1992. The prototype was built for "active email": code arriving over a channel — an email message — to be executed locally in a restricted interpreter. That is the same problem shape as today's LLM tool calls: code arrives over a channel (model output) and must execute locally without being trusted.

The mechanism, as built into Tcl:

- A safe interpreter starts with the dangerous commands disabled or removed (file access, `exec`, sockets, …) — zero capabilities by default.
- The master grants mediated capabilities back through **aliases**: commands visible in the slave that execute in the master's context. The Tcl manual describes this as "protected communication (analogous to a kernel call) between a slave interpreter and its master".
- Any slave can itself create further slaves, for which it is the master, "resulting in a hierarchy of interpreters"; a slave created by a safe interpreter is automatically safe. Recursive nesting of distrust is native to the design.

Where Safe-Tcl stopped — in its own words:

- The 1998 USENIX security-model paper (Levy, Demailly, Ousterhout, Welch) states: "Safe-Tcl currently does not prevent most denial-of-service attacks. We will address this in the future with a combination of resource controls and a kill-key that lets a user intervene when an applet misbehaves."
- Resource controls arrived only in Tcl 8.5 via TIP 143 (2003), whose rationale concedes that "it is trivial for scripts running in even safe Tcl interpreters to conduct a denial-of-service attack". TIP 143 added exactly two kinds of limit — wall-clock time and command count — per individual interpreter. Memory limits were explicitly deferred as too expensive; output accounting does not exist. And nothing is charged upward: a limited interpreter's children inherit the time limit but get a fresh command budget — the TIP merely suggests a master "might want to" deduct quotas itself.
- The kill-key arrived even later: `interp cancel` via TIP 285, in Tcl 8.6.

So the historical record is: the isolation mechanism was sound and shipped in 1996; the resource-governance half was promised in 1998, delivered partially a decade later, and never delivered as a hierarchy-wide accounting model. Meanwhile the mechanism earned outside recognition: NIST's *Countermeasures for Mobile Agent Security* (2000) calls Safe Tcl "probably the best known of the safe interpreters for script-based languages". The alternative mainstream approach — Java's SecurityManager — was deprecated for removal (JEP 411, JDK 17) and permanently disabled (JEP 486, JDK 24).

Safe-Tcl did not die because the mechanism lost. It faded with its host language's ecosystem. The padded cell lost nothing; Tcl lost the market.

## Comparison

| | Safe-Tcl (1992/1996) | Starlark | WASM runtimes | Sericite |
|---|---|---|---|---|
| Isolation is a language-level statement | yes (`interp create -safe`) | no (embedding API) | no (external runtime) | yes (`VM(...)`) |
| Recursive nesting of isolated worlds | yes (children of safe interps are safe) | no | host-mediated | yes |
| Capability granting to children | yes (aliases) | partial (globals injection) | yes (host imports) | yes (FFI, pure-data deep copy both ways) |
| Resource quotas | none until Tcl 8.5; then time + command count only, per interpreter, no ancestor accounting | implementation-specific (starlark-go: configurable step limit) | engine-specific (fuel/metering, not spec-level) | instructions, memory, output, files, children, depth; tighten-only; a child's consumption charged to all ancestors |
| Parent-side introspection of a running child | none (`interp cancel` only, 8.6) | none | engine-specific | step / step_instruction / snapshot / terminate |
| Hermetic, deterministic core | no | yes (a core goal) | yes | no (I/O and files are the point, via explicit grants) |

What Sericite takes from Safe-Tcl: the padded-cell model, zero-default capabilities, granting as the only path to power, and nesting as the natural shape of distrust.

What Sericite adds that Safe-Tcl never had: the quota tree (tighten-only, charged to all ancestors), and treatment of a running child as a debuggable, snapshot-able object rather than a black box.

What Sericite explicitly does not inherit: Safe-Tcl's premise that the host interpreter implementation is trustworthy. See the [security model](security.md) — Sericite-PY runs in the host process and is not your only boundary.

## Sources

- Levy, Demailly, Ousterhout, Welch, "The Safe-Tcl Security Model", USENIX Annual Technical Conference, 1998. <https://www.usenix.org/publications/library/proceedings/usenix98/full_papers/levy/levy.pdf>
- Borenstein, "Email with a Mind of Its Own: The Safe-Tcl Language for Enabled Mail", IFIP WG 6.5, 1994. <http://guppylake.com/pubs/ulpaa-94.pdf>
- Tcl 7.5 release notes (1996-04-21). <https://www.tcl-lang.org/software/tcltk/7.5.html>
- Tcl `interp` manual (safe interpreters, aliases, hierarchy). <https://www.tcl-lang.org/man/tcl8.6/TclCmd/interp.htm>
- TIP 143, "Resource Limits for Tcl Interpreters" (Tcl 8.5). <https://core.tcl-lang.org/tips/doc/trunk/tip/143.md>
- TIP 285, "Script Cancellation with [interp cancel]" (Tcl 8.6). <https://core.tcl-lang.org/tips/doc/trunk/tip/285.md>
- Jansen (NIST), "Countermeasures for Mobile Agent Security", Computer Communications 23(17), 2000. <https://csrc.nist.gov/csrc/media/projects/mobile-security-and-forensics/documents/mobile_agents/ppcountermeas.pdf>
- JEP 411, "Deprecate the Security Manager for Removal" (JDK 17); Security Manager permanently disabled in JDK 24 (JEP 486). <https://openjdk.org/jeps/411>
- starlark-go `Thread.SetMaxExecutionSteps`. <https://pkg.go.dev/go.starlark.net/starlark>
