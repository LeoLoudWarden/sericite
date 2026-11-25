# Scripting Manual

This section collects the manual for the Sericite scripting language, including task-organized guides and an API reference organized by query object.

When learning the language for the first time, start with the [scripting guide](guides/01-quick-start.md). The guides organize examples and explanations by task; the API reference organizes precise contracts by query object. The two do not replace each other.

## Guides

| Page | Contents |
|---|---|
| [Quick start](guides/01-quick-start.md) | Basic types, operations, assignment, functions, closures, decorators |
| [Modules and capability extension](guides/02-modules.md) | Module and relative imports, the capability-extension entry `__addon__` |
| [Custom record objects](guides/03-record.md) | Records and schemas, contracts and annotations, width checks, structural equality |
| [Error handling](guides/04-errors.md) | Catching and raising, error records, static filters |
| [File system](guides/05-files.md) | File and directory operations, path resolution, implicit and explicit directories |
| [Isolated execution spaces](guides/06-vm.md) | Run source as an independent program, provide files, grant capabilities, and control execution |
| [Safety notes](guides/07-vm-safety.md) | Environment isolation, execution limits, common bad habits |

## API reference

| Page | Contents |
|---|---|
| [Language and modules](reference/01-language.md) | Values, operations, assignment, control flow, functions, records/schemas, f-strings, modules, `__addon__` |
| [General built-ins](reference/02-builtins.md) | `input`, `print`, conversions, rendering, `range`, `wrap`, `unwrap` |
| [Value type methods](reference/03-types.md) | All public methods of `list`, `tuple`, `dict`, `str` |
| [Files and directories](reference/04-files.md) | Common path and directory rules, the 11 file and directory interfaces |
| [Errors and exceptions](reference/05-errors.md) | Catching and raising, exception records, all error kinds, the fixed filter groups |
| [VM](reference/06-vm.md) | VM construction, states, driving, debugging, snapshots, quotas, and addon granting |
| [VFS](reference/07-vfs.md) | Detached workspaces, exclusive transfer, and VFS file methods |

## Signature notation

The signatures in the reference describe the script call contract, not Python type-annotation syntax:

```text
function(required, optional=default) -> ReturnType
object.method(argument) -> ReturnType
```

- The right side of `->` is the return type or return-value category.
- `any` means any script value, not Python's `typing.Any` object.
- `A | B` means the return value is one of `A` or `B`; for example, `any | None` means the function may return any value or `None`.
- Optional parameters show their defaults; multiple call forms are listed on separate lines.
- In the built-ins pages, `*` means the following parameters must be passed by keyword. `*args` and `**kwargs` in user functions are variadic parameters; see [functions](reference/01-language.md#functions).
- `list`, `dict`, and `tuple` mean the corresponding built-in containers; more specific element types are described in the prose when needed.
- The documentation only promises the parameter names and call forms listed here; it does not bring other forms of a same-named Python API into Sericite.

## Contents agreement

- Common rules are expanded in full only on their authoritative page. For example, file path rules are on the files page, and the VFS page only lists the same-named methods and links over.
- Each public interface lists the parameters, returns, and main errors needed to use it; general possibilities such as resource exhaustion are covered centrally on the VM and errors pages.
- Code blocks in the examples use the `python` marker only for syntax highlighting; the language is still Sericite.
