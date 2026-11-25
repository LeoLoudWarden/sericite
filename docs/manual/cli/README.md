# CLI Manual

This section collects the usage guide for the `sericite` command line, for operators who run Sericite programs directly, prepare project files, and configure the runtime environment.

The guides organize examples and explanations by task; the complete command-line options, configuration fields, and exit behavior are listed together in the [CLI reference](reference/01-cli.md). To write the scripts themselves, see the [scripting manual](../scripting/README.md); to manage VM lifecycles inside your own Python program, use the embedding API directly instead of extending the CLI configuration.

## Guides

| Page | Contents |
|---|---|
| [Running programs](guides/01-running-programs.md) | Run source files and command strings, pass script arguments, use the REPL |
| [Running multi-file projects](guides/02-projects.md) | Start a project from an entry file, understand how project sources enter the virtual file system |
| [Configuring addons](guides/03-addons.md) | Grant functions, preset files, and set execution limits with a trusted Python file |
| [Input, output, and error diagnostics](guides/04-io-and-diagnostics.md) | Use standard input and output, read diagnostics, handle exit codes |

When using the command line for the first time, reading the first two guides in order is enough to run common single-file and multi-file programs. You only need to write an addon configuration when you need host capabilities, initial files, or custom quotas.

## Reference

| Page | Contents |
|---|---|
| [CLI reference](reference/01-cli.md) | Command-line options, project loading, addon configuration, the REPL, standard streams, diagnostics, and exit codes |
