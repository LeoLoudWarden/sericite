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
| `engine` | 调度循环、帧/求值栈、运算语义、异常展开（跨帧/跨 VM）、内建函数、VM 生命周期与 exec 投递、资源配额、调试快照 |
| `accounting` | 因果记账路由、统一 Meter、原子收费与一次性资源变更许可 |
| `vfs` | 单 VM 私有虚拟文件系统（纯内存、纯文本；平坦文件字典 + 直接子项目录树及名称元数据） |
| `io` | 每个 VM 独立的虚拟输入与输出（输出字节上限；脚本输入变更需许可，宿主预置走显式 trusted 通道）；root 输出可经可选回调实时转发（用户契约见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)第 2 节） |
| `errors` | `SericiteError` 与集中管理的错误 kind 注册表 |
| `cli` / `__main__` | 命令行入口：源码读取与 include 拼接及来源行号映射、可信能力文件装载、root 驱动与宿主侧诊断；不改变编译、调度或隔离不变量（命令行契约见 [CLI 参考](cli-reference.zh-CN.md)） |

`compiler` 包按内聚职责拆分为：

- `_rules`：白名单表、运算符映射、保留名与 VM 方法名
- `_validate`：AST 白名单与 except kind 校验
- `_scopes`：词法作用域与 cell 分析
- `_stack`：静态栈深度分析，保证异常捕获时栈可安全截断
- `_compiler`：产出指令流的 `_Compiler`
- `__init__`：持有 `compile_source`，编排整个编译流水线

`engine` 包按内聚职责拆分为：

- `_model`：limits、帧、函数、schema/record、原生包装、VMContext/VMHandle
- `_values`：值语义、渲染、契约 helper、FFI 深拷贝
- `_core`：生命周期、调度循环、异常展开、调用机制
- `_builtins`：内建函数、子 VM 创建
- `_operators`：运算/索引/属性语义，容器与 record 原生方法
- `_hostdbg`：VM 句柄方法计费、调试快照
- `__init__`：组装 `SericiteEngine` 并 re-export 公开 API

## 3. 设计不变量

修改引擎时必须保持以下不变量（编号仅为引用方便）：

1. 所有 VM 必须由同一个 `SericiteEngine` 直接执行，不能为每个层级再套一层解释器。嵌套 VM 只是同一引擎里的另一个执行上下文，这是"创建子 VM 便宜"的结构基础（实测见 [benchmarks/vm_creation.py](https://github.com/LeoLoudWarden/sericite/blob/main/benchmarks/vm_creation.py)）。
2. 子 VM 不得隐式读取父级或宿主 stdin，也不得直接向宿主 stdout 写入；子 VM 的文件系统默认全新空白，不共享父级任何文件。
3. 子 VM 默认不能取得父级局部变量、父级句柄、宿主对象或 Python 反射入口。
4. 脚本能力通过受控原生函数和 VM 句柄方法提供，不能暴露任意 Python 属性。
5. 执行必须经由内部指令流与统一调度循环；`run()`、`exec()`、`step()`、`step_instruction()` 共享同一条执行路径，不允许旁路执行语义。`run()` 不做逐语句快照，快照只在显式 `step()/snapshot()` 时生成。
6. 新语法必须先过编译器白名单，再编译为指令；禁止为了省事引入 `exec`/`eval`。
7.
  - a. 错误和调试视图只能包含逻辑源码位置及安全值，不能默认透传宿主 traceback 或真实路径；脚本无法感知自己的 VM 嵌套深度。
  - b. 宿主 `RecursionError` 转换为 `resource_exhausted`，`OverflowError` 转换为 `conversion_error`，原生宿主异常不得直接进入脚本。
  - c. `SericiteError.filename` 内嵌引擎级 `vm_id`，仅宿主可见。面向脚本的错误面 `except kind as e` 的绑定值、快照 `error` 视图、消息文本中不得包含泄漏通道。
8. 新增能力时同步考虑隔离、资源记账、生命周期和调试语义，不只做语法可运行。所有动态消耗必须进入统一 Meter 与 AccountRoute；子 VM 的消耗必须计入祖先。
9. Sericite 值语义由引擎助手函数定义，不直接继承 Python 运算符的隐式行为（如 bool 不参与算术）。
10. `resource_exhausted` 与 `internal_error` 不可被脚本 try/except 捕获——配额不能被脚本吞掉。
11. VM 句柄方法白名单只有一个来源（编译器侧定义），引擎侧引用它，两边不得分叉。
12.
  - a. 宿主边界（FFI）必须双向深拷贝 + 类型白名单（None/bool/int/float/str/list/dict 递归）：句柄、函数、record/schema、宿主原生对象一律不得越界。
  - b. FFI 异常契约：宿主回调只能通过抛契约 kind 的 `SericiteError` 报告失败；契约之外的任何 `Exception` 都视为治理失败，当前 VM 以不可捕获的 `host_error` 终止。完整契约见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)第 5.3 节。
  - c. VM 之间的函数授予在同一引擎信任域内按引用传递，不拷贝。
13.
  - a. 授予的 sericite 函数执行在**调用方 VM 的帧栈**上，指令计入调用方及祖先。
  - b. 函数同时保留**定义方环境**：定义方函数的闭包 cell、定义方 VM 的模块变量、定义方已持有的授予函数环境，以及定义方 VM 的内建服务（IO/文件系统/子 VM 创建均解析回定义 VM，即函数的 home）。
  - c. 反向或交叉的组合都不允许；再次授予时必须完整保留这些定义方环境。
14. 一切会增长的资源都必须有配额。所有指令与动态操作必须经由 Meter 和 AccountRoute，禁止事后补账、差值镜像及绕过资源许可；调试、异常、暂停和跨 VM 路径同样适用。具体契约见第 5 节。
15. 调度入口有重入保护：同一 VM 不得被两个调度循环同时驱动（例如宿主在 `input_provider`/FFI 回调里对同一 VM 再调 `run()`、`exec()` 或 `step()`）。
16.
  - a. 跨 VM 的只有结构：record/schema 不携带名字，schema 相等按字段集与契约的结构比较；类名、注解名等标签是编译期、作用域本地的诊断数据，出作用域即失效。
  - b. 外来代码（`origin_vm` 不同的 CodeUnit）在当前 VM 的报错（属性 hint、参数/返回契约、参数数量）一律退为结构描述与授予名，定义方的函数名、类型标签、参数名（以位置序号替代）不得出现；
  - c. 新增值形式或跨层通道时，必须同样保证名字不随值越层。设计论证见[设计说明](design.zh-CN.md)第 3.4 节，脚本可见语义见[语言参考](language-reference.zh-CN.md)第 7 节。

## 4. 脚本接口

脚本可见的内建函数与容器方法以[语言参考](language-reference.zh-CN.md)第 6 节为准；VM 句柄方法与 VM 状态以[虚拟机参考](vm-reference.zh-CN.md)第 3、4 节为准。引擎侧对这份接口只承担两条内部职责：这些名字的编译器白名单有唯一来源（不变量 11）；容器与字符串方法走封闭的原生分发，不暴露任意 Python 属性。方法调用的计费规则见第 5 节。

错误 kind 由 `errors` 模块集中注册，可捕获性由编译器强制：未知过滤名字与不可捕获 kind 都在编译期拒绝为 `syntax_error`。完整 kind 清单见[语言参考](language-reference.zh-CN.md)第 5 节。

## 5. 资源配额

配额由 `SericiteLimits` 定义，字段清单与默认值见[虚拟机参考](vm-reference.zh-CN.md)第 5 节。本节只讲计费模型。

### 5.1 基本规则

- 子 VM 默认继承父 VM 配额，`VM()` 参数只能收紧。
- 指令、内存和子 VM 消耗计入所有祖先，祖先链上任一环超限即失败。
- 内存总账是近似高水位，只增不减；闭包 cell 与捕获环境也计入。
- O(n) 及以上的工作按规模折价计入 `instruction_count`，不能按一条指令打发。

### 5.2 时间成本：预付或增量

- 每条指令的基础成本由统一 Meter 处理。
- native 必须显式声明 `home`、`work`、`allocation`；常量成本也必须明确写出，不能省略。
- 可预估的动态成本在执行前扣除。复制、渲染、比较、快照等复合过程按节点或小片扣除，不能完成后补账。
- 参数验证、成本估算、失败路径和结果构造也属于工作，不能成为免费通道。

### 5.3 空间成本：所有者与许可

- IO/VFS 的脚本资源变更必须消费一次性 `AllocationPermit`；许可绑定所有者、资源类别和数量，不能复用或挪作他用。
- 容器等逻辑分配由可信原语通过 Meter 处理，不要求包装每个 Python 容器。
- 单次收费先检查路由上的全部账户再统一提交。被拒绝的新收费不部分入账，已经发生的工作收费保留。
- 宿主直接预置或管理资源走显式 trusted 通道；脚本不能借这条通道绕过许可。

### 5.4 因果路由与结果归属

- 调用开始时由 caller、home、target 构造 AccountRoute，执行作用域中的每条指令都使用它。
- 共享祖先在一次因果收费中只计一次；跨兄弟 VM 不做特殊差值镜像。
- VM 方法的执行由 target 与 caller 联合约束；返回值的所有权只进入实际 caller 的路由。
- 授予函数创建的子 VM 是空世界，树位置按因果挂在触发方下，配额取 home 与 caller 的逐项最小值。

### 5.5 新增语言功能的检查清单

新增 opcode、native、VM 方法或跨边界通道时，依次回答：

1. **工作量是什么？** 是否包含验证、排序、复制、哈希、比较、异常文本和宿主原语的隐藏复杂度？
2. **何时收费？** 能否预付？若不能，是否已拆成可中断的小片，而不是完成后补账？
3. **资源属于谁？** 新对象、队列项、目录项或临时结构由哪个所有者计量，是否需要许可？
4. **谁触发、谁接收？** home、caller、target 和结果归属是否分别明确？
5. **异常路径怎样？** 失败、暂停、恢复、调试和跨 VM 调用是否仍走同一 Meter 与许可？
6. **测试是否隔离？** 是否用操作前后 checkpoint 覆盖小规模/大规模、紧配额、中途失败和变更前阻断，而不是只看整个 VM 的总账？

## 6. 实测性能

以下最近一次实测均使用 Intel i3-9100、Linux x86_64、CPython 3.13.13（2026-10-26）。所有数值均为多轮测试的中位数。

| 操作 | 实测成本 | 复现脚本 |
|---|---:|---|
| 脚本内创建子 VM | ~88 µs/VM | [vm_creation.py](../benchmarks/vm_creation.py) |
| 宿主侧创建并运行 root VM | ~61 µs/VM | [vm_creation.py](../benchmarks/vm_creation.py) |
| 用 `run()` 执行代表性计数循环 | ~0.82 µs/指令 | [instruction.py](../benchmarks/instruction.py) |
| 用 `step_instruction()` 执行同一循环 | ~2.60 µs/指令（`run()` 的 3.19 倍） | [debugging.py](../benchmarks/debugging.py) |
| 用 `step()` 执行同一循环 | ~6.32 µs/次调用（约 1.40 µs/指令） | [debugging.py](../benchmarks/debugging.py) |

补充限定：

- 指令成本是该工作负载的加权平均值，不代表每种 opcode 都有相同成本。
- 表中数字不含 VM 创建与编译的成本。
- 单步数据包含逐步控制以及每步生成安全快照的成本。
- 测试工作负载只有一个简单局部变量。
- 这些数字是 Python 原型的实测结果，不是性能承诺；引擎变更后需要重新测量。

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

- 宿主 callback 内部的执行耗时与内存由宿主自律，不按指令计费；引擎执行的 FFI 参数与返回值复制按节点计入工作量，返回结构还受节点预算与深度限制。
- 内存总账是近似值（字符串按字符数 ×4、list 槽 ×8、dict 项 ×16），只增不减（高水位），不模拟实际释放——保守但安全。
- finally 副本内再抛异常时，外层 finally 可能多执行一次。
- `except` 内嵌套 except 后裸 `raise` 的重抛对象可能不是最外层。
- for 遍历 list 为活视图、遍历 dict 为键快照。
- VM 终态后其执行上下文仍保留在引擎上（供调试快照查看）；引擎级 `max_total_vms` 已封住数量增长，终态释放留待后续版本。
- 单次收费先检查路由上的全部账户再统一提交；被拒绝的新收费不会只落入部分账户，已经完成的工作收费则保留。
- 跨 VM 调用共享祖先只计一次；VM 方法的执行成本由 target 与 caller 联合约束，返回值的所有权只进入实际 caller。

## 9. 明确暂不支持

文档所列封闭集合之外的字符串、列表与字典方法、可变参数/仅关键字参数、`**` 展开、链式比较、切片赋值、元组、f-string、`import`、`del`、class 字段默认值/方法/继承。
