# Security Policy

## Reporting a vulnerability

请优先使用 GitHub 的 **Private vulnerability reporting**（仓库页面 → Security → Report a vulnerability）私下报告安全问题。在修复发布前，请不要公开披露细节。

Sericite 是一个引擎，其设计目标是隔离不可信代码。以下情形属于安全模型的覆盖范围：

- 脚本绕过 VM 隔离，读写父级/宿主状态；
- 脚本绕过资源配额（指令、内存、输出、VM 数量等）；
- 错误信息、调试视图泄漏宿主路径、密钥或内部实现细节。

以下情形**不属于**引擎的安全责任，见 [docs/security.zh-CN.md](docs/security.zh-CN.md)：

- 宿主通过 FFI 授予的函数内部的安全性（由授予方负责）；
- 宿主函数的执行耗时与内存（不按指令计费）；
- 当前原型与宿主同进程运行，尚未经过正式的外部安全审计。生产环境执行对抗性代码时，不应把 Sericite 作为唯一的隔离边界。

## Supported versions

| Version | Supported |
|---|---|
| 0.11.x | 是 |
| 0.10.x | 是 |
| 0.9.x | 是 |
| 0.8.x | 是 |
| 0.7.x | 是 |
| 0.6.x | 是 |
| 0.5.x | 是 |
| 0.4.x | 是 |
| 0.3.x | 是 |
| 0.2.x | 是 |
| 0.1.x | 是 |
