# R10 · 接口骨架外部参考扫描（→ docs/plan/00-design-skeleton.md）

> **只读实扒产物，非实现。** 为 P0「可编译接口骨架」找**可采纳的分层强制方式 / Port 抽象范式 / 状态与事件的不变式建模**。
> 方法：读全相关模块，结论一律带 `文件:行号`（相对各仓根）；先读现有 design/plan 再提增量。
> 触发：写 `plan/00` 时的 AGENTS §4.5 扫描；本会话实测（非仅引用 R01/R03/R08）。
> 证据项目：**DeepCode-main**（架构最接近八层，Python）、**wuu-main**（Go，Kernel↔Policy 契约）、**crewAI / CowAgent / OpenManus**（旁证）。

---

## ① 结论（增量总览）

P0 骨架需要的四类"形状"，参考集里都有可抄的成熟范式，但**分层强制这一维全参考集集体缺位**：

1. **分层靠机器守**——`import-linter`/`banned-api`/`TID251` 在 12 仓 **grep 命中 0**；连最讲分层的 DeepCode `pyproject.toml` 也只配 `line-length/target-version/ignore E402`（`:19-29`），**无任何边界规则**。→ 我们的三防线是超前设计、**须自写**（正面验证 R09 记忆结论）。
2. **Port 抽象**——DeepCode 用 `typing.Protocol`（结构化、可 `@runtime_checkable`）定义窄端口面、用 `ABC`+`NotImplementedError` 做需实例化的基类：两范式并存。→ 直接对上我们"注入端口用 Protocol、stub 基类用 ABC"。
3. **不变式建模**——DeepCode 领域层把不变式写进 `@dataclass(frozen=True, slots=True)` 的 `__post_init__`（seq>0、id 前缀、tz-aware、终态↔completed_at 交叉校验），是"接缝锁形、字段 draft"的最佳落地样板。
4. **跨语言 wire 单一真源**——DeepCode repo 根 `protocol/app-server.schema.json`（8312 行 JSON-Schema）承载服务端↔客户端契约，正是 C15 的活样本。

## ② 各项目做法（证据）

### DeepCode-main（分层与领域建模最完整）
- **Protocol 端口**：`core/application/execution_handler_registry.py:17`（`ExecutionHandler(Protocol)`）、`core/skills/provider.py:124`（`@runtime_checkable class SkillProvider(Protocol)`）、`core/application/goal_turn_port.py:31`（`GoalTurnPort`）、`core/application/execution_admission.py:24`、`core/harness/agents/external_backend.py:69`（`ExternalCli`）。
- **ABC stub**：`core/providers/base.py:152`（`class LLMProvider(ABC)`）、`workflows/interactions/base.py:79`、`core/harness/tools/diagnostics.py:45`（`raise NotImplementedError`）。
- **Event 信封 + 不变式**：`core/domain/event.py:19-44`——`@dataclass(frozen=True, slots=True) DomainEvent`，`__post_init__` 强制 `sequence>=1`、`evt_`/`turn_`/`item_` 前缀、"item 事件必带 turn"、`require_aware(timestamp)`、`payload` 必须是 JSON 对象。
- **交叉不变式**：`core/domain/turn.py:47-139`——`TurnStatus(StrEnum)` 带 `is_terminal`；`Turn.__post_init__` 编 "terminal⇒completed_at 必存"、"非 terminal⇒禁 completed_at"、"failed⇒error_code 必存"、"仅 failed 可带 error"、"epoch 非负"、"skill_ids 去重" 等。
- **领域原语**：`core/domain/common.py`——`new_id(prefix)`（ASCII-alnum 校验）、`require_prefixed_id/require_aware/require_non_empty/validate_json_object(json.dumps allow_nan=False)`。
- **序列化纪律**：`core/persistence/serde.py:10-45`——`dump_json(allow_nan=False)`、datetime 存 UTC `Z`、`load_json` 拒非 object。
- **wire 单一真源**：repo 根 `protocol/app-server.schema.json`（draft 2020-12 JSON-Schema，8312 行）、`schema/mcp-agent.config.schema.json`。

### wuu-main（Kernel↔Policy 契约形状）
- `internal/loopdriver/contract.go:14-76`——`LoopPolicy{ModelRoundLimit,DisableTools,DisableCompaction}` + `KernelGateway.ExecuteModelLoop(input,LoopPolicy)→Receipt` + `Driver{Create,Resume}` + `Instance{Run,Checkpoint,Cancel(reason),Shutdown}` + `Descriptor.Capabilities`。→ 我们 `contracts/policy.py` 的 `LoopPolicy` + `PolicyPort.propose_action` 形状据此具体化（承 R01 G-6）。

### crewAI / CowAgent（旁证）
- crewAI `llm.py:854-900`/`1584-1650`：LiteLLM 流式装配（`include_usage` 末块空 choices 需增量记 finish_reason）——P0 只锁 `ProviderPort.stream` 签名，实现留 P1（印证端口应薄）。

## ③ 对 P0 骨架的具体取用（已落码）

| P0 落点 | 抄自 | 处置 |
|---|---|---|
| `contracts/common.py`（`new_id/require_aware/validate_json_object`） | DeepCode `domain/common.py` | 改造复用（docstring 标 provenance） |
| `contracts/events.py` Envelope + `EventType` 枚举 | DeepCode `domain/event.py` + `events/protocol.py` | 改造，补 `v/run_id` 版本字段 + 关联键常量 + 内外分层 |
| `state/domain_state.py` `Run.__post_init__` 终态一致 | DeepCode `domain/turn.py` | 改造 pattern（terminal↔completed_at、failed↔error_stack、cancel↔reason） |
| Port = `Protocol` / stub = `ABC+NotImplementedError` | DeepCode 双范式 + wuu loopdriver | 采用；`ProviderPort/StorePort/SandboxPort` 用 Protocol，`TurnLoop/EventBus/PermissionEngine/Tool/ToolRegistry` 用 ABC |
| `protocol/event.schema.json` + `check_protocol_schema.py --check` | DeepCode `protocol/*.schema.json` | 自写真源 + 漂移守卫（schema↔EventType 锁步） |
| 三防线（包边界+ruff `banned-api`+`check_layering_ast.py`） | 全参考集零采用 | **自写**（含抓动态 import + fail-on-empty + self-test） |

## ④ 坑（参考实现踩过的，P0 已防）

- **P-1 浅冻结假不可变**：pydantic/dataclass `frozen=True` 只挡顶层 setattr，内层 list/dict 仍可改。DeepCode 一律 `tuple` 字段规避。→ 我们 contracts/state 集合字段全用 `tuple/frozenset`；`DomainState.defaults` 由 `dict` 改 `SessionDefaults`。
- **P-2 provider 长进策略**：DeepCode `providers/base.py` 把重试/退避 token 塞进 provider 基类（`:159-210`）——与 C1"策略/能力层禁 import provider"有张力。→ 遵 **ADR-0010**：分类=纯函数进 contracts（`errors.py`），重试/fallback 编排归 Kernel；provider 基类不长出策略。
- **P-3 配置文件 locale 编码**：import-linter 用 OS 默认编码读 `.importlinter`，Windows/zh 下中文注释触发 `gbk` 解码崩溃（实测）。→ `.importlinter` 保纯 ASCII。
- **P-4 契约类型名混淆**：`independence` 是契约 `type`、`independent_packages` 是字段——写成 `type=independent_packages` 会被当未知类型直接报错退出（实测）。

## ⑤ 缺口 / 后置

- **无一处提供 `after_seq`+`id:<seq>` 精确 SSE 重放**：DeepCode 走 WS/JSON-RPC、CowAgent 走 OpenAI-compat SSE（无 per-event id）→ P1 须自写续传（见 R02/R08 与 plan/01 T9/T10）。
- **realpath/symlink 敏感路径解析**：DeepCode `permissions.py` 用 `normpath`（非 `realpath+evalsymlink`）→ P1 T6 权限引擎须补齐（03 §11）。
- **codegen TS 类型**：DeepCode 的 schema 由外部消费，本仓 P0 仅立真源 + Python 侧 `--check`；真 TS codegen 归 P7。
- **import-linter 拦不住动态 import**：故 AST 检查器为一等防线之一，非可选。

> 行号为扫描快照，作定位用、非契约。本报告只读取参考实现、不复制其代码，落地均为按本项目契约重写的形状。
