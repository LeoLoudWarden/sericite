# 文件与目录

所有文件内容都是 `str`，读写均为 Unicode 文本，不提供二进制接口。脚本不能经这些函数访问真实磁盘。

分离的 VFS 句柄提供同名方法，路径、返回和错误契约与本文一致；所有权规则见 [VFS](07-vfs.zh-CN.md)。

## 路径

所有 `path` 参数必须是 `str`，否则报 `type_error`。路径按整个工作区根解析，不以当前模块所在目录为基准。

规范化规则：

- `/` 表示根目录；绝对和相对写法都从这个根解析。
- 重复 `/` 和空路径段忽略。
- `.` 段忽略。
- `..` 删除前一段；位于根时继续向上仍留在根。
- `list_dir` 只列直接子项，返回排序后的名称列表，不包含路径前缀。

```text
notes/./draft.txt       -> /notes/draft.txt
/notes/../today.txt     -> /today.txt
../../outside.txt       -> /outside.txt
```

相对导入的前导点属于模块语法，不能与此处的路径段混淆。

## 隐式与显式目录

`write_file`、`rename_file`、`copy_file` 和目录移动/复制会隐式创建缺失的目标父目录。隐式目录变空后自动移除。

`make_dir` 显式创建目标及缺失的父目录。显式目录即使为空也保留。根目录始终存在。

所有变更操作在提交前完成路径和资源检查。失败不会留下部分文件或目录修改；失败和重试仍正常消耗执行资源。

## `read_file`

```text
read_file(path) -> str
```

读取指定文件的全部文本。

| 情况 | 错误 |
|---|---|
| 文件不存在 | `file_not_found` |
| 路径是目录 | `is_directory` |
| 路径不是字符串 | `type_error` |

## `write_file`

```text
write_file(path, text) -> None
```

把 `text` 写入文件。文件存在时替换全部内容，不存在时创建文件，并隐式创建缺失的父目录。`text` 必须是 `str`。

| 情况 | 错误 |
|---|---|
| 目标路径是目录 | `is_directory` |
| 中间路径段是文件 | `not_directory` |
| `text` 不是字符串 | `type_error` |
| 文件数、单文件或总存储限制拒绝变更 | `file_limit_error` |

## `delete_file`

```text
delete_file(path) -> None
```

删除文件。源不存在报 `file_not_found`，源是目录报 `is_directory`。因此变空的隐式父目录会自动移除。

## `rename_file`

```text
rename_file(old_path, new_path) -> None
```

重命名或移动文件，并隐式创建缺失的目标父目录。

- 源不存在：`file_not_found`。
- 源是目录：`is_directory`。
- 目标已存在，无论文件或目录：`file_exists`，不覆盖。
- 目标中间路径段是文件：`not_directory`。
- 规范化后源与目标相同：目标已经存在，因此报 `file_exists`。

重命名不增加文件数，但路径和目录元数据增长仍可能受文件存储配额约束。

## `copy_file`

```text
copy_file(source_path, destination_path) -> None
```

复制文件文本，并隐式创建缺失的目标父目录。源和目标错误规则与 `rename_file` 相同。复制新增文件，因此受文件数、单文件大小和总存储限制；源文件保持不变。

## `make_dir`

```text
make_dir(path) -> None
```

显式创建目录及缺失的父目录。目标已有文件或目录时报 `file_exists`，包括目标已经是由本函数创建的目录；中间路径段是文件时报 `not_directory`。

根目录始终存在，因此对根调用也报 `file_exists`。

## `delete_dir`

```text
delete_dir(path) -> None
```

递归删除整棵目录树，包括显式空目录。源不存在报 `file_not_found`，源是文件报 `not_directory`。根目录不能作为删除源，报 `runtime_error`。

## `rename_dir`

```text
rename_dir(old_path, new_path) -> None
```

递归重命名或移动目录树，不覆盖已有目标。

| 情况 | 错误 |
|---|---|
| 源不存在 | `file_not_found` |
| 源是文件 | `not_directory` |
| 目标已存在 | `file_exists` |
| 根目录作为源或目标 | `runtime_error` |
| 目标位于源目录内部 | `runtime_error` |
| 目标中间路径段是文件 | `not_directory` |

目标父目录按需创建。移动后的目录保留显式/隐式属性和整棵子树。

## `copy_dir`

```text
copy_dir(source_path, destination_path) -> None
```

递归复制整棵目录树。路径和错误规则与 `rename_dir` 相同，但源保持不变。复制新增全部文件和目录，受文件数、单文件大小、总存储及一般资源配额约束。

## `list_dir`

```text
list_dir(path) -> list
```

返回目录直接子项名称的排序列表，文件和目录都包含，不递归。目录为空时返回 `[]`。

目录不存在报 `file_not_found`，路径是文件报 `not_directory`。

## `path_exists`

```text
path_exists(path) -> bool
```

文件或目录存在时返回 `True`，否则返回 `False`。根目录始终返回 `True`。该函数不区分文件和目录；路径不是字符串时报 `type_error`。

## 文件限制与错误恢复

程序的文件操作受 `max_fs_files`、`max_fs_file_bytes` 和 `max_fs_storage_bytes` 的约束，详见 [VM 配额](06-vm.zh-CN.md#配额)。这些约束拒绝变更时产生 `file_limit_error`。

如果多种文件失败采用同一处理方式，可使用固定过滤器 `except file_error`，其成员见[错误参考](05-errors.zh-CN.md#固定过滤器组)。
