# 运行多文件项目

以源文件为入口时，命令行会自动准备程序静态 import 可达的模块。

## 一个最小项目

建立以下目录：

```text
project/
├── main.sericite
└── math_utils.sericite
```

`project/math_utils.sericite`：

```python
def double(number):
    return number * 2
```

`project/main.sericite`：

```python
from math_utils import double

print(double(21))
```

运行入口文件：

```bash
sericite project/main.sericite
```

预期输出：

```text
42
```

入口文件所在目录是项目根。这里根目录是 `project/`，所以 `math_utils` 对应 `project/math_utils.sericite`；从其他工作目录运行同一个入口时，模块解析基准也不会变成当前工作目录。

包、点号模块和相对导入使用相同的项目根。具体语法见脚本手册的[模块与功能拓展](../../scripting/guides/02-modules.zh-CN.md)。

## 项目目录如何成为工作区

命令行不会把整个项目目录直接暴露给程序，而是在启动时建立一份源码快照。上面的项目在虚拟文件系统中表现为：

```text
/
├── main.sericite
└── math_utils.sericite
```

启动扫描只复制静态 import 可达的源码，包括函数和条件分支里的 import。实际模块仍在执行到 import 语句时才从这份快照加载，不会临时回到真实磁盘寻找文件；程序运行期间对虚拟文件的修改也不会写回项目目录。

因此，下面的 `note.txt` 不能指望从项目目录自动读取：

```text
project/
├── main.sericite
└── note.txt
```

```python
text = read_file("/note.txt")
```

如果程序确实需要这份初始数据，应由操作者通过 addon 配置的 `files` 显式放入工作区，见[预置初始文件](03-addons.zh-CN.md#预置初始文件)。

## 其他入口不会扫描当前目录

只有源文件入口会建立上述目录快照。`-c`、stdin 和 REPL 只从已有虚拟文件系统导入模块，即使当前目录中存在同名源码，也不会自动找到它：

```bash
sericite -c 'from math_utils import double'
```

需要在这些入口中使用模块时，可以用 addon 的 `files` 预置源码。完整的加载边界和覆盖顺序见[命令行参考](../reference/01-cli.zh-CN.md#多文件项目)。
