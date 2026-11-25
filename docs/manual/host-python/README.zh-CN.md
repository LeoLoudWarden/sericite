# Python 宿主手册

这里收录在 Python 程序中嵌入 Sericite 的指南和 API 参考，面向需要由现有应用创建、配置、驱动和检查 VM 的开发者。

Sericite-PY 是 Sericite 语言的 Python 参考实现。Sericite 源码借用 Python 的一部分语法，但会编译为 Sericite 自己的指令流，不会交给 Python 的 `exec()` 或 `eval()` 执行。语言本身不依赖 Python，本手册描述的是当前 Python 宿主的公开接口。

## 安装与准备

运行环境需要 Python ≥ 3.12。安装发行包：

```bash
pip install sericite
```

发行包名和导入包名都是 `sericite`，引擎没有第三方运行时依赖。

本手册示例中的外层代码是 Python，传给 `create_root()` 的字符串才是 Sericite 源码。需要编写这些脚本时，请阅读[脚本手册](../scripting/README.zh-CN.md)；只需要从终端运行程序、准备项目文件或编写可信 addon 配置时，请阅读[命令行手册](../cli/README.zh-CN.md)。

## 指南

| 页面 | 内容 |
|---|---|
| [快速开始](guides/01-quick-start.zh-CN.md) | 创建引擎和 root VM，运行第一段代码，取得输出并释放资源 |
| [执行会话与虚拟 IO](guides/02-sessions-and-io.zh-CN.md) | 保留会话状态、继续执行代码、提供输入、转发和缓冲输出 |
| [授予宿主能力](guides/03-addons.zh-CN.md) | 提供 addon、传递纯数据、翻译回调错误、管理能力边界 |
| [准备工作区](guides/04-workspaces.zh-CN.md) | 预置文件和模块、选择入口、在会话之间排他移交 VFS |
| [调试 VM](guides/05-debugging.zh-CN.md) | 使用断点、单步、快照、终止和销毁 |
| [观察 VM 活动](guides/06-observation.zh-CN.md) | 订阅整棵 VM 树的事件，按 VM ID 读取只读快照 |

第一次嵌入时，先读快速开始，再按任务选择后续指南。需要授予宿主函数时，建议同时阅读 addon 指南和安全模型。

## API 参考

| 页面 | 内容 |
|---|---|
| [引擎与配额](reference/01-engine-and-limits.zh-CN.md) | `SericiteEngine`、root 创建、VFS 创建、`SericiteLimits` |
| [VM 句柄](reference/02-vm.zh-CN.md) | `VMHandle` 的驱动、输入、调试、快照、生命周期和宿主管理方法 |
| [VFS 与文件](reference/03-vfs-and-files.zh-CN.md) | `VFSHandle` 所有权，以及 VM/VFS 句柄的 11 个文件与目录方法 |
| [addon](reference/04-addons.zh-CN.md) | 授予名、数据边界、回调异常、重入与成本责任 |
| [观察](reference/05-observation.zh-CN.md) | `SericiteObservation`、`SericiteEvent`、事件载荷和投递规则 |
| [错误与诊断](reference/06-errors.zh-CN.md) | `SericiteError`、`SericiteFrame`、调用栈和宿主错误处理 |

## 安全边界

Sericite 负责语言层的隔离和资源治理；addon 的参数校验、执行时间、内存、外部副作用和秘密保护由宿主负责。生产环境执行不可信代码时，应显式收紧配额、只授予必要能力，并增加独立进程或容器等操作系统级隔离。完整责任划分见[安全模型](../../security.zh-CN.md)。
