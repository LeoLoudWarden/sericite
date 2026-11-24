# 运行程序

`sericite` 命令可以直接运行 Sericite 源码，也可以打开一个持续保留状态的交互会话。

安装发行包后，命令名为 `sericite`：

```bash
pip install sericite
```

在源码仓库中开发时，可以改用 `uv run sericite`。`python -m sericite` 与 `sericite` 使用同一套命令行行为。

## 运行源文件

新建 `hello.sericite`：

```python
print("hello from Sericite")
```

运行它：

```bash
sericite hello.sericite
```

预期输出：

```text
hello from Sericite
```

源文件按 UTF-8 读取。`.sericite` 是约定后缀，命令行不会强制检查后缀。

## 直接执行命令字符串

短程序可以用 `-c` 或 `--command` 直接给出：

```bash
sericite -c 'print(6 * 7)'
```

预期输出：

```text
42
```

也可以从标准输入读取完整源码，此时用单独的 `-` 作为入口：

```bash
printf 'print("hello from stdin")\n' | sericite -
```

这种方式会先把标准输入全部读完再执行源码。需要在程序运行时读取数据时，见[不要混淆源码输入与数据输入](04-io-and-diagnostics.zh-CN.md#不要混淆源码输入与数据输入)。

## 传递脚本参数

入口之后的内容都传给脚本，不再由命令行解释。新建 `args.sericite`：

```python
print(argv)
```

运行：

```bash
sericite args.sericite first --flag
```

预期输出：

```text
['args.sericite', 'first', '--flag']
```

`argv` 是字符串列表，第一项标识本次入口，其余项是脚本参数。文件入口保留你写下的路径；`-c` 入口的第一项是 `"-c"`，stdin 入口的第一项是 `"-"`。

```bash
sericite -c 'print(argv)' first --flag
```

预期输出：

```text
['-c', 'first', '--flag']
```

因此，脚本可以自行实现 `--flag` 等参数约定。即使参数是单独的 `--`，只要位于入口之后，也会原样进入 `argv`。

命令行自己的选项应放在入口之前。若需要显式结束命令行选项，可以在入口前写 `--`；这个 `--` 由命令行消费，不进入 `argv`。

## 使用 REPL

不带源文件或 `-c` 时，命令行进入 REPL：

```text
>>> x = 40
>>> x + 2
42
>>> write_file("/note.txt", "saved")
>>> read_file("/note.txt")
'saved'
```

`>>>` 表示等待新输入，`...` 表示多行语句尚未完成。单个表达式会用 `repr` 回显非 `None` 的结果；赋值等其他语句只显示它们自身产生的输出。

每次输入都在同一个 VM 会话中执行，因此变量、函数、schema、已导入模块和虚拟文件都会保留。一次输入发生编译或运行错误时，错误会写入 stderr，随后仍可继续输入；已经成功建立的会话状态不会因为这一次错误而整体重建。

发送 EOF 可正常退出 REPL。

## 下一步

- 源码拆成多个文件后，阅读[运行多文件项目](02-projects.zh-CN.md)。
- 程序需要宿主函数、初始文件或自定义配额时，阅读[配置 addon](03-addons.zh-CN.md)。
- 脚本语法和语言内建不属于命令行教程，见[脚本快速开始](../../scripting/guides/01-quick-start.zh-CN.md)。
- 需要核对完整参数和会话行为时，查阅[命令行参考](../reference/01-cli.zh-CN.md)。
