# 输入、输出与错误诊断

命令行把入口程序的虚拟输入输出连接到宿主的标准流：脚本 `input()` 读取 stdin，`print()` 写入 stdout，未被脚本处理的错误写入 stderr。

## 从标准输入读取数据

新建 `greet.sericite`：

```python
name = input()
print("hello", name)
```

直接运行时，`input()` 等待你输入一行；也可以通过管道或重定向提供数据：

```bash
printf 'world\n' | sericite greet.sericite
```

预期输出：

```text
hello world
```

`input()` 每次读取一行，并去掉行尾换行符。输入耗尽后继续读取会产生可捕获的 `input_error`，因此可以逐行处理直到 EOF：

```python
lines = []

while True:
    try:
        lines.append(input())
    except input_error:
        break

print(lines)
```

如果未捕获这个错误，一次性程序会打印诊断并以状态码 1 退出；REPL 会显示错误并继续等待下一条命令。

### 不要混淆源码输入与数据输入

下面的 `-` 表示从 stdin 读取完整源码：

```bash
printf 'print("hello")\n' | sericite -
```

命令行会先读到 EOF，再开始执行。因此这份源码中的 `input()` 不会再从同一 stdin 读到数据。

需要同时提供源码和数据时，应选择以下方式之一：

- 把源码保存为文件，把 stdin 留给 `input()`；
- 使用 `-c` 提供源码，把 stdin 留给 `input()`；
- 用 addon 的 `files` 提供适合作为文件处理的数据。

REPL 的命令输入与脚本 `input()` 共用 stdin。交互输入一条调用 `input()` 的命令后，接下来的一行会先作为这次脚本调用的数据，而不是新的 REPL 命令。

## 标准输出

入口程序每次 `print()` 都会立即写入并刷新 stdout，包括 `end=""` 的无换行输出。调用方可以在程序结束前收到输出，不必等待进程退出。

```bash
sericite -c 'print("first", end=""); input(); print("second")'
```

输入一行数据之前，`first` 已经写出。

## 阅读错误诊断

新建 `error.sericite`：

```python
def divide():
    return 1 / 0

divide()
```

运行后，stdout 不包含这次错误；stderr 为：

```text
error.sericite:2: zero_division: division by zero
Traceback (most recent call last):
  File "error.sericite", line 4, in <module>
  File "error.sericite", line 2, in divide
```

第一行给出错误位置、错误 kind 和消息。调用栈从调用方指向实际错误点，每一帧使用定义该代码的源码位置。不同源码入口的名称和启动阶段错误的特殊形式见[命令行参考](../reference/01-cli.zh-CN.md#错误诊断)。

程序在失败前已经写入 stdout 的内容不会因后续错误而丢失。shell 管道只合并或分离标准流，不会改变 Sericite 内部的错误捕获规则；异常处理见[脚本异常处理](../../scripting/guides/04-errors.zh-CN.md)。

## 退出码

自动化脚本可以根据进程退出码判断命令是否完成：正常完成为 0，其他状态表示启动、执行或命令行用法存在问题。REPL 中普通的单次输入错误不会结束会话，也不会仅因此产生非零退出码。

需要区分具体失败类别或处理管道关闭时，查阅[命令行参考的退出码](../reference/01-cli.zh-CN.md#退出码)。
