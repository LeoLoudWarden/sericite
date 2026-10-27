# Sericite-PY 宿主参考

[English](host-reference.md)

本文面向 **在 Python 中使用 Sericite-PY 的宿主程序**：创建和驱动 VM、配置配额、授予 FFI、读写虚拟文件、调试和处理错误。如果你写的是 **Sericite 脚本**，请读[语言参考](language-reference.zh-CN.md)；如果只是直接运行脚本或由 root Sericite 程序掌管应用流程，请读 [CLI 参考](cli-reference.zh-CN.md)，不必先写 Python 启动器。引擎内部的成本契约见[架构说明](architecture.zh-CN.md)。

## 1. 快速上手

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("""
name = input()
print("hello", name)
""")

output = vm.run(["world"])
assert output == "hello world\n"
```

`create_root()` 会编译源码并返回 `VMHandle`；句柄只能交给创建它的引擎驱动。VM 是相互隔离的工作空间，隔离承诺见[安全模型](security.zh-CN.md)第 2 节。

## 2. 引擎与配额

### 2.1 创建引擎和 root VM

```python
SericiteEngine(limits=None)
engine.create_root(
    source,
    inputs=None,
    input_provider=None,
    limits=None,
    functions=None,
    output_writer=None,
)
```

- `source`：Sericite 源码字符串，UTF-8 长度上限 4MB。
- `limits`：root 使用的 `SericiteLimits`。引擎构造时设置默认值；`create_root()` 再传时会替换该 root 的整套配置，而不是逐字段合并。
- `inputs`：预置输入字符串的可迭代对象，按顺序进入输入队列。
- `input_provider`：队列耗尽后调用的宿主函数，返回下一行字符串或 `None`。返回 `None`、抛出 `EOFError` 或 `StopIteration` 时，VM 进入 `waiting_input`。
- `functions`：授予脚本的宿主函数表，见第 5 节。
- `output_writer`：可选的宿主回调，root 每次写虚拟 stdout 后以文本块调用，便于实时转发。累计 stdout 与 `run()` 返回值不变；输出计量和上限仍先生效，子 VM 不继承该回调。

### 2.2 `SericiteLimits`

所有字段都有默认值；默认值面向开发调试，不是执行不可信代码时的安全建议。

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `max_instructions` | 1,000,000 | 指令及折算工作量上限 |
| `max_output_bytes` | 1,048,576 | stdout 的 UTF-8 字节上限 |
| `max_frames` | 100 | 调用帧上限 |
| `max_child_vms` | 100 | 单个 VM 的直接子 VM 上限 |
| `max_list_size` | 100,000 | 单列表槽位上限 |
| `max_dict_size` | 100,000 | 单字典项数上限 |
| `max_string_bytes` | 1,048,576 | 单字符串上限 |
| `max_int_bits` | 4096 | 整数位宽上限 |
| `max_total_bytes` | 67,108,864 | 近似内存总账高水位 |
| `max_total_vms` | 1000 | 引擎累计 VM 数上限，包括终态 VM |
| `max_vm_depth` | 8 | VM 嵌套深度上限 |
| `max_fs_files` | 1000 | 单 VM 文件数上限 |
| `max_fs_file_bytes` | 1,048,576 | 单文件 UTF-8 字节上限 |

脚本内创建子 VM 时只能继续收紧这些限制。指令、内存和子 VM 消耗按因果路由计入相关祖先。

## 3. 驱动 VM：`VMHandle`

### 3.1 方法一览

| 方法 | 用途与返回 |
|---|---|
| `run(inputs=None) -> str` | 驱动到完成、暂停或失败，返回 stdout；`inputs` 必须是字符串 list/tuple，整批验证后才入队 |
| `exec(source) -> str` | 向该 VM 投递新源码并在持久的模块作用域中执行；只返回本次投递产生的输出；见第 4 节 |
| `feed_input(value)` | 向队列加入一行输入；若 VM 正在等待输入，将其唤醒 |
| `step() -> dict` | 执行一条语句并返回快照 |
| `step_instruction() -> dict` | 执行一条内部指令并返回快照 |
| `snapshot() -> dict` | 返回当前安全快照，不推进执行 |
| `stdout() -> str` | 返回当前 stdout |
| `terminate()` | 将 `ready` 或 `waiting_input` 的 VM 标记为 `terminated` |
| `read_file(path) -> str` | 读取该 VM 的文本文件 |
| `write_file(path, text)` | 写入该 VM 的文本文件 |
| `list_dir(path) -> list[str]` | 列出目录的直接子项并排序 |
| `path_exists(path) -> bool` | 检查文件或目录是否存在 |

`run()` 在 VM 抛错时向宿主抛出 `SericiteError`。输入耗尽且没有更多提供者是正常暂停，不是异常。

### 3.2 宿主管理与脚本计费不是一回事

宿主是受信任的管理者：

- 直接 `feed_input()`、`write_file()`、读取文件、查看 stdout 或快照，不计入脚本的内存账；
- 文件数、单文件字节、输出字节等资源自身限制仍然有效；
- `run()`、`exec()`、`step()`、`step_instruction()` 所执行的 VM 指令和动态操作始终受 VM 配额约束。

不要把这条区别理解成“宿主调用会让 VM 免费执行”。它只表示：**宿主的管理动作不是脚本因果工作；VM 的实际执行仍然计量。**

## 4. 状态、快照与生命周期

VM 状态包括：`ready`、`waiting_input`、`done`、`error`、`resource_exhausted`、`terminated`。

快照包含：

| 字段 | 含义 |
|---|---|
| `vm_id` | 引擎内编号 |
| `state` | 当前状态 |
| `last_line` / `next_line` | 最近及下一条逻辑源码行 |
| `locals` | 用户可见局部值的安全副本 |
| `stdout` | 当前输出 |
| `error` | `kind`、`message`、`line`、`column`，无错误时为 `None` |
| `instruction_count` | 当前指令与工作量账 |

复杂值受节点和深度预算约束；环与共享结构使用占位符，不会指数展开。快照不包含可继续操作的子 VM 句柄或宿主对象。

`exec(source)` 让 VM 换上新程序但保留它的世界：新的模块帧复用先前的模块作用域，模块级名字（变量、函数、schema）因此持久，VFS、输入队列与授予的函数不受影响。除 `terminated` 与运行中之外，任何状态都接受投递；尚未执行完的程序（从未开始，或正暂停在输入上）会被丢弃，先前的错误被清除，旧的调试帧栈被替换——需要现场请先 `snapshot()`。编译先于任何状态改变完成，编译失败的源码让 VM 保持原样。配额是生命周期预算：指令、内存与输出消耗跨投递累计，而非按投递计算。

VM 终态后，引擎仍保留上下文供调试。上下文由引擎统一持有，`max_total_vms` 限制累计数量；不再需要整棵 VM 树时，应释放整个引擎。

## 5. FFI：向 VM 授予宿主能力

### 5.1 授予函数

```python
def double(value):
    return value * 2

engine = SericiteEngine()
vm = engine.create_root(
    "print(double(21))",
    functions={"double": double},
)
assert vm.run() == "42\n"
```

授予名必须是合法标识符，不能以 `__` 开头，也不能与内建名冲突。值必须可调用。创建 root 时会统一验证整张函数表。

### 5.2 数据边界

参数和返回值在宿主与 VM 之间双向深拷贝，只允许递归纯数据：

- `None`、`bool`、`int`、`float`、`str`；
- `list`、`dict`；宿主返回的 tuple 会转成 list；
- dict 键同样受类型白名单约束。

record/schema、VM 句柄、函数及其他宿主对象不能越界。需要传递 record 时，先在脚本内 `unwrap()` 成 dict。容器大小、字符串、整数位宽、总节点数和嵌套深度都有限制，复制工作本身按节点计入引擎配额。

### 5.3 异常与重入

- FFI 异常契约：行为良好的宿主回调要么返回结果，要么抛契约 kind 的 `SericiteError`（`file_not_found`、`runtime_error` 等）——语义是"我还活着，这个活干不了"。`SericiteError` 按原样传播，脚本可按 kind 捕获，因此其消息由宿主自行保证不含秘密。
- 回调抛出契约**之外**的任何 `Exception` 都视为治理失败：其内部状态不再可信。引擎让当前 VM 以**不可捕获**的 `host_error` 终止，消息只含宿主异常的类型名，绝不含异常文本，控制权交还宿主。
- 脚本无法捕获这类失败——裸 `except:` 也不行——也无法借它探测宿主异常类型。请在回调内部捕获自己的异常，把脚本可见的失败翻译成契约 kind。
- `SystemExit`、`KeyboardInterrupt` 等其他 `BaseException` 是发给宿主的进程级事件：原样穿透 `run()` 上抛。不要授予其依赖库会在对抗输入路径上调用 `sys.exit()` 的函数——这与"不要授予能被驱动着删文件的函数"是同一条纪律。
- 不要在回调中对同一 VM 再调用 `run()`、`step()` 或其他重入驱动；引擎会拒绝嵌套调度。

### 5.4 成本责任

**宿主 callback 内部的 CPU、内存、阻塞和外部副作用不由引擎计量。** 引擎只负责调用派发及边界复制的成本。

因此 FFI 是显式信任承诺：请自行验证参数、限制输入规模、调用频率和外部资源。不要授予不必要的网络、文件或秘密访问能力。

## 6. 嵌套 VM 与授予语义

脚本可以用 `VM(code, **limits)` 创建子 VM，也可以用 `functions={"name": fn}` 把 Sericite 函数或已有授予函数继续授予下一层。

- 被授予函数保留定义方的模块变量、闭包和已授予环境；
- `print`、VFS、子 VM 创建等世界服务仍解析回定义方（home）；
- 函数体在调用方帧栈执行；
- 世界服务和目标执行由 home/target 与 caller 的联合因果路由约束，共享祖先只计一次；
- 返回值的所有权进入实际调用方。

授予或转授函数就是授予它可达的世界。VM 句柄本身不能通过 FFI 传给宿主。机制细节与设计不变量见[架构说明](architecture.zh-CN.md)不变量 13 与第 5.4 节。

## 7. 宿主错误处理

```python
from sericite import SericiteError

try:
    vm.run()
except SericiteError as exc:
    print(exc.kind, exc.message, exc.filename, exc.line, exc.column)
```

`resource_exhausted`、`internal_error` 与 `host_error` 只是不能被 **Sericite 脚本** 捕获；宿主可以且应该处理它们。语法、校验、运行时和 FFI 错误的 `kind` 注册表见[语言参考](language-reference.zh-CN.md)。

## 8. 不可信代码的宿主检查清单

- 为每层 VM 显式收紧配额，不依赖默认值。
- 生产环境增加独立进程、容器等 OS 级隔离，不把同进程 Python 引擎当作唯一边界。
- 只授予必要的 FFI，并在能力内部做参数、频率和外部资源限制。
- 宿主预置和管理走公开 `VMHandle` API；不要把内部上下文或私有实现对象暴露给不可信 Python。
- 调试快照和异常可以交给上层使用，但仍应避免把宿主自己的秘密写进 `SericiteError`。
