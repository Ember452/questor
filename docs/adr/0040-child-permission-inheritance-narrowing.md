# ADR-0040: 子权限继承收缩——fail-closed + 命名空间审批（子 ⊆ 父，永不放大）

- 状态：✅（2026-10-18，P8 开工前置门；实现见 `docs/plan/08-p8-multi-agent-dag.md` T7）
- 背景：子 agent = 独立 `Run`（[ADR-0038](./0038-subagent-as-independent-run.md)），各自持 `PermissionCtx`。若"继承"父的 `PermissionCtx` 可被放宽，则 `full_auto` 会传染给子、`denylist`/capability floor 被绕过——正是 [ADR-0014](./0014-permission-context-authoritative.md)/[ADR-0015](./0015-sandbox-capability-floors.md)/HARD C17 严禁的"把配置便利变成不可逆损害面"。peer 参照：hermes `subagent_lifecycle.py:471-473` 用"requested toolsets 非父 enabled 子集即拒（would broaden parent permissions）"+ `:231` "always blocks unsafe child tools"。
- 决策（默认 **fail-closed**，spawn 时由端口算 `child_ctx = project_parent_permission(parent_ctx, request)`）：
  - **`denylist`（权威语义）**：`child.denylist = parent.denylist ∪ {本次新增}`——只能扩大或相等，**绝不含父所禁路径**。denylist 不可被 mode/rules 覆盖（C8/C17/ADR-0014）。
  - **`rules`**：`child.rules ⊆ parent.rules`（按 (tool_pattern×argument_pattern×action) 逐条为父子集）；**禁止**给子新增"更宽松的 allow 规则"。求值仍 last-match-wins + 纯函数（ADR-0014）。
  - **`mode`**：v1 **不继承父 mode**——子默认 `mode=default`（最保守）。`full_auto` 属父的审批偏好，不得自动传染子（把"便利"与"隔离"分开）。父若确要子更宽，须**逐子显式提权**（仍受下面 floor 与 denylist 约束）。
  - **`approval_policy`**：子只能与父相同或更保守（`never` 不得比父更宽）。
  - **capability floor 高于 mode（ADR-0015/C17）**：子与父同 OS、同一 `SandboxDescriptor` 能力探针 → floor 完全相同；无写围栏的 write 至多 `ask`、缺能力 exec `deny`，**子不因"是子"而降档**。`full_auto`（即便显式提权）也不能伪造隔离能力。
  - **`workspace_root`/`cwd`**：子路径必须落在父允许范围内（不得越出父 workspace 边界新开损害面）。
  - **子 `ask` 归谁审批**：子 run 的 `ask` → 子自己的 `approval_request` 事件（信封 `run_id=child_rid`），由 surfaces 呈现给人；**父不代答**。父可 `Cancel(child)` 强制走 deny/超时路径。
  - **`request_id` 跨 run 幂等**：命名空间 = 前缀 `child_run_id`（如 `{child_run_id}:req_{seq}`），保证跨 run 全局唯一；[ADR-0016](./0016-tool-lifecycle-approval-identity.md) 的"同 request 同决策 no-op、异决策拒绝、迟到不翻案"仍 per-run 成立、无跨 run 串号。
  - **策略层无裸句柄（C4/C8）**：`PolicyView` 只加**只读** `task_tree`（既有），策略仅发 `ProposeSpawn/ProposePlanUpdate` 意图；建子 run/注册/提 Command 全在内核端口，策略拿不到 `RunController`/`RunRegistry`/`StorePort`。
- 后果：
  - 正面：默认最保守、可长期演进——多 agent 不会成为绕权限的后门；判据可证伪（DoD④：子 denylist ⊇ 父、rules ⊆ 父、父 full_auto 不降子 ask）。
  - 代价：父 `full_auto` 下子仍频繁 `ask`，"全自动编排"需显式逐子提权才顺滑——这是刻意的安全默认，非缺陷。
- 备选（被否）：
  1. **继承父 mode**：`full_auto` 传染子 → 无围栏执行不可逆损害面（违 ADR-0015）→ 否。
  2. **子可新增宽松 rules / 缩小 denylist**：直接放大权限，违子集不变式 → 否。
  3. **父代答子的 ask**：把子的独立审批边界抹平，`request_id` 幂等/审计口径漂移 → 否。
- 关联：HARD-CONSTRAINTS C4/C8/C9/C17；ADR-0014/0015/0016/0018；`contracts/permission.py`、`state/domain_state.py::PermissionCtx`；peer：hermes `subagent_lifecycle.py:231,471`（MIT，取判据）；`docs/plan/08-p8-multi-agent-dag.md` T7。
