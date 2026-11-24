# 文件系统

Sericite 为脚本提供纯文本文件系统，可以用统一的方式读写文件、管理目录。

## 为什么是这样

不同平台的文件接口和行为各有差异。Sericite 统一规定路径写法和操作规则，不把这些差异直接交给脚本。文件内容只有文本：写入的是字符串，读出的也是字符串。这样，同一段脚本在不同平台上都能以同样的方式处理文件。

## 一个文件读写的例子

```python
path = "scratch/note.txt"
write_file(path, "text")      # 写入字符串，自动创建缺失的父目录
read_file(path)               # 'text'：读出字符串
list_dir("scratch")           # ['note.txt']：查看目录内容
path_exists(path)             # True：检查路径是否存在
```

## 文件与目录

### 常用操作

文件操作：

```python
read_file(path)
write_file(path, text)
delete_file(path)
rename_file(old_path, new_path)
copy_file(source_path, destination_path)
```

目录操作：

```python
make_dir(path)
delete_dir(path)
rename_dir(old_path, new_path)
copy_dir(source_path, destination_path)
list_dir(path)
```

特别地，有 `path_exists(path)`，检查文件或目录是否存在。

### 路径解析

假设初始工作区为空，运行以下代码：

```python
notes_path = "/notes"
ideas_path = notes_path + "/ideas"

make_dir(ideas_path)
make_dir("/archive")

write_file(ideas_path + "/./draft.txt", "a new idea")
write_file(ideas_path + "/../today.txt", "finish the report")
write_file(ideas_path + "/../../archive/old.txt", "old report")
```

此时目录结构变为：

```text
/
├── archive
│   └── old.txt
└── notes
    ├── ideas
    │   └── draft.txt
    └── today.txt
```

`make_dir(ideas_path)` 会同时创建 `/notes` 和 `/notes/ideas`。三次写入都从 `ideas_path` 出发：`.` 不改变所在目录，每个 `..` 向上返回一级，因此文件分别写入 `ideas`、`notes` 和 `archive`。

### 隐式目录与显式目录

写入文件时会自动创建缺失的父目录；`make_dir` 则会显式创建目录。两者变为空目录后的处理不同：

```python
write_file("/scratch/draft.txt", "draft")  # 隐式创建 /scratch
write_file("/archive/old.txt", "old")      # 隐式创建 /archive
make_dir("/keep/empty")                    # 显式创建 /keep 和 /keep/empty

delete_file("/scratch/draft.txt")
rename_file("/archive/old.txt", "/old.txt")

path_exists("/scratch")      # False：空了的隐式目录被移除
path_exists("/archive")      # False：文件移走后，/archive 也被移除
path_exists("/keep")         # True：显式目录即使为空也保留
path_exists("/keep/empty")   # True
path_exists("/")             # True：根目录始终保留
```

## 路径解析不能和模块解析混为一谈

相对导入中的前导点表示当前包或上一级包；文件路径中的 `.` 和 `..` 则是普通路径段。两者看起来相似，但解析基准不同。

假设初始工作区如下，其中两个 `__init__.sericite` 都是空文件：

```text
/
├── main.sericite
└── lib
    ├── __init__.sericite
    └── sub
        ├── __init__.sericite
        ├── mod.sericite
        └── util.sericite
```

`/lib/sub/util.sericite`：

```python
prefix = "util: "
```

`/lib/sub/mod.sericite`：

```python
from . import util               # 当前包是 lib.sub，因此导入 lib.sub.util

text = read_file("./input.txt")  # 从根目录解析：读取 /input.txt
write_file("./output.txt", util.prefix + text)  # 写入 /output.txt
```

`/main.sericite`：

```python
write_file("/input.txt", "hello")
import lib.sub.mod

print(read_file("/output.txt"))
```

预期输出：

```text
util: hello
```

不要因为代码位于 `/lib/sub/mod.sericite`，就把 `"./input.txt"` 理解为 `/lib/sub/input.txt`。模块的位置影响相对导入，但文件操作仍然从工作区根目录解析路径。
