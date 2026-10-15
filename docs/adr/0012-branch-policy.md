# ADR-0012: 分支与推送策略（pre-alpha 维护者直推 main，CI required check 上线后转 PR）

- 状态：✅（2026-10-15）
- 背景：GitHub 上 main 已开分支保护（*Require a pull request before merging*），但实际开发是**单人多窗口并行、直推 main 并靠管理员 bypass 通过**——保护规则长期被绕过 = 形同虚设，且与 `CONTRIBUTING.md` 写的"切分支→PR→等 CI"**不一致**（活文档要求现实与文档对齐，AGENTS §5.5）。另因当前 `.github/workflows` 尚未建立，PR 没有 required status check，走 PR 也只是"没人 review 的空转"。
- 决策：分两步走。
  1. **现在（A，pre-alpha / P0–P6）**：**维护者可直推 `main`**；GitHub 保留保护规则 + 明确允许管理员 bypass（*Allow administrators to bypass*，这是**有意识的选择**而非意外）；外部贡献者走 **fork + PR**。`CONTRIBUTING.md` 与 `AGENTS §6` 同步该口径。
  2. **升级触发条件（B）**：当 `.github/workflows` 里出现**可当 required status check 的门禁**（lint + 冷导入 + pytest + 分层守卫至少一条为 blocking）时，**切换为全量 PR 流**：每功能/每 Phase 一个分支 → PR → required checks 绿 → 合并；并把 GitHub 保护改为**不再允许管理员 bypass 合并**。
  3. 升级动作本身要在此文档追加一条"已于 <commit/tag> 切换到 B"的说明（不回改原始决策）。
- 后果：文档与现实一致、不再产生"违规但靠 bypass 掩盖"的噪音；代价=pre-alpha 阶段缺少 PR 这道强制评审（由 AGENTS §5 DoD + 独立审计窗口的报告机制部分替代）。
- 备选(被否)：
  - 立刻全量走 PR：CI required check 还不存在，PR 无实际门禁、单人自批无意义 → 否（留作 B）。
  - **关掉** main 的分支保护：失去 force-push/删除保护与外部 PR 门禁，倒退 → 否。
  - 保持"规则挂着但一直 bypass"：规则形同虚设、换机器操作会突然失败、文档与现实长期不一致 → 否。
- 关联：`CONTRIBUTING.md`（提交流程）、`AGENTS.md §6`、`STRUCTURE §10`（CI 分道 [P0+]）、`HARD-CONSTRAINTS C15`（守卫必须可信、独立 blocking job）。
