# VFS

VFS 是纯文本内存工作区句柄。`VFS()` 创建一个与 VM 分离的工作区，可预先写入文件，再排他移交给某 VM；VM 终态后可取回工作区继续读取。

文件路径、方法参数、返回和文件错误统一见[文件与目录](04-files.zh-CN.md)。

## 构造

```text
VFS() -> VFS
```

创建空的分离工作区。根目录 `/` 始终存在。构造不接受参数。

## 所有权与生命周期

VFS 句柄处于以下三种状态之一：

| 状态 | 含义 | 能否调用文件方法 |
|---|---|---|
| 分离 | 尚未依附 VM，也未被旧句柄消费 | 可以 |
| 依附 | 已由某台 VM 独占 | 不可以，由该 VM 的文件内建访问 |
| 已消费 | 旧句柄已在成功创建 VM 时失效 | 不可以 |

一个 VFS 在任意时刻最多依附一台 VM，不共享写权限。移交的是文件树，不包括模块缓存、输入输出、局部变量、模块解析根或执行账。

### 移入 VM

```text
VM(source, fs=workspace) -> VM
VM(entry_file=path, fs=workspace) -> VM
```

`fs` 必须是有效的分离 VFS。创建全部成功后，工作区依附新 VM，原句柄永久变为已消费状态。之后使用原句柄报 `runtime_error`。

创建失败不会消费 VFS：源码或入口编译失败、入口读取失败、配额检查失败等情况下，工作区仍归原分离句柄所有。`entry_file` 必须显式配合 `fs` 使用。

### 从 VM 取回

```text
vm.take_fs() -> VFS
```

返回一个新的分离句柄，原 VM 失去文件访问能力且不再接受 `exec()`。只能从 `done`、`error`、`resource_exhausted` 或 `terminated` 状态的 VM 取出 VFS。

取出失败时所有权不变。取出后可以销毁原 VM，不影响已分离的 VFS。完整目标状态约束见 [`VM.take_fs`](06-vm.zh-CN.md#vmtake_fs)。

## 文件方法

以下方法只能在分离且未消费的句柄上调用：

| 方法 | 返回 | 详细契约 |
|---|---|---|
| `vfs.read_file(path)` | `str` | [`read_file`](04-files.zh-CN.md#read_file) |
| `vfs.write_file(path, text)` | `None` | [`write_file`](04-files.zh-CN.md#write_file) |
| `vfs.delete_file(path)` | `None` | [`delete_file`](04-files.zh-CN.md#delete_file) |
| `vfs.rename_file(old_path, new_path)` | `None` | [`rename_file`](04-files.zh-CN.md#rename_file) |
| `vfs.copy_file(source_path, destination_path)` | `None` | [`copy_file`](04-files.zh-CN.md#copy_file) |
| `vfs.make_dir(path)` | `None` | [`make_dir`](04-files.zh-CN.md#make_dir) |
| `vfs.delete_dir(path)` | `None` | [`delete_dir`](04-files.zh-CN.md#delete_dir) |
| `vfs.rename_dir(old_path, new_path)` | `None` | [`rename_dir`](04-files.zh-CN.md#rename_dir) |
| `vfs.copy_dir(source_path, destination_path)` | `None` | [`copy_dir`](04-files.zh-CN.md#copy_dir) |
| `vfs.list_dir(path)` | `list` | [`list_dir`](04-files.zh-CN.md#list_dir) |
| `vfs.path_exists(path)` | `bool` | [`path_exists`](04-files.zh-CN.md#path_exists) |

参数可使用表中名称按关键字传入。参数形状错误报 `type_error`。文件操作仍受调用方的一般执行资源约束；文件数量、大小和存储约束按实际调用链生效。

VFS 没有文件句柄式流接口，也没有任意属性。未列出的方法报 `attribute_error`。

## 完整交接示例

```python
workspace = VFS()
workspace.write_file("/input.txt", "hello")
workspace.write_file(
    "/main.sericite",
    "text = read_file(\"/input.txt\")\n"
    "write_file(\"/result.txt\", text + \"!\")\n",
)

program = VM(entry_file="/main.sericite", fs=workspace)
program.run()

result = program.take_fs()
print(result.read_file("/result.txt"))
program.dispose()
print(result.path_exists("/result.txt"))
```

```text
hello!
True
```

取出后的 `result` 是新的有效分离句柄；创建 VM 时使用的 `workspace` 已消费，不能再用它访问文件。
