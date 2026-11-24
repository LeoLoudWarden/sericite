# 配置 addon

Sericite 程序默认无法调用 Python 函数、读取真实磁盘或访问网络。需要这些能力时，操作者可以通过 `--addons` 指定一个可信 Python 文件，为入口程序配置 addon、初始文件和执行限额。

这里的“addon”是运行环境显式提供的能力。Sericite 源码仍按自己的语言规则执行，Python 配置文件则运行在沙箱之外。

## 授予一个函数

建立以下两个文件：

```text
project/
├── main.sericite
└── addons.py
```

`project/addons.py`：

```python
def double(number):
    return number * 2


def configure():
    return {
        "addons": {"double": double},
    }
```

`project/main.sericite`：

```python
from __addon__ import double

print(double(21))
```

运行时，在入口前给出配置文件：

```bash
sericite --addons project/addons.py project/main.sericite
```

预期输出：

```text
42
```

配置文件必须定义无参数的 `configure()` 并返回一个 dict；`addons`、`limits`、`files` 三个键都可省略。上例用 `addons` 的键指定脚本导入名，用值提供对应的 Python 函数。完整的字段类型和校验规则见[命令行参考](../reference/01-cli.zh-CN.md#addon-配置)。

addon 不会直接注入脚本的全局命名空间。每个需要它的 Sericite 源码模块都要写 `from __addon__ import ...`；也可以使用 import 别名。脚本侧的模块规则见[模块与功能拓展](../../scripting/guides/02-modules.zh-CN.md#能力拓展)。

`--addons` 同样适用于 `-c`、stdin 和 REPL：

```bash
sericite --addons project/addons.py -c 'from __addon__ import double; print(double(21))'
```

## 预置初始文件

`configure()` 返回的 `files` 把纯文本写入程序的虚拟文件系统：

```python
def configure():
    return {
        "files": {
            "/message.txt": "hello from the initial workspace",
            "/util.sericite": "value = 42\n",
        },
    }
```

程序随后可以使用这些文件：

```python
import util

print(read_file("/message.txt"))
print(util.value)
```

每个键是虚拟路径，每个值是字符串内容。文件只存在于内存工作区，不会与宿主路径建立持续映射。除了提供 `read_file()` 所需的初始数据，`files` 也可以为 `-c`、stdin 或 REPL 预置可 import 的模块。

Python 配置文件可以用 `__file__` 定位并读取自己的资源，再把读到的文本放进 `files`。读取真实文件的是可信 Python，不是 Sericite 脚本；是否允许这种读取以及允许读取哪些内容，由配置作者决定。

## 设置执行限额

`limits` 接受一个 `SericiteLimits`，用于配置入口程序的配额：

```python
from sericite import SericiteLimits


def configure():
    return {
        "limits": SericiteLimits(max_instructions=100_000),
    }
```

上面的入口程序最多执行 100000 条指令。超过限额时，程序以 `resource_exhausted` 终止，一次性命令以状态码 1 退出。

配额默认值面向开发调试；执行不完全可信的程序时应按任务需要显式收紧限额，而不是为消除资源错误改用无限配额。

## 信任边界

> **addon 配置文件拥有完整宿主权限。像运行任何 Python 文件一样信任它。**

配置文件及其授予的 Python 函数可以读取环境变量和真实磁盘、访问网络，其资源消耗和外部副作用也不由引擎配额约束。只应由操作者选择配置文件，并且只授予程序确实需要的函数。

引擎保证未授予的能力不可达，但不替能力实现者判断操作是否合理。数据边界、启动顺序和安全责任见[命令行参考](../reference/01-cli.zh-CN.md#addon-配置)；执行不可信代码前还应阅读[安全模型](../../../security.zh-CN.md)。
