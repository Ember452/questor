# ADR-0052: L0 新增 profile 词汇——mode 归一严格精确，权限预设只收紧

- 状态：✅（2026-10-20）
- 背景：权限模式（`default|plan|full_auto`）在 Python 侧曾有 5 处各自写字面集——`kernel/permission_policy.PermissionMode`、
  `kernel/subagent_permission._MODE_RANK`、`state/reduce.py` 的合法集、`surfaces/http_sse.py` 的合法集、
  `capabilities/subagent/delegate.py` 的 `params.mode.enum`。同一份仓里 5 处能各自漂移；而 OPT-4 还需要比
  "改 mode"更细的**收紧**表达（只读档、审批 never、敏感路径拦截），否则"更严"只能在调用点手工拼 `PermissionCtx`
  字段，漏一个就是权限缺口。
- 决策：
  1. **词表落 L0**：`contracts/profile.py` 定义 `MODE_DEFAULT/MODE_PLAN/MODE_FULL_AUTO`、`PERMISSION_MODES`
     （**顺序 = 协议顺序**，参与 `ProviderRequest.tools` 字节形态）、`PERMISSION_MODE_SET`、`PERMISSION_MODE_RANK`；
     上述 5 处 Python 真源全部改为引用它（OPT-3 c4）。
  2. **新增 profile 词汇**：`profile` 是"一束收紧旋钮"的名字（本轮 `default` / `read_only`），**不是 mode 的别名**；
     `permission_preset_for(profile)` 返回 frozen `PermissionPreset`，未知/None 回落 `default`（不抛）。
  3. **归一严格**：`normalize(raw)` 只认 canonical 精确值，未知/None 回落 `default` 且**不抛**；刻意**不做**
     `strip`/大小写/别名映射。
  4. **预设只收紧**：`PermissionPreset` 只携带 `mode`（只许更严或 None）、`approval_policy`（`ask|never`）、
     `protect_sensitive_paths`（只许 True）、`enforce_read_only`（只许加）；不含任何 sandbox/capability 字段，
     因此**结构上不可能放宽 capability floor**（C9/C17，floor 只由 sandbox + capability 事实决定）。
- 后果：
  - 正面：Python 侧"合法 mode 是什么"只剩一处；收紧动作可复用、可单测，且"不得放宽"由字段形状保证而非纪律。
  - 代价：新增一层词汇需要 ADR/文档同步；本轮 `profile` **没有生产调用点**（只有单测覆盖），接线属后续刀。
  - 需持续守：`normalize` 一旦"宽容"，`/permissions` 与 `delegate` 参数的拒收面就会静默变宽——那是行为变更，
    必须先改 wire 真源（`protocol/event.schema.json`）与前端派生（P10 协议生成），不能在 Python 侧先行。
- 备选（被否）：
  1. **把 `PermissionMode` 枚举当唯一真源**：否——枚举在 L2 kernel，`state/`（L1）不得反向 import；词表要能被
     L0/L1/surfaces 共用，只能落 contracts。
  2. **`normalize` 做 `strip().lower()` + 别名（`auto` → `full_auto`）**：否——放宽输入面 = 行为变更，
     且会让 Python 与 wire/前端语义分叉。
  3. **引 pydantic `BaseSettings` 做配置并顺带做词表校验**：否——配置层刻意 stdlib-only（横切薄层），
     且新增依赖属 R7 依赖冻结。
  4. **把 `read_only` 并进 mode 当第四档**：否——会改 wire 枚举（`event.schema` + 前端 + 冻结断言），
     而"只读"是**收紧旋钮的组合**，不是 mode 的第四档。
- 关联：[`docs/design/00-layering.md`](../design/00-layering.md)（L0 词汇层）、`HARD-CONSTRAINTS` C1/C9/C14/C17、
  [`ADR-0014`](./0014-permission-context-authoritative.md)（权限求值顺序）、
  [`ADR-0040`](./0040-child-permission-inheritance-narrowing.md)（子⊆父、mode 不继承）、
  `protocol/event.schema.json`（wire 真源）、`kernel/permission_policy.py`、`state/reduce.py`、
  `surfaces/http_sse.py`、`capabilities/subagent/delegate.py`。
