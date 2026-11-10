# Sericite 虚拟机参考

[English](vm-reference.md)

本文面向**需要在 Sericite 脚本中创建和驱动子 VM 的读者**。执行会话、VFS 移交、VM 状态、驱动方法、exec 投递、配额与函数授予的脚本契约都在这里；Python 宿主 API 见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)。

## 1. VM 是什么

VM 是相互隔离的执行会话：看不到父级的变量、文件和句柄，也不知道自己嵌套在第几层。每段会话有独立的模块作用域与缓存、输入队列、stdout 和累计执行账；它依附的 VFS 是独占的文件世界。隔离承诺见[安全模型](security.zh-CN.md)第 2 节。

VM 不是一次性的：同一段会话可以喂输入、逐语句或逐指令单步、查看快照、通过 `exec()` 接收新源码继续执行，或随时终止。`run()`、`step()` 和多次 `exec()` 不会开始新会话；需要全新变量、模块缓存和执行账时应创建另一台 VM。

## 2. 创建 VM 与移交 VFS

脚本内用 `VM(code, **options)` 创建子 VM：

```python
sub = VM(code, max_instructions=10000)   # 资源配额，只能比当前环境更严
sub = VM(code, output_writer=forward, buffer_output=False)
sub = VM(code, fs=workspace)              # 移入一个分离状态的 VFS
```

默认创建空白 VFS。`fs` 只接受 `VFS()` 或另一终态 VM 的 `take_fs()` 所返回的分离句柄；挂载成功后旧句柄永久失效，VFS 由新 VM 独占。`output_writer` 与 `buffer_output` 配置该 VM 的输出，`functions` 用于授予函数（第 6 节），其余选项为配额字段。输出转发见第 4 节，配额见第 5 节。

## 3. 状态与生命周期

VM 状态包括：`ready`、`waiting_input`、`done`、`error`、`resource_exhausted`、`terminated`。

`terminate()` 只把 `ready` 或 `waiting_input` 的 VM 标记为 `terminated`；其他状态下是静默空操作。仍依附 VFS 的 `done`/`error` 等终态 VM 可以继续接受 `exec` 投递。

VM 会占用需要释放的资源。只要仍能从 VM 值或授予函数的环境访问它，它就会保留；因此终态 VM 仍能用于调试快照，并在仍依附 VFS 时接受后续 `exec` 投递。

当一台 VM 彻底不可达后，垃圾回收会最终自动销毁它，包括存在自引用或跨 VM 循环的情况。自动回收不保证在某个语句或作用域边界立即发生；需要确定释放时点时仍应显式调用 `dispose()`。

`dispose()` 可以销毁任意状态的 VM，包括正在运行或等待输入的 VM；它会终止并注销目标及其所有存活后代，不要求子先父后。它会：

- 立即释放目标及其所有存活后代占用的 `max_total_vms` 槽位；
- 让正在运行的目标在当前指令安全退出后停止，不执行目标脚本的 `finally`；
- 幂等——重复释放是空操作；
- 使 VM 值失效——已释放 VM 上的其他方法以 `runtime_error` 失败。

`take_fs()` 只允许在 `done`、`error`、`resource_exhausted` 或 `terminated` 终态调用；它会原子地取出 VFS 并返回新的分离句柄。运行中或 `waiting_input` 不能直接取出，放弃等待中的会话时先 `terminate()`。取出后，原 VM 仍可快照、读取 stdout 和销毁，但失去文件访问且不再接受 `exec()`；旧 home 函数与旧 VFS 句柄也不能访问已移交的世界。若取出失败，VFS 仍属于原 VM。销毁原 VM 不影响已经分离的 VFS。

定义函数所属的 VM 被销毁后，从该 VM 传到其他 VM 的函数也会失效；调用时以可捕获的 `runtime_error` 失败。授予语义见第 6 节。

资源不足时，`dispose()` 会在销毁前失败。销毁不会退还父级已经消耗的累计指令或内存额度；内部生命周期与计费规则见[架构说明](architecture.zh-CN.md)第 5.4 节。

## 4. 驱动方法

| 方法 | 用途与返回 |
|---|---|
| `run(inputs=None) -> str` | 驱动到完成、暂停或失败，返回 stdout；`inputs` 必须是字符串 list/tuple，整批验证后才入队 |
| `exec(source) -> str` | 向该 VM 投递新源码并在持久的模块作用域中执行；只返回本次投递产生的输出；见下文 |
| `feed_input(value)` | 向队列加入一行输入；若 VM 正在等待输入，将其唤醒 |
| `step() -> dict` | 执行一条语句并返回快照 |
| `step_instruction() -> dict` | 执行一条内部指令并返回快照 |
| `snapshot() -> dict` | 返回当前安全快照，不推进执行 |
| `stdout() -> str` | 返回当前 stdout |
| `terminate()` | 终止 VM；生效状态与空操作语义见第 3 节 |
| `dispose()` | 强制销毁任意状态的 VM 及其存活后代；见第 3 节 |
| `take_fs() -> VFS` | 从终态 VM 原子取出 VFS，返回新的分离句柄；见第 3 节 |

VM 值不再提供脚本侧文件代理。文件内置函数始终操作当前会话独占的 VFS；分离句柄上的同名方法操作分离工作区，路径、错误和目录语义见[语言参考](language-reference.zh-CN.md)第 6 节。

```python
fs = VFS()
fs.write_file("/input.txt", "数据")       # 先预置分离工作区
sub = VM(code, fs=fs, max_instructions=10000)
sub.feed_input("一行输入")                # 喂 input()
out = sub.run()
fs = sub.take_fs()
print(fs.read_file("/result.txt"))        # 终态后取回产出
```

推荐工作流：运行前配置分离 VFS，移入 VM 执行，终态取出后读取结果。

输入耗尽且没有更多输入来源是正常暂停（`waiting_input`），不是异常；输入源显式报告关闭（`input_error`）则走普通可捕获错误路径。执行失败时，`sub.run()` 把子 VM 的错误按原 kind 传播给调用脚本，可捕获的 kind 仍可正常捕获。

子 VM 因执行预算耗尽进入 `resource_exhausted` 终态后，父 VM 可以捕获该错误；父 VM 自身或祖先的执行预算错误仍不可捕获。文件操作约束使用另一套可恢复的错误语义，见下文第 5 节。

终态 VM 仍可被操作，但两类方法的行为不同：

- 不驱动该 VM 的方法（`snapshot`、`step`、`step_instruction`、`stdout`、`take_fs` 等）仍然可用；在终态 VM 上，`step`/`step_instruction` 只返回快照，`take_fs` 只由调用方计量；
- 驱动方法（`feed_input`、带输入的 `run`、`exec` 等）可能因该 VM 已耗尽的配额而失败。

计费模型（哪些操作由谁计量）见[架构说明](architecture.zh-CN.md)第 5.4 节。

### 输出转发与缓冲

每台 VM 都有独立的 `output_writer` 与 `buffer_output` 配置。子级 writer 由父级显式配置，不会隐式继承：

```python
def forward(text):
    print(text, end="")

sub = VM('print("live")', output_writer=forward)
```

writer：

- 在每次 `print()` 完成输出处理和缓冲后接收一个字符串；
- 遵循授予函数语义：保留定义方的模块变量、闭包、已授予函数和输入输出，并受定义方与调用方的资源限制；
- 调用父级 `print()` 时，输出因此继续沿父级配置链转发；
- 返回值被忽略，异常按普通规则在触发它的 `print()` 处传播；
- 必须同步完成——若试图通过 `input()` 暂停，会在该 `print()` 处抛出 `runtime_error`。

默认 `buffer_output=True`，为 `run()`/`exec()`/`stdout()` 和快照保留完整 stdout。设为 `False` 后，输出仍转发但不再保留，上述缓冲输出视图为空。输出与 writer 配置跨 `exec` 投递保留。

### exec：向既有 VM 投递新源码

`exec(source)` 让 VM 换上新程序但保留它的世界：

- **保留的世界**：新的模块帧复用先前的模块作用域，模块级名字（变量、函数、schema）因此持久；文件系统、输入队列、授予的函数和已导入模块的缓存不受影响。
- **状态与丢弃规则**：除 `terminated`、已通过 `take_fs()` 分离 VFS，以及正被驱动（`run()`/`exec()`/`step()` 进行中）之外，任何状态都接受投递。尚未执行完的程序（从未开始，或正暂停在输入上）会被丢弃，先前的错误被清除，旧的调试帧栈被替换——需要现场请先 `snapshot()`。
- **编译原子性**：编译先于任何状态改变完成，编译失败的源码让 VM 保持原样。
- **配额按生命周期累计**：指令、内存与输出消耗跨投递累计，而非按投递计算。

### 快照

`step()`、`step_instruction()` 与 `snapshot()` 返回的快照包含脚本可见的安全视图：

| 字段 | 含义 |
|---|---|
| `state` | 当前状态 |
| `last_line` / `next_line` | 最近及下一条逻辑源码行 |
| `locals` | 用户可见局部值的安全副本 |
| `stdout` | 当前输出 |
| `error` | `kind`、`message`、`line`、`column`、`frames`，无错误时为 `None` |
| `instruction_count` | 当前指令与工作量账 |

复杂值受节点和深度预算约束；环与共享结构使用占位符，不会指数展开。快照不包含可继续操作的子 VM 值。

`error.frames` 是该 VM 的调用栈。每项是 `{"function": str, "line": int | None}`；栈顺序与行号脱敏规则同脚本异常 record，见[语言参考](language-reference.zh-CN.md)第 5 节。

## 5. 配额

每台 VM 的资源配额由下列字段定义。所有字段都有默认值；默认值面向开发调试，不是执行不可信代码时的安全建议。

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `max_instructions` | 1,000,000 | 指令及折算工作量上限 |
| `max_output_bytes` | 1,048,576 | stdout 的 UTF-8 字节上限 |
| `max_frames` | 100 | 调用帧上限 |
| `max_list_size` | 100,000 | 单列表/元组槽位上限 |
| `max_dict_size` | 100,000 | 单字典项数上限 |
| `max_string_bytes` | 1,048,576 | 单字符串上限 |
| `max_int_bits` | 4096 | 整数位宽上限 |
| `max_total_bytes` | 67,108,864 | 近似内存总账高水位 |
| `max_total_vms` | 1000 | 整个运行时同时存活且尚未销毁的 VM 数上限，包括入口 VM；销毁后释放槽位 |
| `max_descendant_vms` | 1000 | 单台 VM 的整棵子树中同时存活的后代数上限，不含自身；销毁后释放槽位 |
| `max_vm_depth` | 8 | VM 嵌套深度上限 |
| `max_fs_files` | 1000 | 当前 VM 可扩张到的 VFS 文件总数上限 |
| `max_fs_file_bytes` | 1,048,576 | 当前 VM 可写入或复制的单文件 UTF-8 字节上限 |
| `max_fs_storage_bytes` | 67,108,864 | 当前 VM 可扩张到的 VFS 近似总存储量，包含文本、路径与目录元数据 |

`max_string_bytes` 因历史原因以此命名，但实际按单字符串的字符数计算；单文件和输出配额按 UTF-8 字节计算，文件总存储量沿用内存模型的近似字节口径。

三个文件字段都是 **VM 对文件操作的约束**，不是 VFS 持有的账户：

- 当前 VM 与实际调用链上的限制共同收紧。约束拒绝变更时使用普通、可捕获的 `file_limit_error`，不终止执行会话。
- 每项约束分别比较操作前后的对应当前用量。既有世界已经超限时，仍可读取、收缩或执行不使该项用量进一步扩张的操作；新增文件、扩大文件以及会增加路径或目录元数据的重命名，仍须通过相应检查。
- 变更在提交前完成路径与资源检查，失败不留下部分修改；失败与重试仍纳入正常计量。

只有累计字段 `max_instructions`、`max_output_bytes`、`max_total_bytes` 接受用 `-1` 表示不设上限。包括存活数量字段 `max_total_vms`、`max_descendant_vms` 在内的其余字段都是结构性配额，必须是非负有限整数；所有字段都拒绝其他负数和非整数值。

创建 VM 时会检查所有祖先的 `max_descendant_vms`，因此无论按何种树形结构创建子 VM，都无法绕过某一层限制。不可信子 VM 达到自己的后代上限后以 `resource_exhausted` 终止，仍存活的父级可以捕获；`max_total_vms` 继续作为整个运行时的全局防线。

直接子级配额 `max_child_vms` 已移除。需要禁止某台 VM 创建任何后代时，将它自己的 `max_descendant_vms` 设为 `0`；这不影响父级创建该 VM。

脚本内创建子 VM 时，`VM()` 的配额关键字参数与上表一一对应，只能收紧不能放宽。请求值与继承上限合并时：

- 请求 `-1` 会继承父级有效值；
- 无限父级下的有限请求采用该有限上限；
- 只有两侧都无限才得到无限，因此有限祖先始终是硬上限。

授予函数也会同时受定义方与调用方的配额约束。

无限配额只取消上限检查，不会停止记录用量。

子 VM 的指令、内存和创建消耗也会计入相关祖先。完整计费模型见[架构说明](architecture.zh-CN.md)第 5 节。

## 6. 授予函数

脚本可以用 `functions={"name": fn}` 把自己 `def` 的函数或已持有的被授予函数授予下一层：

```python
def double(x):
    return x * 2
sub = VM("print(double(21))", functions={"double": double})
sub.run()                        # 输出 42
```

被授予的 sericite 函数：

- 保留定义方的模块变量、闭包和已授予环境；
- 函数中的 `print`、文件操作、子 VM 创建和 import 仍使用定义方的环境，包括定义方的文件系统与模块缓存；
- 调用同时受定义方与调用方的资源限制。

通过授予函数在父子 VM 之间传递的 record 按引用共享，字段契约仍然有效。接收方中的报错只使用授予名与结构描述，不显示定义方的函数名和类型标签。

被授予函数的参数名构成接收方可见的公开调用签名，可用于关键字参数；错误消息中的定义方参数名仍按脱敏规则隐藏。

授予或转授函数就是授予它可达的世界——包括捕获的 VM 值，接收方因此获得对它的 `terminate()`/`dispose()` 权限。只应授予允许子 VM 读取或修改其可达状态的函数。机制细节与设计不变量见[架构说明](architecture.zh-CN.md)不变量 13 与第 5.4 节。
