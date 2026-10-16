# ADR-0012: 分支与推送策略（pre-alpha 维护者直推 main，CI required check 上线后转 PR）

- 状态：✅ 已按第 3 条于 **2026-10-16 切换到 B**（全量 PR 流）——见文末「切换记录」；下方原始决策作为历史保留，不回改。
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

---

## 切换记录（追加于 2026-10-16，不回改上方原始决策）

**触发条件已满足 → 口径切换为 B（一律 branch + PR）。**

- **事实依据**：`ci-python.yml` 的 `boundaries` job 自 P0 起就是**独立 blocking**（不依赖 change classifier，C15）——即 ADR 第 2 条说的"可当 required status check 的门禁"已存在；P2 T20 又补了 `check_output_budgets` / `check_secret_projection` 两条可判红守卫，并把 push 触发从"仅 main"改为全分支（commit `1892fb3`），Windows 真机 leg 在 PR / dispatch / 进 main 时跑。
- **已同步的文档**：`CONTRIBUTING.md` 提交流程、`AGENTS.md §6` 分支口径均已改为 B。
- **仍需维护者在 GitHub 侧手动完成（本仓 agent 无网络，既不能代做也不能验证，故如实列成待办而非宣称已完成）**：
  1. Settings → Branches → 保护规则：在 **Require a pull request before merging → Required status checks** 加入 `boundaries`（必选）与 `tests-posix`。关于 `tests-windows`：**它在 PR / dispatch 事件上是会真跑的**（job 条件是`event_name != 'push' || ref == refs/heads/main`），**只有功能分支的纯 push 会把它置为 skipped**；skipped 的 required check 在不同时期/配置下行为并非完全一致，因此建议：先只把 `boundaries` + `tests-posix` 设为 required，观察一次 PR 上 `tests-windows` 的报告形式后再决定是否加——不要凭印象把它排除在门禁之外，也不要凭印象直接勾上。
     实测修正：上文曾经写“必须先合一个跑通的 PR，check 名才会出现在候选里”——不必。把 push 触发扩到全分支后，分支自身的 run 就会上报 check，候选框里已经能搜到。
  2. 同页把管理员绕行关掉：勾选 **Do not allow bypassing the above settings**（等价于撤销原 A 案刻意保留的 *Allow administrators to bypass*）。
  3. **规则模式必须只匹配 `main`，不能是 `*` / `feat/**`**（这是切换当天真碰上的事）：对功能分支也开启 Require PR 后，**连更新一个开放中 PR 的 head 分支都推不上去**，GH013 原文：`Changes must be made through a pull request` + `2 of 2 required status checks are expected`。后果是死锁：CI 红了却无法推修复。B 案要的是“**进主干**必须走 PR + 绿 checks”，而不是“每个分支都不许直接提交”。
- **在上述各项（尤其第 2、3 条）落地前，现实是"口径已 B、强制力不完全"。** 这句留在这里，是为了不让文档假装闸门已经关闭——A 案当初被否掉的正是"规则挂着但一直 bypass"的自欺。
