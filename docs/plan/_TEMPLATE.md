# Phase NN 详细计划 — <标题>

> 起手**必读**：[`AGENTS.md §4.5`](../../AGENTS.md) · [`docs/ROADMAP.md §3`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)
> **§0 未填完 = 本 Phase 计划未就绪、不能开工**（ROADMAP §0 硬门槛）。

## 0. Peer-Repo 扫描（**必填**，AGENTS §4.5 · 综合取优）

**先重列 `project-main/` 目录**（新增自动纳入，非固定清单；上次刷新 2026-10-15 含 12 仓：
`hermes-agent / wuu / DeepCode / CowAgent / MetaGPT / cordis / EvoFlow / autogen / crewAI / OpenManus / GenericAgent / Agent-S`）。
再逐个能力填表；**"自写"必须有原因**（无参考实现 / 与本项目契约不兼容 / 参考实现质量不足）。

| 能力 | 扫描仓（`file:line`） | 结论（复用/改造/自写） | 复用/改造说明 · 许可/署名注意 |
|---|---|---|---|
| <能力 A> | <repo:path:line>; <repo:path:line> | 改造 | |
| <能力 B> | … | 自写（<原因>） | |

> 前端能力另注：**同栈优先源 = DeepCode Tauri v2 / EvoFlow evopanel**；改造后仍守"UI 只消费事件协议、零业务下沉"（C14 / ADR-0007）。

## 1. 目标与可验证判据（DoD）
- **进入条件**：对齐 ROADMAP §1 表。
- **DoD**（本 Phase 收尾的可复现行为，不是"完成感"）：…

## 2. 子任务清单
每条写：**目标 · 涉及层 · 依赖 · 验证方式 · commit 粒度**。
- [ ] T1 …
- [ ] T2 …

## 3. 契约与红线自检
- 触及分层/契约？□ 是（**先记 ADR 再动**） □ 否
- 逐条对照 `HARD-CONSTRAINTS` C1–C19：无违反；如有例外 → ADR。
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
