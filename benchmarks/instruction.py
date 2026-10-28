"""Benchmark: average cost of executing one Sericite instruction.

Measures a fixed counting loop and divides run() wall time by the actual
instruction_count reported by the engine. VM creation and compilation happen
before timing starts. This is a workload-weighted average across the opcodes
used by the loop, not a claim that every opcode has the same cost.

Usage:

    uv sync
    uv run python benchmarks/instruction.py

The engine has zero runtime dependencies; the script itself is stdlib-only.
Numbers are medians; absolute values vary with hardware and Python version.

Recorded run (2026-10-23, Intel i3-9100, CPython 3.13.13, Linux x86_64;
20,000 loop iterations = 180,008 instructions, 9 timed samples):

    run                ~0.65 µs/instruction

For the current cross-benchmark table (2026-10-26), see docs/architecture.md §6.
"""

from __future__ import annotations

import statistics
import sys
import time
from collections.abc import Callable

from sericite import SericiteEngine, SericiteLimits, VMHandle

N_ITERATIONS = 20_000
SOURCE = f"i = 0\nwhile i < {N_ITERATIONS}:\n    i = i + 1\n"
LIMITS = SericiteLimits(max_instructions=100_000_000)


def measure(fn: Callable[[VMHandle], None], reps: int) -> tuple[float, int]:
    """Median timed wall time in nanoseconds and the executed instruction count."""
    samples = []
    counts = []
    for _ in range(reps):
        vm = SericiteEngine(limits=LIMITS).create_root(SOURCE)
        t0 = time.perf_counter_ns()
        fn(vm)
        samples.append(time.perf_counter_ns() - t0)
        snapshot = vm.snapshot()
        assert snapshot["state"] == "done"
        counts.append(snapshot["instruction_count"])
    assert len(set(counts)) == 1 and counts[0] > 0
    return statistics.median(samples), counts[0]


def main() -> None:
    def run(vm: VMHandle) -> None:
        vm.run()

    run(vm=SericiteEngine(limits=LIMITS).create_root(SOURCE))
    elapsed_ns, instruction_count = measure(run, 9)
    us_per_instruction = elapsed_ns / instruction_count / 1e3

    print(f"Python {sys.version.split()[0]} on {sys.platform}")
    print(f"workload             {instruction_count:10d} instructions")
    print(f"run                  {us_per_instruction:10.3f} µs/instruction")


if __name__ == "__main__":
    main()
