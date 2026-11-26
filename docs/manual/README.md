# Sericite Manual

Project repository: <https://github.com/LeoLoudWarden/sericite>

This manual explains how to write and run Sericite programs, and how to embed the Python reference engine in an existing application. It covers public behavior and usage contracts rather than the project's design history or engine internals.

!!! note "Version note"

    The latest online manual tracks the `main` branch and may differ from the latest PyPI release.

## Choose a manual

| Manual | Intended reader | Contents |
|---|---|---|
| [Scripting manual](scripting/README.md) | Sericite script authors | Language, built-ins, records, errors, files, VMs, and VFSs |
| [CLI manual](cli/README.md) | Program operators | Commands, projects, trusted addons, standard IO, and exit codes |
| [Python host manual](host-python/README.md) | Python embedders | Engine API, VM lifecycle, workspaces, addons, debugging, and observation |

The scripting manual can be read independently. Read the CLI manual to run programs from a terminal, or the Python host manual to create and control VMs from Python.

The current Python reference implementation requires Python 3.12 or later and has no third-party runtime dependencies:

```bash
pip install sericite
```

## Guides and API references

Each manual contains two kinds of pages:

- **Guides** organize examples and explanations around tasks. Start here when learning a workflow.
- **API references** define parameters, return values, errors, and other precise contracts. Use them to look up a specific interface.

The guides do not replace the references, and the references do not repeat every introductory example.

## Safety essentials

Sericite is designed for isolation, but the current prototype requires careful deployment:

- The Python engine runs in the host process and has not undergone a formal external security audit. For genuinely adversarial code, do not use Sericite as the only isolation boundary; add independent process, container, or other operating-system-level isolation.
- Default limits are intended for development and debugging, not as safety recommendations. Set explicit limits for code that is not fully trusted.
- CLI addon files and Python host callbacks are trusted code outside the sandbox. Their argument validation, CPU, memory, blocking, external effects, and secret protection are the host's responsibility.
- Grant only the capabilities a program needs. A granted function may expose state and capabilities available in its defining environment, not merely a function name.

For examples of isolation, limits, and capability granting, see the [scripting safety guide](scripting/guides/07-vm-safety.md), [CLI addon guide](cli/guides/03-addons.md), and [Python addon guide](host-python/guides/03-addons.md).
