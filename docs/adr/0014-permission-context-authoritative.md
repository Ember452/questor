# ADR-0014: PermissionCtx 是权限模式的唯一真源，权限引擎改为纯函数

- 状态：✅（2026-10-15）
- 背景：当前权限引擎在构造时自带 `mode/rules`，而权威 Domain_State 又另有 `PermissionCtx`；`SetPermissionMode` 若只改状态，实际求值仍读取旧引擎配置，形成两套真相。同时 `contracts.state_schema.PermissionRule` 与 kernel 内部 `Rule` 字段形状不一致。
- 决策：
  - `Run.permission_ctx` 是 mode、rules、denylist、approval policy、审批请求与决策历史的唯一持久真源。
  - 权限引擎不持有可变配置；每次求值接收 `PermissionCtxView + ToolSpec + ShellAnalysis + SandboxDescriptor`，返回 `PermissionOutcome`。
  - 统一持久化 `PermissionRule` 字段为 `tool_pattern`、`argument_pattern`、`action`、`scope`；kernel 不得再维护第二套规则类型。
  - `SetPermissionMode` 经 Command → reduce 修改未来调用，不回溯既有决策；同一 mode 的重复 Command 幂等且不产生 durable event。
  - 权限求值固定为：非法参数 → 敏感/受保护路径 deny → capability floor → rules → mode → approval policy → approval mode，后两者只可收紧或降级，不可突破前两道门。
- 后果：权限模式可在 UI、事件流、持久化与策略视图中保持一致；代价是调用点必须显式传入当前权限视图，且 checkpoint 必须完整序列化 `PermissionCtx`。
- 备选（被否）：
  1. 每次 mode 改变后重建引擎实例：隐藏写入口，且并发工具/恢复时易读到旧实例 → 否。
  2. 把 rules 只留在 surfaces/config：无法回放、审计与跨进程恢复 → 否。
  3. kernel Rule 与 state PermissionRule 并存：字段迁移必然漂移 → 否。
- 关联：ADR-0006、ADR-0015、ADR-0016；[`../design/01-state-model.md`](../design/01-state-model.md) §6、[`../design/03-tool-interface.md`](../design/03-tool-interface.md) §11。
