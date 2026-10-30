# sericite-debugger: a debugger can be debugged

[中文](README.zh-CN.md)

This is an interactive debugger written in Sericite. It accepts **Sericite source code, that program's input, and its target argv**, creates a child VM from the source, and drives it by statement or instruction; it does not load preset target files.

Any source can be the target, including this debugger itself. The complete self-reference form is **D(D(P))**; see “Self-reference” below for the walkthrough.

## Input protocol

```text
debugger.sericite SOURCE [INPUT] [TARGET_ARG ...]
```

| Argument | Meaning |
|---|---|
| `SOURCE` | Complete Sericite source string, not a filename |
| `INPUT` | Optional multiline stdin preloaded into the target VM |
| `TARGET_ARG` | Arguments used to construct the target program's argv explicitly |

A child VM does not inherit its parent's argv (see the [CLI reference](../../docs/cli-reference.md) §2). The debugger therefore prepends an explicit `argv = [...]` line to the target source.

The panel shows this line too, so displayed line numbers match the executing target exactly.

## Debug code passed directly on the command line

```bash
PROGRAM=$'name = input()\nprint("hello", name)'

uv run sericite demos/sericite-debugger/debugger.sericite \
  "$PROGRAM" 'Sericite'
```

Enter `r` at the debugger prompt. The target consumes the preloaded `Sericite` input and prints:

```text
hello Sericite
session ended · done
```

You can also omit `INPUT`. When the target enters `waiting_input`, the outer debugger shows a `[child stdin]` prompt; entering one line forwards it with `feed_input()`.

The target's input channel and the outer debugger's command channel remain distinct.

## Watchpoints and error scenes

This program violates a runtime record contract on its last field write:

```bash
PROGRAM=$(cat <<'EOF'
class Account:
    balance: int

account = Account(100)
deposit = 40
account.balance = account.balance + deposit
print("after deposit", account)
account.balance = "unlimited"
EOF
)

uv run sericite demos/sericite-debugger/debugger.sericite "$PROGRAM"
```

Enter:

```text
w account
c
c
c
```

The first `c` stops when `account` appears, the second when its balance changes from 100 to 140, and the third reaches the contract error:

```text
◆ watchpoint hit · account
  before: {'<record>': {'balance': 100}}
  after:  {'<record>': {'balance': 140}}
```

The final panel marks the error line with `!` and preserves three kinds of context:

- current-frame `locals`;
- target stdout;
- the safe error view.

```text
│ !   9  account.balance = "unlimited"
│ contract_error: field balance: expected int, got str
│ <module>:9
session ended · error
```

## Self-reference: D(D(P))

Pass the debugger source to the outer debugger, then tell the inner debugger to debug another program:

```bash
DEBUGGER="$(cat demos/sericite-debugger/debugger.sericite)"
PROGRAM=$'name = input()\nprint("hello", name)'

uv run sericite demos/sericite-debugger/debugger.sericite \
  "$DEBUGGER" \
  $'r\n' \
  "$PROGRAM" \
  $'Sericite\n'
```

Enter `r` at the outer prompt. The four arguments are:

1. Outer target: the inner debugger D's source;
2. Inner D's stdin: the command `r`;
3. Inner D's target: the ordinary program P's source;
4. P's stdin: `Sericite`.

This creates two levels of control:

```text
outer debugger
  └─ inner debugger
       └─ name = input()
          print("hello", name)
```

The outer debugger eventually sees the tail of the inner debugger's isolated stdout:

```text
│ │ hello Sericite
│ ╰──────────────────────────────────────────────────────────────────────╯
│ session ended · done
session ended · done
```

The outer debugger can inspect the inner one's safe snapshot, but cannot reach through it to obtain the innermost VM handle. Control can recurse while visibility boundaries remain; see the [VM reference](../../docs/vm-reference.md) §4 for why snapshots do not carry child VM handles.

## Commands

| Input | Action |
|---|---|
| Enter | `step()`—execute one source statement |
| `i` | `step_instruction()`—execute one internal instruction |
| `c` | With a watchpoint: continue by instruction until a hit, input wait, or terminal state. Without one: `run()` |
| `w NAME` | Watch a current-frame local; pause when it appears, leaves the frame, or changes |
| `w off` | Disable the watchpoint |
| `r` | `run()` without checking watchpoints |
| `q` | `terminate()` the target VM |
| `h` | Show help |

Statement stepping treats a function call as one statement; instruction stepping can enter the function (see the [VM reference](../../docs/vm-reference.md) §4).

The target VM has a 20,000-instruction quota. Long sources show only a window around the current position instead of repeatedly printing the entire debugger source.

The current snapshot API does not expose opcode names or operands, so `i` shows source positions and state after each internal instruction, not disassembly. See the [VM reference](../../docs/vm-reference.md) §4 for the full snapshot fields and limits.

## Files and dependencies

- `debugger.sericite`: the only program file, containing the input protocol, watchpoints, VM driving, and rendering.
- `tests/test_sericite_debugger.py`: real CLI tests, including the complete D(D(P)) chain.

The demo needs no Python capabilities, target-file directory, network, LLM, or third-party dependency.

Shell variables in the commands only place source text into argv; they do not participate in executing Sericite code.
