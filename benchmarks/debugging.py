"""Benchmark: cost of running versus single-stepping a Sericite VM.

Runs the same fixed counting loop through run(), step_instruction(), and
step(). VM creation and compilation happen before timing starts. Stepping
measurements include both single-step control and the safe snapshot returned
by every step call. The workload has one simple local variable; snapshots of
large or deeply nested values cost more and are outside this benchmark.

Usage:

    uv sync
    uv run python benchmarks/debugging.py

The engine has zero runtime dependencies; the script itself is stdlib-only.
Numbers are medians; absolute values vary with hardware and Python version.

Recorded run (2026-10-23, Intel i3-9100, CPython 3.13.13, Linux x86_64;
20,000 loop iterations = 180,008 instructions, 9 run and 7 stepping samples):

    run                ~0.64 µs/instruction  (1.00x)
    step_instruction   ~1.86 µs/instruction  (2.92x)
    step               ~1.09 µs/instruction  (1.71x)
    step               ~4.91 µs/step call

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


def measure(
    fn: Callable[[VMHandle], int | None], reps: int
) -> tuple[float, int, int | None]:
    """Median wall time in nanoseconds, instruction count, and optional steps."""
    samples = []
    counts = []
    step_counts = []
    for _ in range(reps):
        vm = SericiteEngine(limits=LIMITS).create_root(SOURCE)
        t0 = time.perf_counter_ns()
        steps = fn(vm)
        samples.append(time.perf_counter_ns() - t0)
        snapshot = vm.snapshot()
        assert snapshot["state"] == "done"
        counts.append(snapshot["instruction_count"])
        step_counts.append(steps)
    assert len(set(counts)) == 1 and counts[0] > 0
    assert len(set(step_counts)) == 1
    return statistics.median(samples), counts[0], step_counts[0]


def main() -> None:
    def run(vm: VMHandle) -> None:
        vm.run()

    def step_instructions(vm: VMHandle) -> int:
        steps = 0
        while True:
            snapshot = vm.step_instruction()
            steps += 1
            if snapshot["state"] != "ready":
                assert snapshot["state"] == "done"
                return steps

    def step_statements(vm: VMHandle) -> int:
        steps = 0
        while True:
            snapshot = vm.step()
            steps += 1
            if snapshot["state"] != "ready":
                assert snapshot["state"] == "done"
                return steps

    for driver in (run, step_instructions, step_statements):
        driver(SericiteEngine(limits=LIMITS).create_root(SOURCE))

    run_ns, run_count, _ = measure(run, 9)
    instruction_ns, instruction_count, instruction_steps = measure(step_instructions, 7)
    statement_ns, statement_count, statement_steps = measure(step_statements, 7)
    assert run_count == instruction_count == statement_count
    assert instruction_steps == instruction_count
    assert statement_steps is not None

    run_us = run_ns / run_count / 1e3
    instruction_us = instruction_ns / instruction_count / 1e3
    statement_us_per_instruction = statement_ns / statement_count / 1e3
    statement_us_per_step = statement_ns / statement_steps / 1e3

    print(f"Python {sys.version.split()[0]} on {sys.platform}")
    print(f"workload             {run_count:10d} instructions")
    print(f"run                  {run_us:10.3f} µs/instruction  (1.00x)")
    print(
        f"step_instruction     {instruction_us:10.3f} µs/instruction"
        f"  ({instruction_us / run_us:.2f}x)"
    )
    print(
        f"step                 {statement_us_per_instruction:10.3f} µs/instruction"
        f"  ({statement_us_per_instruction / run_us:.2f}x)"
    )
    print(f"step                 {statement_us_per_step:10.3f} µs/step call")


if __name__ == "__main__":
    main()
