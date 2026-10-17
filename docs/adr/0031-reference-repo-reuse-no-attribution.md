# ADR-0031: 参考仓复用已获全体作者授权、取消文件内来源标记要求

- 状态：✅（2026-10-17）
- 背景：`AGENTS.md §4.5/§5.6` 与 `CONTRIBUTING.md` 注释规范此前要求"凡改造自参考项目的代码，必须文件内标 provenance + 保留上游许可声明 + CHANGELOG 注明出处"。使用者声明：`project-main/` 下**所有参考仓（含上游为 PolyForm Noncommercial 的 EvoFlow `evopanel`）的原作者均已授权本项目使用其代码，并明确要求不在本仓任何文件内保留来源标记/署名**。
- 决策：**取消"标 provenance / 保留上游许可声明 / CHANGELOG 逐条列来源 / audit-licenses 记出处"这一硬性要求**。改造或并入的参考实现按本仓普通代码书写，代码注释只引用**本仓自身**依据（`ADR-xxxx`、`HARD Cn`、`docs/design/*`）。**已同步修订 `AGENTS.md §4.5/§5.6` 与 `CONTRIBUTING.md`**，保留两条不变 guardrail：① 复用仍守分层/端口（HARD C1/C14）；② 优先适配本仓契约、而非逐行照抄。
- 后果：
  - 正面：与原作者意愿一致；代码不携带外部来源标记；降低注释/CHANGELOG 维护负担。
  - **面向未来生效**：已完成阶段（P0–P5）与 `docs/log/` 交付的源码中**既有的 provenance 注释保持不变**——它们如实记录了当时的做法，回改会造成文档与账本失真（违 AGENTS §5.5）且属代码改动。历史 ADR（0027/0028/0030）、CHANGELOG、审计报告、已完结阶段计划（00–05）中的 provenance 表述作为**历史记录保留**，不逐一改写；本 ADR 是往后工作的准绳。
  - 需持续守：许可合规的最终责任由维护者承担（使用者声明已获全体作者授权）；本仓以 MIT 发布，第三方上游许可义务不在本文判定范围。
- 备选(被否)：
  1. 保留"标 provenance + 保留声明"要求 → 否（违全体原作者明确要求）。
  2. 回头删改已合入源码 / 历史文档里的 provenance → 否（篡改已完成工作的记录，违 §5.5；且属代码改动，越界）。
  3. 只改本 Phase 计划、不动 rulebook → 否（规则书与现实长期不一致，正是 ADR-0012 当初否掉的"挂着规则却一直绕过"）。
- 关联：`AGENTS.md §4.5/§5.6`、`CONTRIBUTING.md`（注释规范）、HARD-CONSTRAINTS C1/C14、[`ADR-0012`](./0012-branch-policy.md)（同类"口径切换、追加记录不改原文"范式）、[`../plan/07-p7-desktop-shell.md`](../plan/07-p7-desktop-shell.md) §0.1 署名口径注。
