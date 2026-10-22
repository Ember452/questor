# Questor Agent 策略契约（L4 Policy，04 的姊妹文档）

> 承接 [`04-turn-loop.md`](./04-turn-loop.md) §9、[`00-layering.md`](./00-layering.md) L4、HARD-CONSTRAINTS C1/C2/C4/C8/C10/C12。
> 定位：**L4 策略契约 + 注册/生命周期/热替换**，是"04=L2 机制"的纵深文档，**不是第六道承重接缝**（五接缝=可开发门槛不变）。

## 0. 边界（策略拥有什么 / 不拥有什么）
- **拥有**：提示词、能力选择(工具 allowlist)、算法(ReAct/ToT/反思/记忆策略)。
- **不拥有**：模型路由、审批/denylist、沙箱、持久化写。策略**只读状态视图 → 只发意图**；执行/校验/记账全在 Harness（03、C8）。

## 1. 三个核心类型（落 `contracts/policy.py`，纯 frozen 数据）
- **`PolicyView`**（策略唯一能读）：`context / task_tree / tool_results / memory / budget` 的只读投影；**不暴露** checkpoint/权限/LoopState/内部元数据。靠 COW/结构共享，不浅 frozen（C2）。
- **`PolicyIntent`**（策略唯一能产，= 不可信输入）：`ProposeToolCall | ProposePlanUpdate | AdviseCompact(仅advisory) | SuggestFinish | SuggestCancel`。`Suggest*` 只是建议，全局终止在内核（C7）。
- **`PolicyPort`**（协议）：`id / fingerprint / propose_action(view)->intent` + 可选 `init/dispose/on_tool_result`。**禁止** execute/沙箱/StorePort 写句柄出现在策略里。

## 2. `PolicyRegistry`（注册/发现/降级）
- 条目 `{id, factory, trust(system|user|project), tools?, broken?}`；信任优先级 project>user>system、最近根覆盖重名。
- **错误二分**：`UnknownPolicyError`（id 写错，附名册）vs `BrokenPolicyError`（加载/部署错，附 reason）；破损**留名不静默消失**。
- **降级 fail-open**：目标策略不可用 → 回落默认策略 + WARN，**绝不让 run 起不来**（C10）。
- P1 用**进程内硬编码单策略**即可（只验证"非法意图不崩"）；注册表/发现归 P9。**P9 落地（ADR-0045）**：`PolicyRegistry` 落 L4 `policy/registry.py`、进程内固定名册、**无磁盘扫描/HMR**；kernel **不 import registry**（解析在组合根/surface 得到 `PolicyPort` 再注入 loop，保 C1）；`Run` 与 `run_started` 带 additive `policy_ref{id,fingerprint}`（不 bump `v`）。

## 3. 三条关键语义（→ ADR-0009）
1. **热替换 = run 内快照冻结、换=新 run**：创建 run 时解析一次、按值快照 `policy_id+fingerprint`，整 run 用同一份；严禁活 run 中途 swap（撕裂状态/回放/审计）。
2. **A/B = 按 fingerprint 路由**：分桶键是内容指纹非版本号；`run_started` 事件带 `policy_ref{id,fingerprint}`（只增字段）；回归网用 `policy_ref` 做同任务多策略对比，全程不动内核。
3. **进程内默认、远程只预留**：`PolicyView/PolicyIntent` 保持纯 frozen 数据（天然可序列化）即止；**v1 不引入任何 RPC/传输**（C12）。

## 4. 与 04 的接缝
循环每轮只调一次 `propose_action(view)` → intent 映射 Command → 权限/校验/沙箱/reduce（04）。循环只认注入的 `PolicyPort`，**不 import 具体策略**（C1/C14，import-linter 守）。

## 5. 反思/记忆类策略（P4/P10）
后台"只读分支快照重放"，写操作经 `WriteMemory` Command，绝不在活 run 上改权威态（04 X4/C10）。

## 6. 待定（v0 后锁）
`PolicyView` 精确字段、`PlanOp` 形态。（**AB 分桶算法已于 P9/ADR-0045 定死**：`stable_hash(fingerprint) % n` + 算子可覆写显式 split 表，默认 n=1=不分流的安全默认。）
