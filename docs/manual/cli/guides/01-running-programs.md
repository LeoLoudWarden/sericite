# Running programs

The `sericite` command can run Sericite source directly, or open an interactive session that keeps state across entries.

After installing the distribution, the command is named `sericite`:

```bash
pip install sericite
```

When developing in a source checkout, use `uv run sericite` instead. `python -m sericite` shares the same command-line behavior as `sericite`.

## Running source files

Create `hello.sericite`:

```python
print("hello from Sericite")
```

Run it:

```bash
sericite hello.sericite
```

Expected output:

```text
hello from Sericite
```

Source files are read as UTF-8. `.sericite` is a conventional suffix; the command line does not enforce it.

## Executing a command string directly

Short programs can be given directly with `-c` or `--command`:

```bash
sericite -c 'print(6 * 7)'
```

Expected output:

```text
42
```

You can also read a complete program from standard input, using a single `-` as the entry:

```bash
printf 'print("hello from stdin")\n' | sericite -
```

This reads all of standard input before executing the source. When the program needs to read data while it runs, see [Don't confuse source input with data input](04-io-and-diagnostics.md#dont-confuse-source-input-with-data-input).

## Passing script arguments

Everything after the entry is passed to the script and no longer interpreted by the command line. Create `args.sericite`:

```python
print(argv)
```

Run it:

```bash
sericite args.sericite first --flag
```

Expected output:

```text
['args.sericite', 'first', '--flag']
```

`argv` is a list of strings. Its first item identifies the entry; the remaining items are the script arguments. A file entry keeps the path exactly as you wrote it; a `-c` entry starts with `"-c"`, and a stdin entry starts with `"-"`.

```bash
sericite -c 'print(argv)' first --flag
```

Expected output:

```text
['-c', 'first', '--flag']
```

A script can therefore implement its own argument conventions such as `--flag`. Even a standalone `--` enters `argv` verbatim as long as it appears after the entry.

The command line's own options must come before the entry. To end CLI options explicitly, write `--` before the entry; this `--` is consumed by the command line and does not enter `argv`.

## Using the REPL

With no source file and no `-c`, the command line enters the REPL:

```text
>>> x = 40
>>> x + 2
42
>>> write_file("/note.txt", "saved")
>>> read_file("/note.txt")
'saved'
```

`>>>` means a new entry is expected, and `...` means a multiline statement is not yet complete. A single expression echoes a non-`None` result with `repr`; other statements such as assignments show only their own output.

Every entry runs in the same VM session, so variables, functions, schemas, imported modules, and virtual files all persist. When an entry has a compile or runtime error, the error is written to stderr and you can keep typing; the session state that was already established is not rebuilt because of that one error.

Sending EOF exits the REPL normally.

## Next steps

- When source is split across files, read [Running multi-file projects](02-projects.md).
- When a program needs host functions, initial files, or custom quotas, read [Configuring addons](03-addons.md).
- Script syntax and language built-ins are outside the command-line tutorial; see the [scripting quick start](../../scripting/guides/01-quick-start.md).
- To check the complete options and session behavior, see the [CLI reference](../reference/01-cli.md).
