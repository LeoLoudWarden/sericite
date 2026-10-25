# Sericite 架构说明

本文描述 Sericite-PY（Python 参考实现）的内部结构与当前实现状态。设计理念见 [design](design.zh-CN.md)；语言行为见[语言参考](language-reference.zh-CN.md)；安全边界见[安全模型](security.zh-CN.md)。

## 1. 执行管线

```text
源码 → ast.parse → 节点白名单校验 → 编译为内部指令流 → 引擎调度循环逐指令执行
```

全程不使用 `exec`/`eval`。源码执行天然经过统一的计量、IO 与调试控制面，而不是"禁用了几个危险名字"。

## 2. 模块结构

| 模块 | 职责 |
|---|---|
| `isa` | 指令、代码单元与异常 handler 表定义（栈式虚拟机） |
| `compiler` | AST 白名单与 except kind 校验 + 编译为指令流（唯一源码入口）；含静态栈深度分析，保证异常捕获时栈可安全截断 |
| `engine` | 调度循环、帧/求值栈、运算语义、异常展开（跨帧/跨 VM）、内建函数、VM 生命周期、资源配额、调试快照 |
| `vfs` | 单 VM 私有虚拟文件系统（纯内存、纯文本；平坦路径字典，目录隐式） |
| `io` | 每个 VM 独立的虚拟输入与输出（含输出字节上限） |
| `errors` | `SericiteError` 与集中管理的错误 kind 注册表 |
| `cli` / `__main__` | 命令行入口 |

## 3. 设计不变量

修改引擎时必须保持以下不变量（编号仅为引用方便）：

1. 所有 VM 必须由同一个 `SericiteEngine` 直接执行，不能为每个层级再套一层解释器。嵌套 VM 只是同一引擎里的另一个执行上下文，这是"创建子 VM 便宜"的结构基础（实测见 [benchmarks/vm_creation.py](https://github.com/LeoLoudWarden/sericite/blob/main/benchmarks/vm_creation.py)）。
2. 子 VM 不得隐式读取父级或宿主 stdin，也不得直接向宿主 stdout 写入；子 VM 的文件系统默认全新空白，不共享父级任何文件。
3. 子 VM 默认不能取得父级局部变量、父级句柄、宿主对象或 Python 反射入口。
4. 脚本能力通过受控原生函数和 VM 句柄方法提供，不能暴露任意 Python 属性。
5. 执行必须经由内部指令流与统一调度循环；`run()`、`step()`、`step_instruction()` 共享同一条执行路径，不允许旁路执行语义。
6. 新语法必须先过编译器白名单，再编译为指令；禁止为了省事引入 `exec`/`eval`。
7. 错误和调试视图只能包含逻辑源码位置及安全值，不能默认透传宿主 traceback 或真实路径；脚本无法感知自己的 VM 嵌套深度。
8. 新增能力时同步考虑隔离、资源记账、生命周期和调试语义，不只做语法可运行。资源消耗必须在指令层可计量；子 VM 的消耗必须计入祖先。
9. Sericite 值语义由引擎助手函数定义，不直接继承 Python 运算符的隐式行为（如 bool 不参与算术）。
10. `resource_exhausted` 与 `internal_error` 不可被脚本 try/except 捕获——配额不能被脚本吞掉。
11. VM 句柄方法白名单只有一个来源（编译器侧定义），引擎侧引用它，两边不得分叉。
12. 宿主边界（FFI）必须双向深拷贝 + 类型白名单（None/bool/int/float/str/list/dict 递归）：句柄、函数、record/schema、宿主原生对象一律不得越界；宿主异常必须净化为 `ffi_error`，消息只含宿主异常的类型名，不含异常文本（防宿主路径/内部信息泄漏）。VM 之间的函数授予在同一引擎信任域内按引用传递，不拷贝。
13. 授予的 sericite 函数执行在**调用方 VM 的帧栈**上（指令计入调用方及祖先），但保留**定义方函数的闭包 cell、定义方 VM 的模块变量、定义方已持有的授予函数环境，以及定义方 VM 的内建服务**（IO/文件系统/子 VM 创建均解析回定义 VM，即函数的 home）；反过来或交叉的组合都不允许。再次授予时必须完整保留这些定义方环境。
14. 一切会增长的资源都必须有配额（见下节）。`run()` 不做逐语句快照——快照只在显式 `step()/snapshot()` 时生成，调试路径不得成为资源旁路。宿主 `RecursionError` 一律转换为 `resource_exhausted`，`OverflowError` 转换为 `conversion_error`；宿主异常不得以原生形态泄漏给脚本或调用方。O(n) 及以上的操作必须按规模折价计入指令配额，新建对象必须记账。授予函数触发的世界服务消耗归属定义 VM（home），但必须同时按因果镜像计入触发它的调用方（镜像止于 home，不与原记账重复）；授予函数创建的子 VM 是空世界，其树位置（父级/深度/子计数）按因果挂在触发它的调用方下，配额取 home 与调用方的逐项最小值。
15. 调度入口有重入保护：同一 VM 不得被两个调度循环同时驱动（例如宿主在 `input_provider`/FFI 回调里对同一 VM 再调 `step()`）。
16. 跨 VM 的只有结构：record/schema 不携带名字（schema 相等按字段集与契约的结构比较）；类名、注解名等标签是编译期、作用域本地的诊断数据，只烘焙进本层 CodeUnit 的指令与元数据，出作用域即失效。外来代码（`origin_vm` 不同的 CodeUnit）在当前 VM 的报错——属性 hint、参数/返回契约、参数数量——一律退为结构描述与授予名，定义方的函数名、类型标签、参数名（以位置序号替代）不得出现。新增值形式或跨层通道时，必须同样保证名字不随值越层。

## 4. 脚本接口

内建函数：

- `input()`：读取当前 VM 的一行输入。
- `print(value, ...)`：写入当前 VM 的 stdout 缓冲区。
- `len(x)`、`int(x)`、`float(x)`、`str(x)`、`range(...)`。
- `read_file(path)`、`write_file(path, text)`、`list_dir(path)`、`path_exists(path)`：操作本 VM 的私有文件系统（仅文本）。
- `VM(code, **limits)`：创建子 VM，可选资源配额参数（只能收紧）；特殊参数 `functions={name: fn}` 向子 VM 授予函数（sericite 函数或已持有的授予函数）。
- 宿主注入：`SericiteEngine.create_root(source, functions={name: python_callable})` 向 root VM 授予宿主函数。

容器方法：list `append`/`pop`；dict `keys`/`values`/`get`/`pop`。采用封闭的原生分发，不暴露任意 Python 属性。追加元素计入新列表槽；键/值快照按 O(n) 工作量与列表分配记账。

VM 句柄可用方法（脚本内与宿主侧一致）：`run(inputs)`、`feed_input(text)`、`step()`、`step_instruction()`、`snapshot()`、`stdout()`、`terminate()`，以及 `read_file` / `write_file` / `list_dir` / `path_exists`（配置/读取该 VM 的文件系统）。

VM 状态：`ready`、`waiting_input`、`done`、`error`、`resource_exhausted`、`terminated`。

错误分类：`runtime_error`、`syntax_error`、`validation_error`、`type_error`、`zero_division`、`conversion_error`、`index_error`、`key_error`、`name_error`、`arity_error`、`raise_error`、`file_not_found`、`is_directory`、`not_directory`、`ffi_error`、`input_error`、`attribute_error`、`contract_error`、`resource_exhausted`、`internal_error`。`errors` 模块是这些 kind 的单一注册表。除 `resource_exhausted`/`internal_error` 外均可被 try/except 按 kind 过滤捕获；编译器将未知过滤名字拒绝为 `validation_error`。

## 5. 资源配额

配额由 `SericiteLimits` 定义：`max_instructions`、`max_output_bytes`、`max_frames`、`max_child_vms`、`max_list_size`、`max_dict_size`、`max_string_bytes`、`max_int_bits`、`max_total_bytes`、`max_total_vms`、`max_vm_depth`、`max_fs_files`、`max_fs_file_bytes`。

规则：

- 子 VM 默认继承父 VM 配额，`VM()` 参数只能收紧。
- 源码总长度固定上限 4MB（按 UTF-8 字节计）。
- 除指令条数外，大体量操作（容器比较/成员判断、拼接、序列化、编译子 VM 源码、VM 方法返回值）按规模折价计入 `instruction_count`。
- 闭包 cell 与捕获环境计入 `max_total_bytes`；快照只暴露用户可见的值，不暴露内部 cell 对象。
- 子 VM 的指令与内存分配计入所有祖先，祖先链上任一环超限即失败。

## 6. 实测性能

以下最近一次实测均使用 Intel i3-9100、Linux x86_64。指令与调试数据来自 2026-10-23 的 CPython 3.13.13；VM 创建数据沿用复现脚本中记录的 CPython 3.13/3.14 结果。所有数值均为多轮测试的中位数。

| 操作 | 实测成本 | 复现脚本 |
|---|---:|---|
| 脚本内创建子 VM | ~50 µs/VM | [vm_creation.py](../benchmarks/vm_creation.py) |
| 宿主侧创建并运行 root VM | ~42 µs/VM | [vm_creation.py](../benchmarks/vm_creation.py) |
| 用 `run()` 执行代表性计数循环 | ~0.65 µs/指令 | [instruction.py](../benchmarks/instruction.py) |
| 用 `step_instruction()` 执行同一循环 | ~1.86 µs/指令（`run()` 的 2.92 倍） | [debugging.py](../benchmarks/debugging.py) |
| 用 `step()` 执行同一循环 | ~4.91 µs/次调用（约 1.09 µs/指令） | [debugging.py](../benchmarks/debugging.py) |

指令成本是该工作负载的加权平均值，不代表每种 opcode 都有相同成本，且不含 VM 创建与编译。单步数据包含逐步控制以及每步生成安全快照的成本，测试工作负载只有一个简单局部变量。这些数字是 Python 原型的实测结果，不是性能承诺；引擎变更后需要重新测量。

## 7. 当前原型能力概览

- 内建类型：int、float、str、bool、None、list、dict；运算符、比较、成员判断、短路逻辑。
- record 与 schema：`class` 定义运行期结构契约（字段 + 每字段契约），点号成员访问，形状固定，`wrap`/`unwrap` 与 dict 互转；注解（参数/返回值/带注解赋值）作为运行期契约真实执行，含 blame 式报错；类名/注解名是仅用于报错文本的编译期标签。
- 控制流：`if/elif/else`、`while`、`for`、`break/continue`、`try/except/else/finally`、`raise`、三元表达式。
- 函数：定义、递归、位置与关键字参数、默认参数、装饰器、独立调用帧、按引用捕获的词法闭包。
- VM 套 VM：任意层可创建子 VM，子 VM 不感知层深；父 VM 可给子 VM 预置文件、喂输入、单步调试（语句级与指令级）、快照、终止。
- 能力授予（FFI）：宿主向 root VM 注入函数，任意层 VM 向下一层授予函数；跨宿主边界双向深拷贝、纯数据类型白名单。
- 资源治理：见上节。原型经过一轮对抗性安全审查（含独立第三方视角），审查发现的拒绝服务与信息泄漏路径均已修复并固化回归测试。
- 每个 VM 自带私有虚拟文件系统，可在运行前配置、运行后取回产出。

明确的取舍：更多容器方法、可变参数、链式比较、`import` 等暂不支持——它们属于易用性或表达力问题，按需逐步加入，不影响设计主线。

## 8. 已知边界与语义偏差

- 宿主函数的执行耗时与内存由宿主自律，不按指令计费（每次 FFI 调用计 1 条指令）；宿主返回结构受节点预算与深度限制。
- 内存总账是近似值（字符串按字符数 ×4、list 槽 ×8、dict 项 ×16），只增不减（高水位），不模拟实际释放——保守但安全。
- finally 副本内再抛异常时，外层 finally 可能多执行一次。
- `except` 内嵌套 except 后裸 `raise` 的重抛对象可能不是最外层。
- for 遍历 list 为活视图、遍历 dict 为键快照。
- VM 终态后其执行上下文仍保留在引擎上（供调试快照查看）；引擎级 `max_total_vms` 已封住数量增长，终态释放留待后续版本。
- 配额检查发生在各环节自身记账时：后代 VM 执行期间祖先的计数被推高但不即时校验，可能小幅过跑（约一次调用链条的规模）后才触发。
- 跨兄弟 VM 的场景（一个子 VM 的函数被转授给另一个子 VM）中，镜像计费会在共同祖先处重复计入——方向是多计（保守），不构成配额逃逸。

## 9. 明确暂不支持

字符串方法与文档所列封闭集合之外的列表/字典方法、可变参数/仅关键字参数、`**` 展开、链式比较、切片、元组、f-string、`import`、`del`、class 字段默认值/方法/继承。
