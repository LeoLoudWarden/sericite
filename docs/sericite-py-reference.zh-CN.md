# Sericite-PY 参考

[English](sericite-py-reference.md)

本文面向**在 Python 中使用 `sericite` 库的宿主程序**：创建引擎与 root VM、配置配额、授予 FFI、处理错误。Sericite-PY 是 Sericite 语言的 Python 参考实现——语言本身不依赖 Python。

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

`create_root()` 会编译源码并返回 `VMHandle`；句柄只能交给创建它的引擎驱动。

## 2. 创建引擎与 root VM

```python
SericiteEngine(limits=None)
engine.create_vfs() -> VFSHandle
engine.create_root(
    source,
    inputs=None,
    input_provider=None,
    limits=None,
    functions=None,
    output_writer=None,
    buffer_output=True,
    argv=None,
    fs=None,
)
```

- `source`：Sericite 源码字符串，UTF-8 长度上限 4MB。
- `limits`：root 使用的 `SericiteLimits`，见第 3 节。
- `inputs`：预置输入字符串的可迭代对象，按顺序进入输入队列。
- `input_provider`：队列耗尽后调用的宿主函数，返回下一行字符串或 `None`。返回 `None`、抛出 `EOFError` 或 `StopIteration` 时，VM 进入 `waiting_input`；要报告输入源永久关闭，抛出 `SericiteError(kind="input_error")`，脚本可以捕获。
- `functions`：授予脚本的宿主函数表，见第 5 节。
- `output_writer`：可选的宿主回调，root 每次写虚拟 stdout 后以文本块调用，便于实时转发。输出计量和上限仍先生效，子 VM 不继承该回调。
- `buffer_output`：是否在内存中保留 root stdout，默认 `True`。设为 `False` 时不保留缓冲输出，可避免长期 root 无限保留历史输出；完整语义见[虚拟机参考](vm-reference.zh-CN.md)第 4 节。
- `argv`：root 模块初始 `argv` 列表的字符串可迭代对象；缺省为空列表。引擎复制该列表，后续不与宿主共享变更；`argv` 不能用作授予名。其语义见 [CLI 参考](cli-reference.zh-CN.md)第 2 节。
- `fs`：可选的分离状态 `VFSHandle`。`engine.create_vfs()` 创建独立工作区；`create_root(..., fs=fs)` 成功后才移动所有权，失败时句柄仍可使用。终态 VM 的 `take_fs()` 返回新的分离句柄。

参数类型错误在 API 边界报 `type_error`。root 参数校验先于 VM 创建，失败不会注册 VM；`limits` 可以是 `None` 或 `SericiteLimits`，`fs` 必须属于同一引擎且未被消费。

## 3. 配额：SericiteLimits

`SericiteLimits` 的字段清单与默认值见[虚拟机参考](vm-reference.zh-CN.md)第 5 节；脚本内 `VM()` 的配额关键字参数与之一一对应。所有字段都有默认值；默认值面向开发调试，不是执行不可信代码时的安全建议。

引擎构造时设置默认配额；`create_root()` 再传 `limits` 时会替换该 root 的整套配置，而不是逐字段合并。

对于可信、长期运行的 root，累计配额可用 `-1` 表示不设上限（具体字段及合并、继承规则见[虚拟机参考](vm-reference.zh-CN.md)第 5 节）；存活 VM 数及其他结构性配额必须保持有限。

`-1` 是显式的信任决定，只用于你掌控的代码。无限配额对资源安全的含义与边界见[安全模型](security.zh-CN.md)第 3 节。

## 4. 驱动 VM 与管理 VFS

`VMHandle` 的驱动方法（`run`/`exec`/`step`/快照/`take_fs`/`dispose` 等）与脚本内 VM 值共享状态与契约，见[虚拟机参考](vm-reference.zh-CN.md)第 3、4 节。宿主可以在两段会话之间持有并管理工作区：

```python
from sericite import SericiteEngine

engine = SericiteEngine()
fs = engine.create_vfs()
fs.write_file("/input.txt", "hello")
vm = engine.create_root(
    "write_file('/output.txt', read_file('/input.txt') + '!')",
    fs=fs,
)
vm.run()
fs = vm.take_fs()
assert fs.read_file("/output.txt") == "hello!"
vm.dispose()
```

宿主 `VMHandle` 的文件方法操作当前依附的 VFS，`VFSHandle` 的同名方法操作分离工作区。两者都是可信宿主管理通道，不是脚本侧 VM 文件代理；脚本只能操作当前会话的 VFS 或分离句柄。路径、目录与公开错误语义见[语言参考](language-reference.zh-CN.md)第 6 节。

宿主侧快照是脚本安全视图的严格超集，额外包含：

| 字段 | 含义 |
|---|---|
| `vm_id` | 引擎内编号；永不复用 |
| `parent_id` | 父 VM 的引擎内编号；root 为 `None` |
| `depth` | 嵌套深度；root 为 0 |
| `child_count` | 累计创建的直接子 VM 数；销毁子 VM 不会减少 |

脚本调用只能取得安全视图，不能看到这些宿主字段。

宿主侧还有一条特权规则——宿主管理不计入脚本账：

- 直接 `feed_input()`、通过 `VMHandle`/`VFSHandle` 读写文件、查看 stdout 或快照、`dispose()`，不计入脚本的内存账；
- 文件数、单文件字节、文件总存储量、输出字节等资源自身限制仍然有效；
- `run()`、`exec()`、`step()`、`step_instruction()` 所执行的 VM 指令和动态操作始终受 VM 配额约束。

不要把这条区别理解成"宿主调用会让 VM 免费执行"。它只表示：**宿主的管理动作不是脚本因果工作；VM 的实际执行仍然计量。**脚本计量模型见[架构说明](architecture.zh-CN.md)第 5 节。

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
- `list`、`dict`、`tuple`；两个方向都保留 list/tuple 类型；
- dict 键同样受类型白名单约束。

record/schema、模块对象、VM/VFS 句柄、函数及其他宿主对象不能越界；尝试这样做会报 `ffi_error`。需要传递 record 时，先在脚本内 `unwrap()` 成 dict。容器大小、字符串、整数位宽、总节点数和嵌套深度都有限制，复制工作本身按节点计入引擎配额。

### 5.3 异常与重入

- FFI 异常契约：行为良好的宿主回调要么返回结果，要么抛契约 kind 的 `SericiteError`（`file_not_found`、`runtime_error` 等）——语义是"我还活着，这个活干不了"。`SericiteError` 按原 kind 传播，是否可捕获遵守语言规则；普通可捕获 kind 可由脚本按 kind 处理，因此其消息由宿主自行保证不含秘密。
- `resource_exhausted` 是特殊情况：宿主回调直接抛出它时，引擎视为该 VM 自身的配额耗尽——VM 进入 `resource_exhausted` 终态，脚本不可捕获。若这类失败应当允许脚本恢复，请在回调内改抛 `runtime_error`、`ffi_error` 等普通契约 kind。
- 回调抛出契约**之外**的任何 `Exception` 都视为治理失败：其内部状态不再可信。引擎让当前 VM 以**不可捕获**的 `host_error` 终止，消息只含宿主异常的类型名，绝不含异常文本，控制权交还宿主。
- 脚本无法捕获这类失败——裸 `except:` 也不行——也无法借它探测宿主异常类型。请在回调内部捕获自己的异常，把脚本可见的失败翻译成契约 kind。
- `SystemExit`、`KeyboardInterrupt` 等其他 `BaseException` 是发给宿主的进程级事件：原样穿透 `run()` 上抛。不要授予其依赖库会在对抗输入路径上调用 `sys.exit()` 的函数——这与"不要授予能被驱动着删文件的函数"是同一条纪律。
- 不要在回调中对同一 VM 再调用 `run()`、`step()` 或其他重入驱动；引擎会拒绝嵌套调度。

### 5.4 成本责任

**宿主 callback 内部的 CPU、内存、阻塞和外部副作用不由引擎计量。** 引擎只负责调用派发及边界复制的成本。

因此 FFI 是显式信任承诺：请自行验证参数、限制输入规模、调用频率和外部资源。不要授予不必要的网络、文件或秘密访问能力。

## 6. 宿主错误处理

```python
from sericite import SericiteError

try:
    vm.run()
except SericiteError as exc:
    print(exc.kind, exc.message, exc.filename, exc.line, exc.column)
    for frame in exc.frames:
        print(frame.function, frame.line)
```

`exc.frames` 是错误最初发生的那台 VM（首个捕获到调用栈的 VM）的调用栈，类型为 `tuple[SericiteFrame, ...]`；顺序与脱敏规则同脚本异常 record，见[语言参考](language-reference.zh-CN.md)第 5 节。

每帧是一个 `SericiteFrame`——与 `SericiteError` 一样从 `sericite` 顶层导入：

- `function`：`str`，函数名；
- `line`：`int | None`，行号；帧来自其他 VM 时脱敏为 `None`。

各 VM 快照的 `error.frames` 对应该快照所属 VM，但形态不同：它是 dict 列表（`{"function": str, "line": int | None}`），不是 `SericiteFrame` 对象。编译期尚未进入 VM 执行的错误没有调用栈。

`resource_exhausted` 的脚本侧可捕获规则（仅当来自 `VM()` 隔离的代码时可捕获）与 `kind` 注册表见[语言参考](language-reference.zh-CN.md)第 5 节。文件操作约束拒绝改用普通、可捕获的 `file_limit_error`；`internal_error` 与 `host_error` 始终不能被脚本捕获。宿主可以且应该处理 `resource_exhausted`、`internal_error` 与 `host_error`。

## 7. 不可信代码的宿主检查清单

- 为每层 VM 显式收紧配额，不依赖默认值。
- 生产环境增加独立进程、容器等 OS 级隔离，不把同进程 Python 引擎当作唯一边界。
- 只授予必要的 FFI，并在能力内部做参数、频率和外部资源限制。
- 宿主预置和管理走公开 `VMHandle`/`VFSHandle` API；不要把内部上下文或私有实现对象暴露给不可信 Python。
- 调试快照和异常可以交给上层使用，但仍应避免把宿主自己的秘密写进 `SericiteError`。
