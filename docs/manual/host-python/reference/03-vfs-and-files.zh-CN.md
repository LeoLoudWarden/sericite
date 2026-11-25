# VFS 与文件

`VFSHandle` 是 Python 宿主持有的纯文本内存工作区句柄。它可以预先准备文件，排他移入一台 VM，并在该 VM 终态后取回。

句柄由[`SericiteEngine.create_vfs`](01-engine-and-limits.zh-CN.md#sericiteenginecreate_vfs)或[`VMHandle.take_fs`](02-vm.zh-CN.md#vmhandletake_fs)返回，不应直接实例化。文件路径、目录行为和公开文件错误的共同权威是[脚本文件与目录参考](../../scripting/reference/04-files.zh-CN.md)。完整交接示例见[准备工作区](../guides/04-workspaces.zh-CN.md)。

## 所有权与状态

文件树的依附状态与 `VFSHandle` 的有效性是两个不同维度。文件树只有两种依附状态：

| 文件树状态 | 含义 | 宿主访问方式 |
|---|---|---|
| 分离 | 尚未依附 VM | 通过有效的 `VFSHandle` |
| 依附 | 已由一台 VM 独占 | 通过该 VM 的 `VMHandle` |

`VFSHandle` 自身则分为有效和已失效。成功创建 VM 会使移入文件树的原句柄永久失效，之后调用其文件方法报 `runtime_error`；文件树依附 VM 与旧句柄失效是同一次提交的两个结果，不是文件树的两个先后阶段。

一个 VFS 在任意时刻最多依附一台 VM，不存在共享写权限。移交的是文件树，不包括模块缓存、虚拟 IO、局部变量、addon、断点、模块解析根或累计资源用量。

### 移入 VM

```python
engine.create_root(source=source, fs=workspace)
engine.create_root(entry_file="/main.sericite", fs=workspace)
```

`fs` 必须是当前引擎中有效的句柄，其文件树必须处于分离状态。创建全部成功后，文件树依附新 VM，旧句柄永久失效。入口读取、源码编译、参数或配额检查失败时，文件树仍分离，原句柄仍可使用。

未提供 `fs` 时，root 获得空白 VFS。使用 `entry_file` 必须显式提供 `fs`；`source` 与 `entry_file` 不能同时提供。

### 从 VM 取回

```python
workspace = vm.take_fs()
```

只能从 `done`、`error`、`resource_exhausted` 或 `terminated` 状态的 VM 取出。等待输入或断点暂停的会话可继续执行，或先 `terminate()` 再取出。

成功后文件树重新分离，并返回新的有效句柄。取出后原 VM 不再接受 `exec()`，原 VM 定义的函数和通过原 VM 发起的宿主文件管理调用也不能继续访问已经移交的工作区。失败操作保持所有权和句柄有效性不变；销毁原 VM 不影响取回的工作区。

## 文件与目录方法

`VFSHandle` 与宿主 `VMHandle` 提供以下同名方法。参数可以使用表中名称按关键字传入。

| 方法 | 返回 | 详细契约 |
|---|---|---|
| `read_file(path: str)` | `str` | [`read_file`](../../scripting/reference/04-files.zh-CN.md#read_file) |
| `write_file(path: str, text: str)` | `None` | [`write_file`](../../scripting/reference/04-files.zh-CN.md#write_file) |
| `delete_file(path: str)` | `None` | [`delete_file`](../../scripting/reference/04-files.zh-CN.md#delete_file) |
| `rename_file(old_path: str, new_path: str)` | `None` | [`rename_file`](../../scripting/reference/04-files.zh-CN.md#rename_file) |
| `copy_file(source_path: str, destination_path: str)` | `None` | [`copy_file`](../../scripting/reference/04-files.zh-CN.md#copy_file) |
| `make_dir(path: str)` | `None` | [`make_dir`](../../scripting/reference/04-files.zh-CN.md#make_dir) |
| `delete_dir(path: str)` | `None` | [`delete_dir`](../../scripting/reference/04-files.zh-CN.md#delete_dir) |
| `rename_dir(old_path: str, new_path: str)` | `None` | [`rename_dir`](../../scripting/reference/04-files.zh-CN.md#rename_dir) |
| `copy_dir(source_path: str, destination_path: str)` | `None` | [`copy_dir`](../../scripting/reference/04-files.zh-CN.md#copy_dir) |
| `list_dir(path: str)` | `list[str]` | [`list_dir`](../../scripting/reference/04-files.zh-CN.md#list_dir) |
| `path_exists(path: str)` | `bool` | [`path_exists`](../../scripting/reference/04-files.zh-CN.md#path_exists) |

两类句柄的操作对象不同：

- `VFSHandle` 只在句柄有效且文件树分离时提供文件方法；句柄失效或文件树依附 VM 时以 `runtime_error` 拒绝。
- 宿主 `VMHandle` 只操作该 VM 当前依附的工作区；VM 已销毁或 VFS 已取出时以 `runtime_error` 拒绝。

宿主调用不执行脚本，也不提供流式文件句柄、字节模式或真实磁盘路径映射。路径是工作区内的逻辑路径，文件内容必须是字符串。

## 限制与计量

宿主文件管理是可信通道，不计入脚本资源计量，但文件自身约束仍然有效：

- `VFSHandle` 的扩张操作使用引擎默认 `SericiteLimits` 的文件数、单文件大小和总存储约束。
- `VMHandle` 的扩张操作使用该 VM 的相应限制。
- 文件约束按操作前后的当前文件世界判断，允许收缩以及不使已超限项目进一步扩张的操作。
- 拒绝变更报普通 `file_limit_error`，不终止 VM，操作保持原子性。

这些是宿主管理规则，不表示脚本可以用它们绕过自己的执行计量。脚本调用文件内建或脚本内分离 VFS 方法时，仍按调用方和文件操作实际所属的执行环境计量。
