# ADR-0010: 错误分类归 contracts、重试/fallback 编排归 Kernel

- 状态：✅（2026-10-15）
- 背景：实扒三家重试/fallback/换模型逻辑全在 agent 层，而错误 `kind` 又来自 ProviderPort 归一化错误。若不划清，要么策略碰 provider（违反 C1）、要么 provider 长出策略逻辑。
- 决策：
  - **错误分类 = 纯函数，进 `contracts`（不 import 任何 provider 实现）**：输出结构化 verdict `{retryable, should_compress, should_fallback, should_rotate_credential}` + 稳定 `kind` 枚举；分类器可插拔 hook，失败 fail-to-builtin。
  - **重试/fallback/冷却的编排 = Kernel(L2)**：消费 verdict，按边界执行（primary 满预算、链每环一次、退避封顶、run 内粘、跨 run 复位）。
- 后果：策略层不碰 provider、provider 不长策略；分类与循环解耦、可单测。代价=需维护一张"阶段优先级分类表"（顺序即语义）。
- 关联：`design/04-turn-loop.md §13`、`design/02-event-protocol.md §10`、C1/C5。
