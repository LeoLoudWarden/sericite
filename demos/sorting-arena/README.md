# sorting-arena: an untrusted-code sorting tournament

[中文](README.zh-CN.md)

Nine mutually untrusted Sericite programs enter a judging arena. Three sorting algorithms compete on instruction count; six troublemakers fail in different ways. The judge keeps running while only the current submission is eliminated.

This is a complete application with no LLM, network access, or third-party dependencies. It highlights a different side of the project from `root-agent`: **isolation not only contains untrusted code, but also turns its execution into a measurable competition with enforceable elimination.**

## Run

From the repository root:

```bash
uv run sericite \
  --capabilities demos/sorting-arena/capabilities.py \
  demos/sorting-arena/arena.sericite
```

The output shows each submission's trial runs followed by the final scoreboard. Every startup generates new problems, so scores and rankings can change. This is one actual run; instruction counts are engine accounting, not elapsed time:

```text
╭─ FINAL STANDINGS ────────────────────────────────────────────────────╮
  RANK  CONTESTANT                  TOTAL INSTRUCTIONS
  1     quicksort               12,028
  2     insertion-sort          20,815
  3     bubble-sort             41,352
  DQ    wrong-answer            wrong_answer
  DQ    answer-thief            file_not_found
  DQ    output-flood            resource_exhausted
  DQ    infinite-loop           resource_exhausted
  DQ    vm-spawner              resource_exhausted
  DQ    input                   input_error
╰──────────────────────────────────────────────────────────────────────╯
  The arena survived every submission. The scoreboard only counts correct code.
```

## Rules

Each entry is a complete, standalone Sericite program:

1. Read whitespace-separated integers from `/input.txt`.
2. Write the ascending result to `/output.txt`, separated by whitespace.
3. Pass all four test cases to qualify. The score is the sum of `instruction_count` across those cases; any failure eliminates the entry.

Every test case starts a fresh child VM with only `/input.txt` preloaded. The expected answer stays in the judge's world. Entries receive no functions and no output forwarding, and no mutable state is shared between entries; see the [security model](../../docs/security.md) §2 for the rest of the isolation boundary.

An entry that calls `input()` is eliminated with `input_error` while waiting for input, even if it already wrote an answer.

Failures fall into a few categories:

| Failure | Example entries | Result |
|---|---|---|
| Wrong answer | `wrong-answer` | Disqualified |
| Inaccessible file | `answer-thief` | `file_not_found` |
| Exhausted quota | `output-flood`, `infinite-loop`, `vm-spawner` | `resource_exhausted` |
| Unavailable input | `input` | `input_error` |

Three normal sorting algorithms in `entries/` are ranked only if they pass every case. Correctness comes before instruction-count ranking: finishing is not the same as being correct.

## How Python randomness reaches the judge

Sericite has no built-in random number generator. `capabilities.py` wraps Python's `random.randrange(below)` as `random_int(below)` and explicitly grants it to the root judge through `functions`. On every startup, `arena.sericite` builds four problem types, each with 24 integers:

- `mixed`: random integers from 0 to 99;
- `reversed`: random integers, sorted and then reversed;
- `nearly sorted`: random sorted data with four randomly selected pairs swapped;
- `duplicates`: random integers from 0 to 9, producing many repeated values.

`nearly sorted` makes 8 extra `random_int` calls to choose the swap positions.

Only root receives `random_int`; entry VMs are created without `functions`, so contestants cannot call it. See the [VM reference](../../docs/vm-reference.md) §6 for why grants do not cross VM layers automatically.

The main per-case limits are (see `run_case()` in `arena.sericite` for the full set, and the [VM reference](../../docs/vm-reference.md) §5 for field semantics):

| Limit | Value | Role in this demo |
|---|---:|---|
| `max_instructions` | 120,000 | Bounds the instruction count of an infinite loop |
| `max_output_bytes` | 512 | Stops output floods |
| `max_child_vms` | 0 | Prevents entries from spawning VMs |
| `max_frames` | 64 | Bounds call depth |
| `max_total_bytes` | 1 MiB (approximate accounting) | Bounds memory growth |

## Add a contestant

Drop another `.sericite` file into `entries/`, for example `10-my-sort.sericite`.

Startup seeds entries in filename order; the judge removes the first three characters and the extension for display. A three-digit prefix is therefore a convenient way to control running order.

Neither `capabilities.py` nor `arena.sericite` needs to change. Try a faster algorithm or a new troublemaker and watch the judge finish the tournament.

## Files and trust boundaries

- `arena.sericite`: all application logic—test data, reference answers, VM lifecycle, correctness checks, scoring, and the scoreboard.
- `capabilities.py`: a thin trusted startup layer. It reads `entries/*.sericite` from this directory, places them in the root VFS as **text**, grants `random_int` to root, and raises the trusted root's total instruction budget. It never executes an entry.
- `entries/`: simulated submissions from an untrusted source, including valid algorithms and deliberately disruptive programs.

Entries are Sericite, not Python, and never pass through `exec`/`eval`. When running genuinely adversarial code, still add an OS-level boundary outside the engine; see the [security model](../../docs/security.md) for the complete boundary.
