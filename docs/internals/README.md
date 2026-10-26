# 内部原理

这一层回答"**它是怎么跑起来的**"。`docs/architecture/` 讲结构意图与生成的关系图，
`docs/plan/` 记录施工进度；这里只讲机制本身，且以代码为准。

## 阅读路线

| 篇目 | 回答什么 |
| --- | --- |
| [01 Turn 生命周期](01-turn-lifecycle.md) | 一次对话从输入到结束到底发生了什么 |
| [02 事件与状态](02-events-and-state.md) | 引擎产出什么、谁有权改状态 |
| [03 工具与权限](03-tools-and-permissions.md) | 工具怎么被调用、权限在哪一层裁决 |

建议按顺序读。三篇合起来大约 30 分钟，足以看懂 `src/questorharness/engine/` 的主干。

## 贯穿全层的三条不变式

1. **单写者**：只有 `Command` 能改状态；`Event` 是输出，不反哺状态。
2. **单向依赖**：内层不 import 外层的具体实现，方向由 `.importlinter` 机械执行。
3. **fail-closed 优先**：权限、凭据、沙箱这类安全判定，默认值一律取"拒绝"或"不降级"。

任何一篇里出现的"例外"，都能在 [ADR](../adr/README.md) 里找到对应决策；找不到就说明
文档或代码有一方错了。

## 与其它文档的分工

| 文档 | 回答什么 |
| --- | --- |
| 本文与三篇子文档 | 机制如何运转，读代码前先看 |
| [架构说明](../ARCHITECTURE.md) | 当前仓库布局、依赖方向、运行时数据目录 |
| [docs/architecture/](../architecture/README.md) | 目标结构、生成的关系图与目录树 |
| [docs/adr/](../adr/README.md) | 为什么这样设计、放弃了哪些替代方案 |
| [docs/plan/](../plan/01-structure-hardening.md) | 分阶段施工台账与验收记录 |
