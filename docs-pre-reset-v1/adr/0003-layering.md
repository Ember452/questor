# ADR-0003: 八层分层 + 依赖倒置 + Harness=pure mechanism

- 状态：✅（2026-10-15）
- 背景：VISION 初版"四层"太粗、也没说"怎么不把自己框死"。参照 6 个真实项目的分层，需一版够细、又不焊死的架构。
- 决策：分 **L0 Contracts / L1 Domain-State / L2 Kernel-Harness / L3 Capabilities / L4 Policy / L5 Ports / L6 Surfaces / L7 Shell** + 横向(config/DI 插件宿主/observability/权限)。
  - **依赖倒置**：内层定义接口、外层实现，内层永不 import 外层。
  - **Harness = pure mechanism**（承 DeepCode 纪律）：只调度/判权限/写状态/发事件，**绝不 import 模型或 UI**。
  - **Agent 策略是可插拔组件**：只读状态快照→返回意图，换算法/灰度只动 L4。
  - 每条边界=可插拔注册点 + 只增不改契约；分层是"依赖纪律"不是牢笼。
- 后果：经常变(L4)与尽量不变(L1-L2/L5/L7)隔离 → 长期可维护；代价是要靠 CI/类型把边界守住（HARD-CONSTRAINTS C1）。
- 备选(被否)：粗四层（会退化成"什么都往 kernel 塞"）→ 否。
- 关联：[`../design/00-layering.md`](../design/00-layering.md)、[`../design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)。
