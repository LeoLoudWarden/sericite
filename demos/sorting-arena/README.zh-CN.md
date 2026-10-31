# sorting-arena：不可信代码排序竞技场

[English](README.md)

九份互不信任的 Sericite 源码进入一个裁判系统：三份正常排序算法靠指令数争夺名次，六份捣乱提交以不同方式失败。裁判继续工作，只有当前选手出局。

这是一个无需 LLM、无需网络、无第三方依赖的完整应用。它重点展示 `root-agent` 之外的一条主线：**隔离不只是让代码"跑不出问题"，还能把每份不可信代码的执行变成可比较、可淘汰的比赛。**

## 运行

在仓库根目录执行：

```bash
uv run sericite \
  --capabilities demos/sorting-arena/capabilities.py \
  demos/sorting-arena/arena.sericite
```

输出依次是每位选手的试跑过程和最终积分榜。每次启动都会生成新题目，因此积分和名次可能不同。下面是一次实际运行；指令数是引擎账本，不是耗时：

```text
╭─ FINAL STANDINGS ────────────────────────────────────────────────────╮
  RANK  CONTESTANT                  TOTAL INSTRUCTIONS
  1     quicksort               12,028
  2     insertion-sort          20,815
  3     bubble-sort             41,352
  DQ    wrong-answer            wrong_answer
  DQ    answer-thief            file_not_found
  DQ    output-flood            resource_exhausted
  DQ    infinite-loop           resource_exhausted
  DQ    vm-spawner              resource_exhausted
  DQ    input                   input_error
╰──────────────────────────────────────────────────────────────────────╯
  The arena survived every submission. The scoreboard only counts correct code.
```

## 比赛规则

每份选手源码都是完整、独立的 Sericite 程序：

1. 从 `/input.txt` 读取一组以空白分隔的整数；
2. 把升序结果以空白分隔写入 `/output.txt`；
3. 通过全部四组测试后，按各测试的 `instruction_count` 总和排名；任何一组失败即失去排名资格。

每组测试都创建一台全新子 VM，只预置 `/input.txt`。裁判把预期答案留在自己的世界，不授予任何函数，也不转发选手输出。选手之间没有可共享的可变状态；其他隔离边界见[安全模型](../../docs/security.zh-CN.md)第 2 节。

调用 `input()` 的选手会在等待输入时按 `input_error` 淘汰，即使它已经写入答案也不例外。

失败分为几类：

| 失败类型 | 示例提交 | 结果 |
|---|---|---|
| 答案不正确 | `wrong-answer` | 失去排名资格 |
| 访问不可见文件 | `answer-thief` | `file_not_found` |
| 耗尽配额 | `output-flood`、`infinite-loop`、`vm-spawner` | `resource_exhausted` |
| 等待不可用输入 | `input` | `input_error` |

`entries/` 中还有三份正常排序算法；积分榜只统计通过全部测试的提交。正确性检查先于指令数排名：跑完不等于答对。

## Python 随机性如何进入裁判

Sericite 本身不内置随机数。`capabilities.py` 把 Python 的 `random.randrange(below)` 包装成 `random_int(below)`，通过 `functions` 显式授予 root 裁判。`arena.sericite` 每次启动构造四类题目，每类 24 个整数：

- `mixed`：0～99 的随机整数；
- `reversed`：生成随机整数，排序后反转；
- `nearly sorted`：生成随机有序数据，再随机交换四对位置；
- `duplicates`：0～9 的随机整数，制造大量重复值。

`nearly sorted` 额外调用 8 次 `random_int` 来选择交换位置。

`random_int` 只授予 root；创建选手 VM 时没有传 `functions`，所以选手不能调用它。授予不会自动跨层继承的完整规则见[虚拟机参考](../../docs/vm-reference.zh-CN.md)第 6 节。

每组测试的主要配额（完整字段见 `arena.sericite` 中的 `run_case()`，字段语义见[虚拟机参考](../../docs/vm-reference.zh-CN.md)第 5 节）：

| 配额 | 值 | 本 demo 中的作用 |
|---|---:|---|
| `max_instructions` | 120,000 | 限制死循环的指令数 |
| `max_output_bytes` | 512 | 截停输出洪水 |
| `max_child_vms` | 0 | 禁止选手派生 VM |
| `max_frames` | 64 | 限制调用深度 |
| `max_total_bytes` | 1 MiB（近似账本） | 限制内存增长 |

## 添加自己的选手

在 `entries/` 中新增一个 `.sericite` 文件即可，文件名形如 `10-my-sort.sericite`。

启动配置按文件名排序播种；裁判显示时会去掉前三位字符和扩展名。因此三位数字前缀适合控制出场顺序。

无需修改 `capabilities.py` 或 `arena.sericite`。可以尝试更快的算法，也可以提交新的捣乱程序，观察裁判是否仍能完成比赛。

## 文件与信任边界

- `arena.sericite`：全部应用逻辑，包括测试数据、参考答案、VM 生命周期、验题、计分和排行榜。
- `capabilities.py`：可信的薄启动配置。它读取本目录的 `entries/*.sericite`，作为**文本**放进 root VFS，向 root 授予 `random_int`，并提高可信 root 的总指令预算。它不会执行选手源码。
- `entries/`：模拟来自不可信数据源的提交，既有正常算法，也有故意失败的选手。

选手是 Sericite，不是 Python，不会经过 `exec`/`eval`。真正执行对抗性代码时，仍应在引擎外增加 OS 级隔离；完整边界见[安全模型](../../docs/security.zh-CN.md)。
