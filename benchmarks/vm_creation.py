"""Benchmark: how cheap is creating a Sericite VM?

Measures the four paths that matter for the "cheap, nestable isolation"
claim, plus OS-level reference points for comparison:

  host_create      SericiteEngine.create_root(src)   — compile + context
  host_create_run  create_root(src) + vm.run()       — full host-side flow
  script_create    VM(code) from inside a script     — what user code pays
  script_run       VM(code) + sub.run() from a script

  ref_thread       threading.Thread start+join
  ref_fork         os.fork + waitpid (POSIX only)
  ref_proc_true    subprocess run of /bin/true
  ref_proc_python  subprocess run of `python -c pass`

Usage:

    uv sync
    uv run python benchmarks/vm_creation.py

The engine has zero runtime dependencies; the script itself is stdlib-only.
Numbers below are medians; absolute values vary with hardware and Python
version, the order-of-magnitude comparison is the point.

Recorded run (2026-10-23, Intel i3-9100, CPython 3.13/3.14, Linux x86_64):

    host_create        ~37 µs/VM
    host_create_run    ~42 µs/VM
    script_create      ~50 µs/VM
    script_run         ~64 µs/VM
    ref_thread         ~70 µs
    ref_fork           ~1.9 ms
    ref_proc_true      ~0.55 ms
    ref_proc_python    ~12.9 ms

For the current cross-benchmark table (2026-10-26), see docs/architecture.md §6.

An independent reproduction on different hardware measured script_create
~0.11 ms and host_create_run ~0.33 ms — same order of magnitude.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from sericite import SericiteEngine, SericiteLimits

N_HOST = 2000  # VMs per host-side sample
N_SCRIPT = 1000  # child VMs per script-side sample
SOURCE = "x = 1"  # minimal non-empty program


def bench(fn: Callable[[], None], reps: int) -> float:
    """Median wall time of fn() over reps, in nanoseconds."""
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t0)
    return statistics.median(samples)


def main() -> None:
    script_limits = SericiteLimits(
        max_instructions=100_000_000,
        max_child_vms=N_SCRIPT + 100,
        max_total_vms=N_SCRIPT + 100,
    )
    host_limits = SericiteLimits(max_total_vms=N_HOST + 100)

    results: list[tuple[str, float]] = []  # (label, µs per unit)

    # Warm-up
    for _ in range(50):
        SericiteEngine().create_root(SOURCE).run()

    def host_create() -> None:
        engine = SericiteEngine(limits=host_limits)
        for _ in range(N_HOST):
            engine.create_root(SOURCE)

    def host_create_run() -> None:
        engine = SericiteEngine(limits=host_limits)
        for _ in range(N_HOST):
            engine.create_root(SOURCE).run()

    results.append(("host_create", bench(host_create, 7) / N_HOST / 1e3))
    results.append(("host_create_run", bench(host_create_run, 7) / N_HOST / 1e3))

    loop = f'code = "{SOURCE}"\nfor i in range({N_SCRIPT}):\n'
    script_create_src = loop + "    sub = VM(code)\n"
    script_run_src = loop + "    sub = VM(code)\n    sub.run()\n"

    # Warm-up
    SericiteEngine().create_root(script_create_src, limits=script_limits).run()

    def script_create() -> None:
        SericiteEngine().create_root(script_create_src, limits=script_limits).run()

    def script_run() -> None:
        SericiteEngine().create_root(script_run_src, limits=script_limits).run()

    results.append(("script_create", bench(script_create, 5) / N_SCRIPT / 1e3))
    results.append(("script_run", bench(script_run, 5) / N_SCRIPT / 1e3))

    def ref_thread() -> None:
        for _ in range(2000):
            th = threading.Thread(target=lambda: None)
            th.start()
            th.join()

    results.append(("ref_thread", bench(ref_thread, 3) / 2000 / 1e3))

    if hasattr(os, "fork"):

        def ref_fork() -> None:
            for _ in range(200):
                pid = os.fork()
                if pid == 0:
                    os._exit(0)
                os.waitpid(pid, 0)

        results.append(("ref_fork", bench(ref_fork, 3) / 200 / 1e3))

    def ref_proc_true() -> None:
        for _ in range(100):
            subprocess.run(["/bin/true"], check=True)

    def ref_proc_python() -> None:
        for _ in range(20):
            subprocess.run([sys.executable, "-c", "pass"], check=True)

    if os.path.exists("/bin/true"):
        results.append(("ref_proc_true", bench(ref_proc_true, 3) / 100 / 1e3))
    results.append(("ref_proc_python", bench(ref_proc_python, 3) / 20 / 1e3))

    print(f"Python {sys.version.split()[0]} on {sys.platform}")
    for label, us in results:
        print(f"{label:<16} {us:10.1f} µs")


if __name__ == "__main__":
    main()
