# Phase NN 详细计划 — <标题>

> 起手**必读**：[`AGENTS.md`](../../AGENTS.md) · [`docs/ROADMAP.md §3`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)
> 目标：把本 Phase 的**可验证判据（DoD）· 子任务 · 契约/红线自检** 写清楚即可开工。

## 0. 既有依据与接缝（本项目自身）

列出本 Phase 要复用/扩展的**本仓已有**契约与设计：相关 `docs/design/*`、`docs/adr/*`、已有 Port/模块（`file:line`）· 本 Phase 在其上**只加不改**还是**需新 ADR**。

| 能力 | 既有依据（本仓 design/adr/Port） | 结论（复用既有接缝 / 新增 · 需否 ADR） |
|---|---|---|
| <能力 A> | <design/0X §y; ADR-00N; contracts/…> | 复用既有接缝 |
| <能力 B> | … | 新增（先记 ADR） |

> 前端能力另注：UI 只当**瘦客户端**、仅消费事件协议、零业务下沉（C14 / ADR-0007）。

## 1. 目标与可验证判据（DoD）
- **进入条件**：对齐 ROADMAP §1 表。
- **DoD**（本 Phase 收尾的可复现行为，不是"完成感"）：…

## 2. 子任务清单
每条写：**目标 · 涉及层 · 依赖 · 验证方式 · commit 粒度**。
- [ ] T1 …
- [ ] T2 …

## 3. 契约与红线自检
- 触及分层/契约？□ 是（**先记 ADR 再动**） □ 否
- 逐条对照 `HARD-CONSTRAINTS` C1–C20：无违反；如有例外 → ADR。
- 动到本阶段涉及的子系统前，先查 [`docs/pitfalls.md`](../pitfalls.md) 对应分区（跳线程/子进程关联、载荷进观测面、事件被节流合并…）。
- 事件协议：只增字段？不破信封/关联键/终止序？

## 4. 测试与回归
- 单元 / 集成 / **evals 任务级**（P10 前必备）
- 冷导入 + `import-linter` 分层守卫通过
- 外部事件契约快照 diff 通过

## 5. 落地风险 & 备选
| 风险 | 触发条件 | 缓解 | 备选 |
|---|---|---|---|

## 6. 收尾（活文档，AGENTS §5.5）
- [ ] 回填"实际 vs 计划偏差"到 `docs/adr/` 或 design/*
- [ ] 更新 ROADMAP §1.5 备注
- [ ] CHANGELOG `[Unreleased]` 追加
- [ ] 相关 design/0X 若已定稿有变化 → 就地修订
