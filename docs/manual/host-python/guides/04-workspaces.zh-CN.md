# 准备工作区

每台 VM 的文件操作都作用于自己的虚拟文件系统（VFS）。Python 宿主可以预先准备文件和模块，把完整工作区移入 VM，并在会话结束后取回结果。

## 从工作区入口运行项目

下面的示例准备输入文件、模块和入口文件：

```python
from sericite import SericiteEngine

engine = SericiteEngine()
fs = engine.create_vfs()
fs.write_file("/input.txt", "hello")
fs.write_file("/util.sericite", "suffix = '!'\n")
fs.write_file(
    "/main.sericite",
    "import util\n"
    "text = read_file('/input.txt')\n"
    "write_file('/result.txt', text + util.suffix)\n",
)

vm = engine.create_root(entry_file="/main.sericite", fs=fs)
assert vm.run() == ""

fs = vm.take_fs()
assert fs.read_file("/result.txt") == "hello!"
vm.dispose()
assert fs.path_exists("/result.txt")
```

`entry_file` 必须与 `fs` 一起提供。引擎从工作区读取并编译入口，以入口所在目录作为模块解析根；`read_file()`、`write_file()` 等文件操作仍以工作区根为基准。上例的 `import util` 因而读取 `/util.sericite`，不会搜索 Python 的模块路径或真实磁盘。

如果直接使用 `source` 并同时提供 `fs`，模块从工作区根解析。`source` 与 `entry_file` 必须恰好选择一种，详细参数见[引擎与配额](../reference/01-engine-and-limits.zh-CN.md#sericiteenginecreate_root)。

## 工作区的所有权与句柄

VFS 不是由多个执行会话共同读写的共享对象。理解移交时，需要区分两个问题：

- **文件树依附在哪里**：分离的文件树由宿主通过有效的 `VFSHandle` 操作；依附的文件树由一台 VM 独占，脚本和宿主通过该 VM 访问。
- **宿主句柄是否还有效**：成功把文件树移入 VM 后，原来的 `VFSHandle` 失效；以后取回文件树时会得到一个新句柄。

`create_root(..., fs=fs)` 只有在创建全部成功后，才同时提交文件树依附并使原句柄失效。源码编译、入口读取或参数校验失败时，文件树仍分离，原句柄也仍可操作。成功创建后，应通过 VM 访问文件，不要继续使用原来的 `fs`。

终态 VM 的 `take_fs()` 原子取出文件树，使其重新分离，并返回一个新的有效句柄。允许的状态是 `done`、`error`、`resource_exhausted` 和 `terminated`；如果程序仍在等待输入或暂停，可以先继续执行，或明确 `terminate()` 后取回。

取出后，原 VM 仍可读取快照和 stdout，也可以销毁，但失去文件访问能力且不再接受 `exec()`。销毁原 VM 不影响已经取回的工作区。失败操作不会改变所有权或句柄有效性。

移交的只有文件树。模块缓存、局部变量、虚拟 IO、addon、断点、模块解析根和累计资源用量都仍属于原会话。取回工作区后修改模块文件，再把工作区移入一台新 VM，新会话会重新导入修改后的代码。

## 宿主可以直接管理文件

`VFSHandle` 和宿主 `VMHandle` 都提供文件与目录方法。例如，在会话结束后、取出工作区前，宿主可以检查或补充文件：

```python
vm.write_file("/host-note.txt", "prepared by host")
assert vm.read_file("/host-note.txt") == "prepared by host"
```

这两类句柄的区别是：

- `VFSHandle` 只操作处于分离状态的工作区；
- `VMHandle` 操作该 VM 当前依附的工作区。

它们是可信宿主管理通道，不计入脚本资源计量，但文件数、单文件大小和总存储量等限制仍然有效。脚本内的 VM 句柄不提供这些文件代理；脚本只能操作当前会话的文件或使用显式持有的分离 VFS。

全部方法、路径规则和错误见[VFS 与文件参考](../reference/03-vfs-and-files.zh-CN.md)，通用的路径和目录行为由[脚本文件参考](../../scripting/reference/04-files.zh-CN.md)定义。
