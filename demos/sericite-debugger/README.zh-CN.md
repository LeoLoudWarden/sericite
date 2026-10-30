# sericite-debugger：调试器也可以被调试

[English](README.md)

这是一个用 Sericite 编写的交互式调试器。它接收**一段 Sericite 源码、这段程序的输入和目标 argv**，把源码创建为子 VM，再逐语句或逐指令驱动；不读取预设的目标文件。

因此目标可以是任意源码，包括这个调试器自己。完整的自指形态是 **D(D(P))**，用法见下文“自指”一节。

## 输入协议

```text
debugger.sericite SOURCE [INPUT] [TARGET_ARG ...]
```

| 参数 | 含义 |
|---|---|
| `SOURCE` | 目标程序的完整 Sericite 源码字符串，不是文件名 |
| `INPUT` | 预置给目标 VM 的 stdin，可包含多行；省略后不预置 |
| `TARGET_ARG` | 显式构造给目标程序的 argv 参数 |

子 VM 不自动继承父级 argv（见 [CLI 参考](../../docs/cli-reference.zh-CN.md)第 2 节）。因此调试器会在目标源码前显式加入一行 `argv = [...]`。

面板把这一行也显示出来，所以显示的行号与目标实际执行完全一致。

## 调试一段即时传入的程序

```bash
PROGRAM=$'name = input()\nprint("hello", name)'

uv run sericite demos/sericite-debugger/debugger.sericite \
  "$PROGRAM" 'Sericite'
```

启动后输入 `r`，目标程序会消费预置的 `Sericite` 并打印：

```text
hello Sericite
session ended · done
```

也可以省略 `INPUT`。当目标进入 `waiting_input` 时，外层调试器会显示 `[child stdin]` 提示；输入一行后，调试器通过 `feed_input()` 把它交给目标。

目标的输入通道和外层调试器的命令通道不会混在一起。

## watchpoint 与错误现场

下面的程序在最后一次 record 字段写入时违反运行期契约：

```bash
PROGRAM=$(cat <<'EOF'
class Account:
    balance: int

account = Account(100)
deposit = 40
account.balance = account.balance + deposit
print("after deposit", account)
account.balance = "unlimited"
EOF
)

uv run sericite demos/sericite-debugger/debugger.sericite "$PROGRAM"
```

输入：

```text
w account
c
c
c
```

第一次 `c` 在 `account` 创建时暂停，第二次在余额从 100 变成 140 时暂停，第三次到达契约错误：

```text
◆ watchpoint hit · account
  before: {'<record>': {'balance': 100}}
  after:  {'<record>': {'balance': 140}}
```

最终面板用 `!` 标记错误行，并保留三类现场：

- 当前帧的 `locals`；
- 目标 stdout；
- 安全错误视图。

```text
│ !   9  account.balance = "unlimited"
│ contract_error: field balance: expected int, got str
│ <module>:9
session ended · error
```

## 自指：D(D(P))

把调试器源码作为外层目标，再告诉内层调试器去调试另一个程序：

```bash
DEBUGGER="$(cat demos/sericite-debugger/debugger.sericite)"
PROGRAM=$'name = input()\nprint("hello", name)'

uv run sericite demos/sericite-debugger/debugger.sericite \
  "$DEBUGGER" \
  $'r\n' \
  "$PROGRAM" \
  $'Sericite\n'
```

启动后，在外层输入 `r`。四组参数分别表示：

1. 外层目标：内层调试器 D 的源码；
2. 内层 D 的 stdin：命令 `r`；
3. 内层 D 的目标：普通程序 P 的源码；
4. P 的 stdin：`Sericite`。

形成两层控制：

```text
outer debugger
  └─ inner debugger
       └─ name = input()
          print("hello", name)
```

外层最终能从内层的独立 stdout 尾部看到：

```text
│ │ hello Sericite
│ ╰──────────────────────────────────────────────────────────────────────╯
│ session ended · done
session ended · done
```

外层能观察内层的安全快照，但不能越过内层取得最内层 VM 的句柄。控制可以递归，可见性仍有边界；快照为什么不携带子 VM 句柄，见[虚拟机参考](../../docs/vm-reference.zh-CN.md)第 4 节。

## 命令

| 输入 | 行为 |
|---|---|
| 回车 | `step()`，执行一条源码语句 |
| `i` | `step_instruction()`，执行一条内部指令 |
| `c` | 有 watchpoint：逐指令继续到命中、等待输入或终态；无 watchpoint：直接 `run()` |
| `w NAME` | 监视当前帧局部变量；出现、离开帧或值变化都会暂停 |
| `w off` | 关闭 watchpoint |
| `r` | 不检查 watchpoint，直接 `run()` |
| `q` | `terminate()` 目标 VM |
| `h` | 显示帮助 |

语句级单步把函数调用作为一条语句执行；指令级单步可以进入函数内部（语义见[虚拟机参考](../../docs/vm-reference.zh-CN.md)第 4 节）。

目标 VM 的指令配额为 20,000 条。长源码只显示当前位置附近的窗口，避免自调试时反复打印整份调试器源码。

当前快照 API 不提供 opcode 名称或操作数，因此 `i` 展示每条内部指令执行后的源码位置和状态变化，不是反汇编。快照的完整字段与限制见[虚拟机参考](../../docs/vm-reference.zh-CN.md)第 4 节。

## 文件与依赖

- `debugger.sericite`：唯一程序文件，包含输入协议、watchpoint、VM 驱动和面板。
- `tests/test_sericite_debugger.py`：真实 CLI 测试，包括完整的 D(D(P)) 链路。

demo 不需要 Python capabilities、目标文件目录、网络、LLM 或第三方依赖。

命令行中的 shell 变量只负责把源码文本放进 argv，不参与 Sericite 程序的执行。
