# Input, output, and error diagnostics

The command line connects the entry program's virtual input and output to the host's standard streams: script `input()` reads stdin, `print()` writes stdout, and errors the script does not handle are written to stderr.

## Reading data from standard input

Create `greet.sericite`:

```python
name = input()
print("hello", name)
```

When run directly, `input()` waits for you to type a line; you can also provide data through a pipe or redirection:

```bash
printf 'world\n' | sericite greet.sericite
```

Expected output:

```text
hello world
```

`input()` reads one line at a time and strips the trailing newline. Reading after the input is exhausted raises a catchable `input_error`, so you can process line by line until EOF:

```python
lines = []

while True:
    try:
        lines.append(input())
    except input_error:
        break

print(lines)
```

If this error is not caught, a one-shot program prints a diagnostic and exits with status code 1; the REPL shows the error and keeps waiting for the next command.

### Don't confuse source input with data input

The following `-` means read the complete program from stdin:

```bash
printf 'print("hello")\n' | sericite -
```

The command line first reads to EOF and only then starts executing. So `input()` in this source cannot read further data from the same stdin.

When you need to provide both source and data, choose one of these approaches:

- save the source to a file and leave stdin to `input()`;
- provide the source with `-c` and leave stdin to `input()`;
- provide data that works better as files through the addon `files`.

REPL command entry and script `input()` share stdin. After interactively entering a command that calls `input()`, the next line is consumed as data for that script call first, not as a new REPL command.

## Standard output

Every entry-program `print()` writes to stdout immediately and flushes, including unterminated output with `end=""`. Callers can receive output before the program finishes, without waiting for the process to exit.

```bash
sericite -c 'print("first", end=""); input(); print("second")'
```

`first` is already written before you enter a line of data.

## Reading error diagnostics

Create `error.sericite`:

```python
def divide():
    return 1 / 0

divide()
```

After running, stdout does not contain this error; stderr is:

```text
error.sericite:2: zero_division: division by zero
Traceback (most recent call last):
  File "error.sericite", line 4, in <module>
  File "error.sericite", line 2, in divide
```

The first line gives the error location, error kind, and message. The call stack points from the caller to the actual error point, and each frame uses the source location that defines that code. For the names of different source entries and the special form of startup errors, see the [CLI reference](../reference/01-cli.md#error-diagnostics).

Content already written to stdout before the program failed is not lost because of a later error. Shell pipes only merge or separate standard streams; they do not change Sericite's internal error-catching rules. For exception handling, see [script error handling](../../scripting/guides/04-errors.md).

## Exit codes

Automation scripts can use the process exit code to judge whether a command finished: 0 means normal completion, and other values mean there is a problem with startup, execution, or command-line usage. An ordinary single-entry error in the REPL does not end the session and does not by itself produce a non-zero exit code.

To distinguish specific failure categories or handle a closed pipe, see the [CLI reference's exit codes](../reference/01-cli.md#exit-codes).
