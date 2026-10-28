# Changelog

本项目的所有重要变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 宿主侧驱动 VM 时，`snapshot()`/`step()`/`step_instruction()` 返回的快照新增宿主专属诊断字段 `vm_id`/`parent_id`/`depth`/`child_count`（字段含义见虚拟机参考第 4 节）。

### Changed
- 脚本内 `snapshot()`/`step()`/`step_instruction()` 返回的快照移除 `vm_id` 字段，脚本可见快照固定为安全视图字段集合（见虚拟机参考第 4 节）。
- VM 句柄的显示文本由 `<VM id=N state=...>` 改为 `<VM state=...>`，不再暴露引擎全局 VM 计数。
- **语义破坏变更**：源码解析、语言规则校验、编译护栏与源码大小预检统一抛出 `syntax_error`，移除 `validation_error` kind；root 创建、子 VM 与 `exec()` 投递遵守同一契约。原 `except validation_error` 需改为 `except syntax_error`，旧 kind 名现按未知 kind 拒绝。

### Fixed
- 直接子 VM 计数与 `max_child_vms` 配额改为只统计创建成功的子 VM：源码超限、编译失败或总 VM 数超限导致的创建失败不再虚增 `child_count`、也不再消耗子 VM 配额（此前失败尝试会被计入，宿主诊断字段因此虚高）。
- `_create_vm` 内部调整为"先计费常量内存、成功后才注册 context"：常量计费触顶（`max_total_bytes`）时不再留下孤儿 context（此前孤儿会占用 `max_total_vms` 槽位、消耗一个 `vm_id`，且不计入 `child_count`）。

### Security
- 关闭两条向脚本泄漏引擎全局 VM 计数的通道：脚本侧快照的 `vm_id` 字段与 VM 句柄显示文本的 `id=`（原安全模型"引擎不保证什么"第 6 条已知边界，现已修复并从文档移除）。固化配套约束：`SericiteError.filename`（内嵌 `vm_id`）仅宿主可见，面向脚本的错误面不得将其拼入消息文本或暴露为字段（见架构说明不变式 7）。

## [0.8.0] - 2026-10-27

### Added
- 引擎新增 `exec`：向既有 VM 投递新源码并在其持久模块作用域中执行（宿主级 `VMHandle.exec(source)` 与脚本级 `sub.exec(code)`）。模块变量、定义、VFS 与授予的函数跨投递保留；只返回本次投递产生的输出；编译失败不改变 VM 状态，普通执行错误后可继续投递；`terminated` 的 VM 拒绝投递，未执行完的程序会被丢弃。配额仍按 VM 生命周期累计。
- CLI 新增 `-c/--command`、stdin 源码入口和可重复的 `--include`；include 在同一 root 编译单元与全局作用域中按序组合，错误位置映射回原始文件。
- CLI 新增 `--capabilities`：通过可信 Python `configure()` 配置 root 的 FFI、配额与初始 VFS，使应用主体可以直接运行在 root Sericite 中。
- CLI 实时转发并 flush root stdout，包括无换行输出；`create_root()` 新增可选 `output_writer`，保留累计输出且不被子 VM 继承。
- 新增双语 CLI 参考，收录命令契约、include 语义、信任边界与退出码。
- root-agent demo 新增可开关的 `llm_chat` 实时 stderr 日志：默认单行摘要，可选完整请求/响应 JSON，且不记录认证头。

### Changed
- root-agent demo 改为会话级持久执行 VM：`sericite_exec` 复用同一个第一层 VM（`exec` 投递新代码），file 工具直接对接该 VM 的文件系统，删除每次执行的播种/收种同步；外层提示词同步改为指导模型为内层会话维护持久 VM。
- 原厚宿主 LLM demo 原位转换为 `demos/root-agent`：Python 仅保留能力适配，会话循环、工具分发、子 VM 与文件收种迁移到 Sericite；新增离线全链回归测试。
- 文档索引按入门、使用参考、设计边界、实现与历史分层，并更新目录迁移指针。
- 原《宿主参考》拆分为《虚拟机参考》（VM 状态、驱动方法、exec 投递、配额与授予语义）与《Sericite-PY 参考》（Python 库 API 与 FFI）；语言参考的 VM 章节收窄为入口与指针，其余文档的引用同步更新。

### Fixed
- root-agent demo 按旧厚宿主逻辑划分 root 控制区与模型工作区：root 自己运行外层会话，第一层 VM 只接收工作区和必要能力，外层提示词等控制资产不暴露给模型。
- sdist 改用公开内容白名单，只从明确公开的目录与文件构建，避免本地未跟踪内容意外进入发布包。

## [0.7.1] - 2026-10-27

### Fixed
- 修复 `str.replace(old, new, count)` 的 `count` 超出宿主 C `ssize_t` 范围时错误抛出 `conversion_error` 的问题；负数和超过可能替换次数的正数现按文档语义执行全部替换，包括 `old` 为空串的情况。

## [0.7.0] - 2026-10-27

### Added
- 新增增强赋值 `+=`、`-=`、`*=`、`/=`、`//=`、`%=`，支持名字、列表/字典下标与 record 字段目标；目标地址只求值一次，运算、错误与资源记账复用普通二元运算及写入路径。
- 字符串和列表新增只读切片 `value[start:stop]` 与 `value[start:stop:step]`，支持缺省位置、负索引、越界截断和负步长；结果复制按长度计入指令与内存配额，切片赋值在编译期拒绝。
- 字符串新增 `strip`/`lstrip`/`rstrip`、`split`/`splitlines`、`join`、`find`/`replace` 方法；采用封闭原生分发，扫描与匹配按规模计费，字符串结果及拆分列表槽位在创建前计入分配，绑定方法跨 VM 调用仍受调用方配额约束。

## [0.6.2] - 2026-10-26

### Security
- 契约/属性错误消息中的 record 与 schema 文本渲染纳入统一计量：`_contract_violation`、`_load_attr`、`_store_attr` 等抛错路径构建错误消息时按渲染节点数与文本长度计入指令配额，闭合"可捕获错误循环触发大 schema 渲染"造成的宿主 CPU 放大通道。
- `wrap()` 键集不匹配的错误路径把字典键拼入消息，其成本模型补充按字符串键的字节长度计费（同时覆盖键的哈希查找成本）；`schema()` 缺字段与函数缺参数的错误消息在拼接前按缺失名字节数计费；`_fit_detail` 的二次 schema 适配遍历按期望 schema 规模计费。
- **语义破坏变更**：FFI 异常契约明确化——宿主回调报告失败的唯一方式是抛契约 kind 的 `SericiteError`（按原样传播、脚本可按 kind 捕获）；契约之外的任何 `Exception` 视为宿主治理失败，当前 VM 以新增不可捕获 kind `host_error` 立即终止（消息只含异常类型名），控制权交还宿主，脚本不再能捕获宿主异常、也无法借异常类型名探测宿主内部；`SystemExit`、`KeyboardInterrupt` 等 `BaseException` 作为进程级事件原样上抛给宿主，不再被净化。`ffi_error` 保留给引擎侧的 FFI 边界违规。
- 安全模型文档补充已知边界：VM 句柄显示文本中的 `id=` 暴露引擎全局 VM 计数。

### Changed
- 内部重构：`engine`（2801 行）与 `compiler`（1081 行）分别拆分为子包，按内聚职责组织模块（engine 拆为 `_model`/`_values`/`_core`/`_builtins`/`_operators`/`_hostdbg`，compiler 拆为 `_rules`/`_validate`/`_scopes`/`_stack`/`_compiler`）；公开 API 与执行语义完全不变，行为无变化。

## [0.6.1] - 2026-10-26

### Security
- 跨 VM 方法返回值的结果估算移除 10,000 节点截断预算：每个节点都完整计入工作量与分配，调用方配额不足时以 `resource_exhausted` 失败且结果不交付，不再在预算耗尽后免费放行剩余节点。
- 普通字典下标读写（`d[key]`、`d[key] = value`）与字典字面量构造（`BUILD_DICT`）在实际哈希前按字符串键长度计入指令配额，闭合新鲜长字符串键的未计费哈希成本。

## [0.6.0] - 2026-10-26

### Security
- 重新设计安全记账体系：新增 `AccountRoute`、`Meter` 与一次性 `AllocationPermit`，所有指令和动态操作统一经过计量入口；native 必须显式声明 home、work、allocation，未知 VM 方法的成本模型直接失败。
- 跨 VM 调用在开始时建立 caller/home/target 联合因果路由，目标执行的每条指令即时受调用方配额约束，不再事后差值镜像；共享祖先只计一次，收费先检查全部账户再统一提交，返回值只进入实际 caller 的路由。
- FFI 双向复制、渲染、快照、结果估算和结构比较改为执行中逐节点计费；IO/VFS 脚本变更必须消费资源许可，宿主预置显式使用 trusted 通道。
- VFS 改用直接子项目录树和名称元数据，深路径写入恢复近似线性，新增目录逐项记账，目录枚举成本覆盖条目数与名称长度。

### Changed
- 单次收费被拒绝时不再只增加部分账户的计数；指令配额在边界处立即停止，不再为事后镜像超额冲账。
- 新增静态架构约束，禁止旧收费入口复活及在 `accounting` 之外直接修改指令与内存账；当前架构、安全模型和宿主文档同步为新契约。

## [0.5.2] - 2026-10-26

### Security
- 补全 VM 句柄方法的资源计费与因果镜像：`feed_input`/`step`/`step_instruction`/`terminate`/`read_file`/`write_file`/`path_exists` 不再绕过统一计费包装；读取结果按大小计费，`write_file`/`feed_input`/`run(inputs)` 的输入字符串按长度计费，绑定方法逃逸到其他 VM 后也会计入实际触发方配额。
- 跨 VM 原生调用的镜像计费改为在 `finally` 路径执行：目标 VM 运行或子 VM 编译抛出可捕获异常、参数校验失败前已发生预计费时，调用方仍需承担相应指令与分配成本；镜像超额以不可捕获的 `resource_exhausted` 终止，`InputRequired` 的暂停与恢复语义保持不变。
- `list.pop(i)` 按索引之后的元素搬移量计入指令配额，负索引先规范化；`pop()`/`pop(-1)` 保持 O(1) 路径，不再能以固定指令账在大列表上反复执行线性搬移。

## [0.5.1] - 2026-10-26

### Security
- 闭合绑定方法的跨 VM 计费逃逸：`list.append`/`list.pop`/`dict.keys`/`dict.values`/`dict.get`/`dict.pop` 与计费型 VM 句柄方法（`snapshot`/`stdout`/`list_dir`/`run`）的绑定方法此前未登记 `home`，经授予函数泄漏到其他 VM 后，调用时跳过因果镜像计费，调用方可借定义方 VM 的账本放大自身消耗；现在这些绑定方法一律登记定义方 VM，跨 VM 调用时其资源增量按设计镜像进触发方配额。同 VM 调用的行为与账本数值不变。
- `except` 过滤条件在编译期拒绝 `resource_exhausted`/`internal_error` 两个不可捕获 kind：此前它们能编译通过但运行时永不命中，造成可以捕获的假象。报错消息同时区分了"不可捕获"与"未知 kind"两种情况。

## [0.5.0] - 2026-10-25

### Added
- `print` 新增仅关键字参数 `end`，默认仍为换行；支持 `end=""` 及自定义末尾文本，非字符串值报 `type_error`，末尾文本计入输出配额。
- 列表新增 `append`/`pop` 成员方法，字典新增 `keys`/`values`/`get`/`pop` 成员方法；采用封闭的原生方法分发，支持绑定方法，未支持的方法报 `attribute_error`。
- 成员方法补齐资源治理：`append` 检查列表上限并计入新槽分配，`keys`/`values` 检查结果列表上限，并按字典规模计入指令与列表分配。

### Removed
- **Breaking**：移除全局内建 `keys(d)`，改用 `d.keys()`；`keys` 不再是保留名，可作为普通变量或授予函数名。

### Changed
- `except` 过滤条件现在必须是已定义的错误 kind；未知名字及拼写错误在编译期以 `validation_error` 拒绝，错误消息提示按 kind 绑定消息与裸 `except:` 兜底的正确写法，不再让无效 handler 留到运行期静默失配。

## [0.4.4] - 2026-10-25

### Security
- 嵌套 schema 契约检查补齐深度计费：`_contract_cost` 现按 schema 的全部嵌套字段数计费（`size` 在创建 schema 时一次性预计算），修复此前 D 层嵌套 schema 链构造与单次检查分别只按 O(D)/O(1) 计费、却做 O(D²)/O(D) 实际工作的欠计费放大。
- schema 文本渲染（`_contract_text`/`SericiteSchema.__repr__`）加 64 层深度上限：快照/单步调试不再因局部变量里的深层嵌套 schema 向宿主抛出原始 `RecursionError`。

## [0.4.3] - 2026-10-25

### Fixed
- 修复分支、循环和异常路径中 record 报错标签与运行时值脱节的问题：标签按控制流保守传播，无法确定同一标签时退回匿名结构显示，不再沿用顺序编译产生的误导性名字。

## [0.4.2] - 2026-10-24

### Security
- 不变量 16 补全两条遗漏通道：外来代码在子 VM 的报错中，参数名替换为位置序号（`argument 1`、`missing argument(s): 2`），带注解赋值（`CHECK_ANNOT`）的注解标签同样按 `origin_vm` 擦除。
- 契约检查补齐计费：record 构造、字段写入、`wrap()` 的逐字段契约检查按 schema 规模计入指令配额（此前大 schema 契约可放大宿主 CPU 60–70×）。
- 字符串 `==`/`in` 恢复按长度计费（0.4.1 比较重写时的计费回归）。
- 快照视图中的原生函数显示为 `<function VM.run>`，不再出现 `<_NativeFunction>` 内部类名；`_type_name` 对授予函数同样归一为 `function`。

### Changed
- **内建归属改为定义 VM**：函数值现在自带其定义 VM 的完整世界——除模块变量、闭包、授予环境外，`print`/`read_file` 等内建与 `VM()` 创建也解析回定义方（home）。调用从其他 VM 获得的函数，其文件读写作用于它自己的 VM，不再作用于调用方。这取代了 0.4.1 文档化的"内建属于执行 VM"的临时语义（语义割裂）。**注意**：授予一个会做 IO 的函数等于把自己的文件系统与输出通道一并授予；转授子 VM 交来的函数等于把该子 VM 的世界转授他人——security 文档已写明。
- 世界服务的资源消耗归属定义 VM，同时按因果镜像计入触发它的调用方配额（镜像止于 home，不重复计费）；授予函数创建的子 VM 按因果挂在调用方树下（父级/深度/子计数），配额取 home 与调用方的逐项最小值——调用方的预算完整约束其因果消耗总量（含孙 VM 的运行期指令）。

### Fixed
- `in`/`not in` 对含共享子结构的 list 不再产生假阳性（0.4.1 比较记忆化引入的语义回归）："比较中"与"已完成"拆为两张表，命中已完成的对返回缓存的真实结果。
- 镜像计费扣除回调期间已沿调用方祖先链走账的部分：孙 VM 的初始分配不再被调用方重复计入。
- 回归测试增至 312 个用例。

## [0.4.1] - 2026-10-24

### Security
- 修复跨 VM 编译期标签泄漏：授予函数体内嵌套调用的 helper 在子 VM 报错时，此前会带出父层的类名/函数名（属性 hint、参数契约、返回契约、参数数量四条通道）。现在标签与定义方名字的可见性以"代码单元的定义 VM == 当前执行 VM"为准（`CodeUnit.origin_vm`），外来代码的报错一律退为结构描述与授予名——架构不变量 16 规定。
- 修复 record/schema 相等与成员判断的配额欠计费：比较按实际访问节点数计费，并以 (id, id) 记忆化消除共享子结构（DAG）的指数放大；此前 10 万元素的 record 比较只计 1 条指令，可被用作宿主 CPU DoS。
- 修复原生函数作为一等值后的宿主信息泄漏：`sub.run` 赋给变量再打印不再暴露宿主类名与 Python 堆地址（显示为 `<function VM.run>`），错误消息中的类型名统一为 `function`。
- 收紧注解位保留名规则：保留名必须就是注解表达式本身，不得藏在子表达式中（`x: stash(print)` 之类走私内建函数对象的写法现在编译期拒绝）。

### Added
- 契约名 `bool`/`list/dict` 落地：0.4.0 文档已承诺但未实现，现可在 class 字段与注解位使用。三者与 `any` 同为仅注解位的契约名（不可调用、不可赋值）。

### Changed
- **Breaking**：`bool`/`list`/`dict` 成为保留名（不可作为变量/函数名）；0.4.0 已保留的 `any`/`wrap`/`unwrap` 同属此列，此前未显式声明，在此一并声明。
- class 体的裸字段声明豁免保留名检查：`class C: int` 现在是合法字段（字段名不是名字引用），不再误报"内建只能直接调用"。
- `wrap()` 的键集校验按 dict 实际大小计入指令配额。
- 环状结构的相等比较从"递归耗尽报 resource_exhausted"变为按余归纳语义收敛（`a = [a]` 与 `b = [b]` 相等）。
- 安全文档补充：record 跨 VM 按引用传递的共享状态说明；"内建属于执行它的 VM"（调用外来函数等于借出自己的世界）的预期语义；SECURITY.md 支持版本表补 0.4.x。
- 回归测试增至 298 个用例。

## [0.4.0] - 2026-10-24

### Design

本次更新是类型系统的路线决断：Sericite 不引入名义类型，而是把"类型"拆成两半——**运行期的结构 schema**（一等值，可传递、可授予、按字段与契约比较）与**编译期的词法标签**（只服务报错文本，出作用域即擦除）。

**为什么不引入名义类型。** 名义身份由创建事件决定，在层层嵌套、逐层授予的世界里跨层必撞身份墙：父层的 `Point` 与子层同形状同名的 `Point` 算同一类型吗？结构语义下 schema 按字段集与契约比较，天然跨层可比，这个问题整体不存在。同时沙箱的输出必须是可枚举的纯数据，名字不污染值。

**为什么标签必须随作用域擦除。** Sericite 的宇宙观是层层封闭：你无法知道自己是否嵌套在更大的宇宙里，布景上也不该留着外层世界的厂商标签。一个值若烙着父层起的名字跨层旅行，在子层出错时就会报出一个子层全部源码中从未出现过的符号；而子层的错误消息是可被 `except` 捕获的数据——这个名字就是一条谁都没有显式打开的信息信道，楚门的世界就此破洞。名字是层本地命名空间里的指针，跨层运输一个名字等于运输一个悬垂指针。所以类名与注解名只活在编译期；每一层在自己的入口显式命名（`r2: T2 = make()`），命名是接收方的本地行为，不是随货附赠的遗产。

完整论述见 `docs/design` §3.4「结构跨层，名字层本地」（中英双语），执行纪律固化为架构不变量 16。

### Added
- 语言新增 record 与 schema：`class` 定义运行期结构契约（字段声明 `x` 或 `y: int`），schema 是一等运行期值、每次执行 `class` 语句即创建；record = 载荷 + schema 引用，支持点号成员读写，形状固定（字段不可增删、写入受字段契约约束）。
- schema/record 相等为结构相等（字段名 + 字段契约；record 另要求载荷相等）；record 与 dict 永不相等。新增内建 `wrap(schema, dict)`（严格键集套皮）与 `unwrap(record)`（浅拷贝扒皮）；新增契约标记 `any`。
- 注解从静默忽略变为真实执行的运行期契约：`def f(p: T)`、`x: T = value`、`def f(...) -> T` 分别在调用/赋值/返回时检查（宽度子类型：实参 record 包含期望字段即可），dict 不自动套皮；报错带 blame 方向（argument / return value / annotated assignment）。新增错误 kind：`attribute_error`、`contract_error`。
- 报错标签：类名与注解文本是编译期、作用域本地的诊断标签（如 `record Point {x: int} has no field 'y'`），不进入值、出作用域失效，无标签时按结构显示。
- record/schema 不能跨宿主 FFI 边界（报 `ffi_error` 并提示 unwrap）；经授予函数跨 VM 按引用传递，契约检查跨 VM 成立；授予函数在子 VM 的报错（参数契约、返回契约、参数数量）一律使用授予名与结构描述，定义方的函数名与类型标签不越界。新值创建纳入内存配额，契约检查按字段数折算指令。
- 属性访问的 VM 白名单校验从编译期移到运行期（`sub.evil()` 现在编译通过、运行期报 `attribute_error`）；`def f(p: int)` 等注解位不再误报保留名错误。
- design 文档新增 §3.4"结构跨层，名字层本地"，架构文档新增不变量 16（标签只烘焙进本层 CodeUnit、授予函数报错用授予名与结构描述），固化 record/schema 设计的纪律。
- 回归测试增至 285 个用例。

## [0.3.1] - 2026-10-23

### Security
- 修复授予函数的名字解析：函数体未命中定义方模块变量时，不再回退到调用方 VM 的同名 `granted` 函数，而是保留定义方已持有的授予函数环境，避免调用方伪造同名能力。
- 提高子 VM 源码编译的指令折算系数，防止大源码以过低的指令预算消耗宿主 CPU。
- 闭包 cell 与捕获环境改用更保守的内存记账系数。
- 安全文档明确：被授予的 sericite 函数会共享定义方可达的可变状态，授予函数即授予这部分能力；未被授予的父级变量仍不可见。
- 回归测试增至 224 个用例。

## [0.3.0] - 2026-10-23

### Added
- 语言新增词法闭包：嵌套函数按引用捕获外层局部变量，跨 VM 授予与再次授予时保留定义方闭包环境和模块全局；闭包 cell 与捕获环境纳入内存配额。
- 语言新增函数装饰器：装饰器表达式从上到下求值，堆叠装饰器从下到上应用，结果重新绑定到函数名。
- 新增 `benchmarks/vm_creation.py`：VM 创建成本的可复现基准（宿主侧与脚本内两条路径，附线程/进程参照）。实测：脚本内创建子 VM 约 0.05 ms，宿主侧创建+运行全流程约 0.04 ms（Intel i3-9100，CPython 3.13/3.14），与线程同数量级、比进程便宜一到两个数量级；design 文档相应段落由"有待量化验证"更新为实测陈述。
- 新增 `benchmarks/instruction.py` 与 `benchmarks/debugging.py`：按真实指令计数测量连续执行、逐指令与逐语句调试成本，编译和 VM 创建不计时。在 Intel i3-9100、CPython 3.13.13 上，代表性循环约 0.65 µs/指令，逐指令约 1.86 µs/指令，逐语句约 4.91 µs/次调用；中英文架构文档与 README 同步记录结果。
- 英文文档补齐：`docs/architecture.md`（架构说明全译）；`docs/`、`docs/stages/`、`docs/behind-the-scenes/`、`demo/` 的索引页按"英文 `.md`、中文 `.zh-CN.md` 单文件不混排"的规范拆分为独立英文版。stages 正文与 behind-the-scenes 长文保持中文（历史文档，翻译成本高、价值低）。
- 回归测试增至 221 个用例。

## [0.2.0] - 2026-10-22

### Changed
- 项目更名：Mica/MicaLang → Sericite。发行包名 `micalang` → `sericite`，import 包名 `mica` → `sericite`，CLI 命令 `micalang` → `sericite`，源码扩展名 `.mica` → `.sericite`，Python API 类名 MicaEngine/MicaError/MicaLimits → SericiteEngine/SericiteError/SericiteLimits。更名缘由见 README "The name"。
- design 文档修正先例论述：补充 Safe-Tcl 作为直接祖先的考据，新增 docs/prior-art.md《先例与相关工作》（中英双语）。

## [0.1.0] - 2026-10-22

首次公开发布。构建过程见构建手记 `docs/stages/`（tag `stage-0`…`stage-6`）。

### Added

- Sericite-PY 参考实现：源码经白名单校验编译为内部指令流，由统一调度循环执行，不经 `exec`/`eval`。
- 语言：int/float/str/bool/None/list/dict；`if/while/for`、`break/continue`、`try/except/else/finally`、`raise`、三元表达式；函数、递归、默认参数与关键字实参。
- 嵌套 VM：任意层可创建子 VM，子 VM 不感知层深；父 VM 可预置文件、喂输入、单步调试、快照、终止。
- 能力授予（FFI）：宿主向 root VM 注入函数，任意层 VM 向下一层授予函数；跨宿主边界双向深拷贝 + 纯数据类型白名单。
- 资源治理：指令数、输出字节、调用深度、子 VM 数量、嵌套深度、容器大小、字符串字节、整数位宽、近似内存总量、VM 总数、文件数与单文件字节配额；子 VM 消耗计入所有祖先。
- 每个 VM 自带私有虚拟文件系统（纯内存、纯文本）。
- 回归测试：198 个用例。
- demo：HTTP 能力授予 + 多层虚拟化的 LLM 代码执行示例（`demo` extra，含离线桩服务器）。
