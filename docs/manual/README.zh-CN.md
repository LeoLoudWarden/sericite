# Sericite 手册

项目仓库：<https://github.com/LeoLoudWarden/sericite>

本手册说明如何编写和运行 Sericite 程序，以及如何把 Python 参考引擎嵌入现有应用。这里记录公开行为和使用契约，不展开项目设计历史或引擎内部实现。

!!! note "版本说明"

    在线手册的最新版跟随 `main` 分支更新，可能与 PyPI 最新发行版不一致。

## 选择手册

| 手册 | 适合读者 | 内容 |
|---|---|---|
| [脚本手册](scripting/README.zh-CN.md) | Sericite 脚本作者 | 语言、内建、record、错误、文件、VM 与 VFS |
| [命令行手册](cli/README.zh-CN.md) | 运行程序的操作者 | 命令、多文件项目、可信 addon、标准输入输出与退出码 |
| [Python 宿主手册](host-python/README.zh-CN.md) | Python 嵌入者 | 引擎 API、VM 生命周期、工作区、addon、调试与观察 |

脚本手册可以独立阅读。需要从终端运行程序时读命令行手册；需要由 Python 应用创建和控制 VM 时读 Python 宿主手册。

当前 Python 参考实现需要 Python 3.12 或更高版本，没有第三方运行时依赖：

```bash
pip install sericite
```

## 指南与 API 参考

每套手册包含两类页面：

- **指南**围绕任务组织示例和解释，适合学习一项工作流程。
- **API 参考**定义参数、返回值、错误和其他精确契约，适合查询具体接口。

指南不代替参考，参考也不重复所有入门示例。

## 安全使用总则

Sericite 为隔离而设计，但当前原型在部署时仍需注意：

- Python 引擎与宿主同进程运行，尚未经过正式的外部安全审计。执行真正的对抗性代码时，不要把 Sericite 当作唯一隔离边界；应增加独立进程、容器或其他操作系统级隔离。
- 默认配额面向开发调试，不是安全建议。运行不完全可信的代码时，应显式设置限额。
- CLI addon 文件和 Python 宿主回调都是沙箱之外的可信代码。参数校验、CPU、内存、阻塞、外部副作用和秘密保护由宿主负责。
- 只授予程序确实需要的能力。授予函数暴露的不只是一个函数名，还可能包括其定义方能够访问的状态与能力。

隔离、限额和能力授予的示例见[脚本安全指南](scripting/guides/07-vm-safety.zh-CN.md)、[CLI addon 指南](cli/guides/03-addons.zh-CN.md)和 [Python addon 指南](host-python/guides/03-addons.zh-CN.md)。
