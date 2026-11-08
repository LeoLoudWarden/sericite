# Sericite 虚拟机参考

[English](vm-reference.md)

本文面向**需要创建和驱动 VM 的读者**：在 Sericite 脚本里创建子 VM，或经宿主 API 驱动任意 VM。VM 的状态、驱动方法、exec 投递、配额与函数授予的契约都在这里。

脚本内的 VM 值与宿主侧的 `VMHandle` 提供同一组驱动方法，驱动语义相同；下文统一用 `sub.` 书写，宿主侧换成自己的句柄变量即可。有一处刻意的不对称：宿主侧拿到的快照带有额外的宿主专属诊断字段（§4）。

## 1. VM 是什么

VM 是相互隔离的工作空间：看不到父级的变量、文件和句柄，也不知道自己嵌套在第几层。每台 VM 有独立的模块作用域、虚拟文件系统、输入队列与 stdout；隔离承诺见[安全模型](security.zh-CN.md)第 2 节。

VM 不是一次性的：同一台 VM 可以喂输入、预置和读取文件、逐语句或逐指令单步、查看快照、投递新源码继续执行，或随时终止。

## 2. 创建 VM

脚本内用 `VM(code, **options)` 创建子 VM：

```python
sub = VM(code, max_instructions=10000)   # 资源配额，只能比当前环境更严
sub = VM(code, output_writer=forward, buffer_output=False)
```

`output_writer` 与 `buffer_output` 配置该 VM 的输出，`functions` 用于授予函数（第 6 节），其余选项为配额字段。输出转发见第 4 节，配额见第 5 节。

root VM 不由脚本创建：直接运行程序时由 CLI 创建（见 [CLI 参考](cli-reference.zh-CN.md)）；嵌入 Python 时由 `SericiteEngine.create_root()` 创建（见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)）。

## 3. 状态与生命周期

VM 状态包括：`ready`、`waiting_input`、`done`、`error`、`resource_exhausted`、`terminated`。

`terminate()` 只把 `ready` 或 `waiting_input` 的 VM 标记为 `terminated`；其他状态下是静默空操作——`done`/`error` 等终态 VM 仍可被 `exec` 投递。

VM 上下文是资源，VM 句柄是指向它的能力值。只要句柄或授予环境仍可达，上下文就会保留；终态 VM 因此仍能用于调试快照和后续 `exec` 投递。

当一台 VM 及其所有可达对象构成不可达的引用岛时（包括经授予函数形成的自引用或跨 VM 循环），垃圾回收会最终自动销毁它。自动回收不保证在某个语句或作用域边界立即发生；需要确定释放时点时仍应显式调用 `dispose()`。

`dispose()` 可以销毁任意状态的 VM，包括正在运行或等待输入的 VM；它会终止并注销目标及其所有存活后代，不要求子先父后。它会：

- 立即释放目标及其所有存活后代占用的 `max_total_vms` 槽位；
- 让正在运行的目标在当前指令安全退出后停止，不执行目标脚本的 `finally`；
- 幂等——重复释放是空操作；
- 使句柄失效——已释放句柄上的其他方法以 `runtime_error` 失败。

函数的 home 是它所属世界所在的那台 VM。该 VM 被销毁后，从它逃逸到其他子树的函数——包括授予给它的宿主函数——也会失效；调用时以可捕获的 `runtime_error` 失败，不会暴露宿主内部错误。授予语义见第 6 节；内部规则见[架构说明](architecture.zh-CN.md)第 5.4 节。

脚本内 `dispose()` 只计入实际 caller、不计入待销毁 target，配额不足时在变更前失败；完整计费模型见[架构说明](architecture.zh-CN.md)第 5.4 节。

`vm_id` 永不复用，父级的累计指令/内存账本与 `child_count` 也不会退还。

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
| `read_file(path) -> str` | 读取该 VM 的文本文件 |
| `write_file(path, text)` | 写入该 VM 的文本文件 |
| `delete_file(path)` | 删除文件并清理为空的隐式目录 |
| `rename_file(old_path, new_path)` | 重命名或移动文件；拒绝覆盖已有文件 |
| `copy_file(source_path, destination_path)` | 复制文件；拒绝覆盖已有文件 |
| `make_dir(path)` | 显式创建目录及缺失父目录；空目录会持续存在 |
| `delete_dir(path)` | 递归删除整个目录树 |
| `rename_dir(old_path, new_path)` | 递归移动目录树；拒绝覆盖或移入自身 |
| `copy_dir(source_path, destination_path)` | 递归复制目录树；拒绝覆盖或复制到自身内部 |
| `list_dir(path) -> list[str]` | 列出目录的直接子项并排序 |
| `path_exists(path) -> bool` | 检查文件或目录是否存在 |

```python
sub = VM(code, max_instructions=10000)
sub.write_file("/input.txt", "数据")      # 预置文件给它
sub.feed_input("一行输入")                # 喂 input()
out = sub.run()
print(sub.read_file("/result.txt"))       # 取回它写的文件
```

推荐工作流：运行前预置文件与输入，运行后读取结果。

输入耗尽且没有更多提供者是正常暂停（`waiting_input`），不是异常；输入源显式报告关闭（`input_error`）则走普通可捕获错误路径。执行失败时，宿主侧的 `run()` 向宿主抛出 `SericiteError`；脚本内的 `sub.run()` 把子 VM 的错误按原 kind 传播给调用脚本，可捕获的 kind 仍可正常捕获。

子 VM 因配额耗尽进入 `resource_exhausted` 终态后，父 VM 可以捕获该错误；父 VM 自身或祖先的配额错误仍不可捕获。脚本可见的完整规则见[语言参考](language-reference.zh-CN.md)第 5 节。

终态 VM 仍可被操作，但两类方法的行为不同：

- 不驱动该 VM 的方法（`snapshot`、`step`、`step_instruction`、VFS 读取等）仍然可用；在终态 VM 上，`step`/`step_instruction` 只返回快照；
- 写入或驱动方法（`write_file`、`delete_file`、`rename_file`、`copy_file`、`make_dir`、`delete_dir`、`rename_dir`、`copy_dir`、`feed_input`、带输入的 `run`、`exec` 等）可能因该 VM 已耗尽的配额而失败。

计费模型（哪些操作由谁计量）见[架构说明](architecture.zh-CN.md)第 5.4 节。

### 输出转发与缓冲

每台 VM 都有独立的 `output_writer` 与 `buffer_output` 配置。子级 writer 由父级显式配置，不会隐式继承：

```python
def forward(text):
    print(text, end="")

sub = VM('print("live")', output_writer=forward)
```

writer：

- 在每次 `print()` 完成输出计量和缓冲后接收一个字符串；
- 遵循授予函数语义：在实际 caller 的帧栈上执行并受其与祖先的配额约束，同时保留定义侧的模块变量、闭包、授予环境和 IO；
- 调用父级 `print()` 时，输出因此继续沿父级配置链转发；
- 返回值被忽略，异常按普通规则在触发它的 `print()` 处传播；
- 必须同步完成——若试图通过 `input()` 暂停，会在该 `print()` 处抛出 `runtime_error`。

默认 `buffer_output=True`，为 `run()`/`exec()`/`stdout()` 和快照保留完整 stdout。设为 `False` 后，输出仍计量并转发，但不再保留，上述缓冲输出视图为空。输出与 writer 配置跨 `exec` 投递保留。

### exec：向既有 VM 投递新源码

`exec(source)` 让 VM 换上新程序但保留它的世界：

- **保留的世界**：新的模块帧复用先前的模块作用域，模块级名字（变量、函数、schema）因此持久；VFS、输入队列与授予的函数不受影响。
- **状态与丢弃规则**：除 `terminated` 与正被驱动（`run()`/`exec()`/`step()` 进行中）之外，任何状态都接受投递。尚未执行完的程序（从未开始，或正暂停在输入上）会被丢弃，先前的错误被清除，旧的调试帧栈被替换——需要现场请先 `snapshot()`。
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

复杂值受节点和深度预算约束；环与共享结构使用占位符，不会指数展开。快照不包含可继续操作的子 VM 句柄或宿主对象。

`error.frames` 是该 VM 的调用栈。每项是 `{"function": str, "line": int | None}`；栈顺序与行号脱敏规则同脚本异常 record，见[语言参考](language-reference.zh-CN.md)第 5 节。

在宿主侧（`VMHandle` 上）调用这些方法时，返回的字典是上述安全视图的严格超集，额外带有宿主专属诊断字段：

| 字段 | 含义 |
|---|---|
| `vm_id` | 引擎内编号 |
| `parent_id` | 父 VM 的引擎内编号；根为 `None` |
| `depth` | 嵌套深度；根为 0 |
| `child_count` | 累计创建的直接子 VM 数 |

脚本自己的调用永远只返回上面的安全视图，无法看到这些字段。

## 5. 配额

每台 VM 的资源配额由下列字段定义。所有字段都有默认值；默认值面向开发调试，不是执行不可信代码时的安全建议。

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `max_instructions` | 1,000,000 | 指令及折算工作量上限 |
| `max_output_bytes` | 1,048,576 | stdout 的 UTF-8 字节上限 |
| `max_frames` | 100 | 调用帧上限 |
| `max_list_size` | 100,000 | 单列表槽位上限 |
| `max_dict_size` | 100,000 | 单字典项数上限 |
| `max_string_bytes` | 1,048,576 | 单字符串上限 |
| `max_int_bits` | 4096 | 整数位宽上限 |
| `max_total_bytes` | 67,108,864 | 近似内存总账高水位 |
| `max_total_vms` | 1000 | 引擎同时存活且尚未销毁的 VM 数上限，包括 root；销毁后释放槽位 |
| `max_descendant_vms` | 1000 | 单台 VM 的整棵子树中同时存活的后代数上限，不含自身；销毁后释放槽位 |
| `max_vm_depth` | 8 | VM 嵌套深度上限 |
| `max_fs_files` | 1000 | 单 VM 文件数上限 |
| `max_fs_file_bytes` | 1,048,576 | 单文件 UTF-8 字节上限 |

`max_string_bytes` 因历史原因以此命名，但实际按单字符串的字符数计算；文件和输出配额按 UTF-8 字节计算。

只有累计字段 `max_instructions`、`max_output_bytes`、`max_total_bytes` 接受用 `-1` 表示不设上限。包括存活数量字段 `max_total_vms`、`max_descendant_vms` 在内的其余字段都是结构性配额，必须是非负有限整数；所有字段都拒绝其他负数和非整数值。

创建 VM 时会检查所有祖先的 `max_descendant_vms`，因此无论按何种树形结构创建子 VM，都无法绕过某一层限制。不可信子 VM 达到自己的后代上限后以 `resource_exhausted` 终止，仍存活的父级可以捕获；`max_total_vms` 继续作为整个引擎的全局防线。

直接子级配额 `max_child_vms` 已移除。需要禁止某台 VM 创建任何后代时，将它自己的 `max_descendant_vms` 设为 `0`；这不影响父级创建该 VM。

脚本内创建子 VM 时，`VM()` 的配额关键字参数与上表一一对应，只能收紧不能放宽。请求值与继承上限合并时：

- 请求 `-1` 会继承父级有效值；
- 无限父级下的有限请求采用该有限上限；
- 只有两侧都无限才得到无限，因此有限祖先始终是硬上限。

授予函数合并 home 与 caller 配额时也遵守同一规则。

无限只跳过上限检查，不跳过记账：诊断账本继续增长。

指令、内存和子 VM 消耗按因果路由计入相关祖先。计费模型见[架构说明](architecture.zh-CN.md)第 5 节；Python 宿主经 `SericiteLimits` 为 root 配置同一组字段，见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)第 3 节。

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
- `print`、VFS、子 VM 创建等世界服务仍解析回定义方（home）；
- 函数体在调用方帧栈执行；
- 世界服务和目标执行由 home/target 与 caller 的联合因果路由约束，共享祖先只计一次；
- 返回值的所有权进入实际调用方。

被授予函数的参数名构成接收方可见的公开调用签名，可用于关键字参数；错误消息中的定义方参数名仍按脱敏规则隐藏。

授予或转授函数就是授予它可达的世界——包括捕获的 VM 句柄，接收方因此获得对它的 `terminate()`/`dispose()` 权限。只应授予允许子 VM 读取或修改其可达状态的函数。VM 句柄本身不能通过 FFI 传给宿主。机制细节与设计不变量见[架构说明](architecture.zh-CN.md)不变量 13 与第 5.4 节；宿主向 root 授予 Python 函数（FFI）见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)第 5 节。
