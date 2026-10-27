# 先例与相关工作

Sericite 并不声称"语言内建隔离"是新想法。它声称的是：这个想法被验证过一次，因历史原因半途而废，如今值得把它做完。（[English](prior-art.md)）

## Safe-Tcl：直系祖先

Tcl 自 7.5 版本（发布于 1996 年 4 月 21 日）起把安全解释器做成了语言内建，其源头是 Nathaniel Borenstein 与 Marshall Rose 在 1992 年实现的 Safe-Tcl 原型。这个原型为"主动邮件"（active email）而生：代码通过信道——一封电子邮件——送达，在收件人本地的受限解释器里执行。这与今天 LLM 工具调用的问题形状完全相同：代码通过信道（模型输出）送达，必须在本地执行且不可信任。

Tcl 内建的这套机制：

- 安全解释器启动时危险命令已被禁用或移除（文件访问、`exec`、socket……）——零能力默认。
- master 通过 **alias** 把受控能力授予回去：slave 中可见的命令，实际在 master 的上下文里执行。Tcl 手册称此为"slave 与 master 之间的受保护通信（类似于系统调用）"。
- 任何 slave 都可以再创建自己的 slave，并对它们扮演 master，"形成解释器层级"；由安全解释器创建的子解释器自动也是安全的。不可信的递归嵌套是这个设计的原生形态。

Safe-Tcl 停在了哪里——用它自己的话说：

- 1998 年 USENIX 安全模型论文（Levy、Demailly、Ousterhout、Welch）明确写道："Safe-Tcl currently does not prevent most denial-of-service attacks. We will address this in the future with a combination of resource controls and a kill-key that lets a user intervene when an applet misbehaves."（Safe-Tcl 目前无法防止多数拒绝服务攻击；我们未来将以资源管制加 kill-key 的组合来解决。）
- 资源管制直到 Tcl 8.5 才经 TIP 143（2003 年）落地，其 rationale 承认"脚本即使在安全解释器中运行，发起拒绝服务攻击也是轻而易举的"。TIP 143 只加了两种限制——墙钟时间与命令数——且按单个解释器计。内存限制被明确以"代价过高"搁置；输出统计不存在。也没有任何向上计费：被限额的解释器创建的子解释器继承时间限，但命令数配额重新归零——TIP 只是建议 master"或许可以"自行扣减配额。
- kill-key 来得更晚：`interp cancel`，经 TIP 285 于 Tcl 8.6 引入。

于是历史记录是这样的：隔离机制本身是成立的，1996 年就已发布；资源治理这一半在 1998 年被承诺，十年后才部分兑现，且从未兑现为跨层级的配额会计。与此同时，这套机制获得过外部认可：NIST 的《Countermeasures for Mobile Agent Security》（2000）称 Safe Tcl 是"probably the best known of the safe interpreters for script-based languages"。主流平台的另一条路线——Java 的 SecurityManager——已被标记废弃（JEP 411，JDK 17），并在 JDK 24 中被永久禁用（JEP 486）。

Safe-Tcl 之死，不是机制输了。它是随宿主语言的生态位一起萎缩的。padded cell 没有输掉任何东西；是 Tcl 输掉了市场。

## 对比

| | Safe-Tcl (1992/1996) | Starlark | WASM 运行时 | Sericite |
|---|---|---|---|---|
| 隔离是语言级语句 | 是（`interp create -safe`） | 否（嵌入方 API） | 否（外部运行时） | 是（`VM(...)`） |
| 隔离世界可递归嵌套 | 是（safe 的子解释器自动 safe） | 否 | 由宿主居中 | 是 |
| 向子级授予能力 | 是（alias） | 部分（注入全局变量） | 是（宿主 imports） | 是（FFI，纯数据双向深拷贝） |
| 资源配额 | 8.5 之前没有；之后仅时间 + 命令数两种、按单解释器计、无祖先计费 | 依实现而定（starlark-go：可配置步数上限） | 依引擎而定（fuel/metering，非规范层能力） | 指令、内存、输出、文件、子 VM、深度；只紧不松；子级消耗计入全部祖先 |
| 父级对运行中子级的内省 | 无（8.6 起仅 `interp cancel`） | 无 | 依引擎而定 | step / step_instruction / snapshot / terminate |
| 内核密封、确定性 | 否 | 是（核心目标） | 是 | 否（IO 与文件正是设计要点，经显式授予） |

Sericite 从 Safe-Tcl 继承的：padded-cell 模型、零能力默认、授予是获得能力的唯一路径、嵌套是不可信性的自然形状。

Sericite 补上而 Safe-Tcl 从未有过的：配额树（只紧不松、计入全部祖先），以及把运行中的子级当作可调试、可快照的对象，而不是黑盒。

Sericite 明确不继承的：Safe-Tcl"宿主解释器实现可信"的前提。见[安全模型](security.zh-CN.md)——Sericite-PY 与宿主同进程运行，它不应是你的唯一边界。

## 出处

- Levy, Demailly, Ousterhout, Welch, "The Safe-Tcl Security Model", USENIX Annual Technical Conference, 1998. <https://www.usenix.org/publications/library/proceedings/usenix98/full_papers/levy/levy.pdf>
- Borenstein, "Email with a Mind of Its Own: The Safe-Tcl Language for Enabled Mail", IFIP WG 6.5, 1994. <http://guppylake.com/pubs/ulpaa-94.pdf>
- Tcl 7.5 发布说明（1996-04-21）。<https://www.tcl-lang.org/software/tcltk/7.5.html>
- Tcl `interp` 手册（安全解释器、alias、层级）。<https://www.tcl-lang.org/man/tcl8.6/TclCmd/interp.htm>
- TIP 143, "Resource Limits for Tcl Interpreters"（Tcl 8.5）。<https://core.tcl-lang.org/tips/doc/trunk/tip/143.md>
- TIP 285, "Script Cancellation with [interp cancel]"（Tcl 8.6）。<https://core.tcl-lang.org/tips/doc/trunk/tip/285.md>
- Jansen (NIST), "Countermeasures for Mobile Agent Security", Computer Communications 23(17), 2000. <https://csrc.nist.gov/csrc/media/projects/mobile-security-and-forensics/documents/mobile_agents/ppcountermeas.pdf>
- JEP 411, "Deprecate the Security Manager for Removal"（JDK 17）；JDK 24 起 Security Manager 永久禁用（JEP 486）。<https://openjdk.org/jeps/411>
- starlark-go `Thread.SetMaxExecutionSteps`。<https://pkg.go.dev/go.starlark.net/starlark>
