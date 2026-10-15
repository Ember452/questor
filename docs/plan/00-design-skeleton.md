# Questor 计划 0（P0）· 设计与可编译接口骨架 · 开发计划

> 用途：P0 的**详细开工计划**（ROADMAP §0/§3 约定「每 Phase 开工前另写一份 `docs/plan/NN-<phase>.md`」）。
> 母文档 [`VISION.md`](../VISION.md)；阶段口径 [`ROADMAP.md`](../ROADMAP.md) §0/§1/§1.5；契约 [`design/00`](../design/00-layering.md)–[`06`](../design/06-memory.md) + [`HARD-CONSTRAINTS`](../design/HARD-CONSTRAINTS.md)；结构 [`STRUCTURE.md`](../STRUCTURE.md)；决策 [`adr/0001`](../adr/0001-from-scratch-not-port.md)–[`0011`](../adr/0011-seq-semantics.md)。
> **姊妹文档**：[`plan/01-p1-minimal-loop.md`](./01-p1-minimal-loop.md) —— P0 产「空而有形状的骨架 + 守卫 + 契约真源」，P1 在其上「填肉跑出行为」。二者交接见本文 §9。

---

## 0. 定位与原则

P0 在 ROADMAP 里是**两半**：

1. **设计文档半**（`docs/design/*` + `HARD-CONSTRAINTS` + `ADR 0001–0011`）——**已完成**，本文 §1 做一次「是否达可开发门槛」的审计。
2. **可编译接口骨架半**（stub 全绿、import-linter/边界通过）——**从未落码**（仓库现无 `src/`、`pyproject.toml` 近乎空）→ **这才是本计划要做的实体工作**。

**DoD**（ROADMAP §1 P0 行 + §1.5 备注）：能照文档搭出**可编译的接口骨架**——
- stub **全绿**：所有子包冷导入通过、类型/签名可实例化；
- **边界通过**：分层依赖靠机器守（import-linter/ruff/AST，见 §2 verdict：参考集零采用，我们自写）；
- **不能跑 Agent 任务**（无业务逻辑）；可跑从 P1 起。

**核心原则**：stub = **接口 / 类型 / 签名 / 不变式的「形状」**，不含算法、副作用、I/O。分层靠**机制**守而非口头（HARD C1/C14/C15）。接缝（run/seq/Command-Event 总线/权限三态/工具账本骨架/Port 协议）**在 P0 锁形**；具体字段留 `draft`（C11 防过早焊死）。

---

## 1. 现状审计：设计文档半是否达 ROADMAP §0「可开发」门槛

ROADMAP §0 三条件：

| 条件 | 现状 | 判定 |
|---|---|---|
| ① 五接缝有纸面契约（00 分层 / 01 状态 draft / 02 事件 / 03 工具 / 04 循环）；05/06 为纵深非门槛 | 全部存在，且经 R01–R09 实扒加固 | ✅ |
| ② 工程红线（HARD C1–C15）+ ADR 0001–0011 定稿可自检 | 存在 | ✅ |
| ③ ROADMAP 存在 + **P1 有一份详细计划** | ROADMAP ✅；`plan/01` 本次已产 | ✅ |
| ④（本计划补）P0 有详细计划 | 本文件 | ✅ |

**遗留（属正常、非阻塞）**：`01-state-model` 是 **working draft**（字段未锁）——正合 C11「接缝早锁、字段 v0 后锁」，**P0 骨架只锁接缝类型名与关联键、字段留 `Optional/draft`**，不在此刻钉死。`05-policy`/`06-memory` 是纵深文档，非第六接缝，不进 P0 骨架门槛。

**结论**：设计半达标，可进入接口骨架落码。

---

## 2. 参考扫描与复用（AGENTS §4.5 必做，逐条 `file:line` + verdict）

**扫描集**（`Get-ChildItem project-main` 当下为准，12 仓）：hermes-agent / wuu / DeepCode / CowAgent / MetaGPT / cordis / EvoFlow / autogen / crewAI / OpenManus / GenericAgent / Agent-S。P0（骨架/契约/边界）相关取证：

| P0 关注点 | 取证 `file:line` | verdict |
|---|---|---|
| **分层如何被工具强制** | **全 12 仓 grep `import-linter`/`.importlinter`/`banned-api`/`TID251` = 0 命中**；连最讲分层的 DeepCode `pyproject.toml:19-29` 也只配 `line-length/target-version/ignore E402`，**无边界规则** | **自写**：以**包/模块边界为主** + ruff `flake8-tidy-imports.banned-api`(TID251) 点名禁跨层 + 自研 AST 检查器；import-linter 仅作**声明式意图**兜底（正面验证 R09/记忆结论） |
| **Port 接口定义范式** | DeepCode 广泛 `typing.Protocol`：`application/execution_handler_registry.py:17`、`skills/provider.py:124`(`@runtime_checkable`)、`application/goal_turn_port.py:31`、`application/execution_admission.py:24`、`harness/agents/external_backend.py:69`；`ABC`+`NotImplementedError`：`providers/base.py:152`(`LLMProvider`)、`workflows/interactions/base.py:79`、`harness/tools/diagnostics.py:45` | **改造复用**：**被注入端口用 `Protocol`**（结构化、可 `@runtime_checkable`）、**需实例化的 stub 基类用 `ABC`+`NotImplementedError`** → `contracts/ports.py`、`providers/`、`capabilities/` |
| **Event 信封 + 不变式** | DeepCode `core/domain/event.py:19-44`：`@dataclass(frozen=True, slots=True)` + `__post_init__` 强制 `sequence≥1`、`evt_` 前缀、`item` 必带 `turn`、`tz-aware`、`payload` 是 JSON 对象；`events/protocol.py` EventMsg frozen union | **改造复用** → `contracts/events.py` 信封模板（补我们 `v`(版本) + `run_id` + 关联键常量；内部/外部两层留 P1 投影） |
| **状态模型交叉不变式** | DeepCode `core/domain/turn.py:47-139`：`TurnStatus(StrEnum)` 带 `is_terminal`、`Turn` frozen+slots、`__post_init__` 编 **terminal↔completed_at、非 terminal 禁 completed_at、failed↔error_code、仅 failed 可带 error** 等交叉不变式 | **改造复用 pattern** → `state/` Run/status 与终态一致（呼应 C13 终态唯一 / 02 §3 终止序 / 01 §2 配对不变式） |
| **领域共享原语** | DeepCode `core/domain/common.py`：`new_id(prefix)`(ASCII-alnum 校验)、`require_prefixed_id/require_aware/require_non_empty/validate_json_object(allow_nan=False)`、`enum_value` | **改造复用** → `contracts/` 共享不变式原语（ids、tz-aware、JSON 约束） |
| **序列化纪律** | DeepCode `core/persistence/serde.py:10-45`：`dump_json` `allow_nan=False`、datetime UTC `Z`、`load_json` 拒非 object | **改造复用**（P0 只在 contracts 定 **JSON/时间约束**；store 落地在 P1 T9） |
| **跨语言 wire 单一真源（C15）** | DeepCode repo 根 `protocol/app-server.schema.json`(8312 行 JSON-Schema) + `schema/mcp-agent.config.schema.json`(820) | **shape参考** → P0 起 `protocol/event.schema.json` 作**外部事件投影唯一真源**，构建期 codegen + CI `--check` 防漂移 |

**纪律**：守分层（复用形状不 import 他仓实现）、尊重 license+署名、真移植处标 provenance（AGENTS §4.5）。

---

## 3. P0 交付物 = 可编译接口骨架（范围）

### 3.1 进 P0（产「形状」，不产「行为」）
- **八层包骨架**（`src/questor/{contracts,state,kernel,capabilities,policy,providers,surfaces,config,observability}` + `__main__.py`），每包 `__init__` 不导出实现类（C1 边界）。
- **L0 契约全签名**（`contracts/`）：Command/Event union + 信封 + 关联键常量、Domain_State schema 接缝类型（字段 `Optional/draft`）、PolicyView/PolicyIntent/PolicyPort、ToolSpec + Tool/ToolResult、各 Port(`ProviderPort/StorePort/Clock/Id/SandboxPort`) 抽象。
- **L1 数据模型 stub**（`state/`）：frozen+不可变集合、`__post_init__` 接缝级不变式（**不含 reduce 语义**）。
- **各层 stub 基类**（`kernel/capabilities/policy/providers/surfaces`）：`ABC`/`Protocol` + `raise NotImplementedError`；无循环、无 provider 调用、无存储写、无网络。
- **`capabilities/{skills,mcp,subagent}` 空目录 + README**（S2「预留 stub、早期不塞码」）。
- **`protocol/event.schema.json`** 外部事件投影单一真源 + codegen/`--check` 钩子。
- **三道分层防线**（HARD C15）：`.importlinter`（声明意图）+ ruff `banned-api`（点名禁跨层 + `ban-relative-imports=all`）+ 自研 AST 检查器（禁 contracts 出现实现、禁 reduce 原地 mutate 占位）；每条带 `--self-test` + **fail-on-empty**。
- **`pyproject.toml` 依赖钉版**（uv，Python 3.13）：`pydantic>=2`、`immutables`、`jsonschema`、`import-linter`、`ruff`、`pytest`；**Provider 侧 `litellm` 与 `fastapi`/`aiosqlite` 到 P1 再加**（P0 只锁 Port，不绑实现）。
- **CI 骨架**：冷导入 job（不依赖 change-classifier 的独立 blocking）、边界守卫 job、外部契约快照 diff（`contracts_changed` 触发）。

### 3.2 **明确不做**（属 P1 及后，越过即破里程碑）
- 任何 `reduce` 业务语义 / turn 循环 / ProviderPort→LiteLLM 调用 / StorePort 读写实现 / HTTP+SSE 服务 / CLI 交互 / 权限求值算法 / 沙箱执行 / 记忆。
- P0 只保证「**照着能编译、能实例化 stub、能证明边界守得住**」。

---

## 4. 实现步骤（P0-T1 → P0-T6，依赖有序）

### P0-T1 工程与守卫 bootstrap（无依赖）
建八层包目录 + 空 `__init__`（不导出实现）+ `pyproject` 钉版 + `.importlinter` + ruff `banned-api` + 自研 AST 检查器脚手架 + 冷导入/CI 脚本骨架。
→ verify：`uv run python -c "import questor.<每子包>"` 全绿；`lint-imports` 绿；`ruff check` 绿；AST 检查器 self-test 能判红（造一个越界 import）判绿；故意扫空目录 fail-on-empty 生效。

### P0-T2 L0 契约签名（`contracts/`，依赖 T1）
- `ports.py`：ProviderPort/StorePort/Clock/Id/SandboxPort(`fences_writes/fences_network/isolates_process_tree` 探针签名)。
- `events.py`：Command union + 内部/外部 Event 类型名 + 信封 `Envelope{v,seq,run_id,turn?,ts,type,data}` + 关联键常量(`run_id/turn/tool_call_id/card_id/item_id` **定死**)；占位 `parallel_safe`/`kind=subagent`/多模态 type（`draft`）。
- `policy.py`：PolicyView/PolicyIntent(ProposeToolCall|ProposePlanUpdate|AdviseCompact|SuggestFinish|SuggestCancel)/PolicyPort(`id/fingerprint/propose_action` + 可选钩子)。
- `tool.py`：ToolSpec(capability/risk/parallel_safe 占位/available/read_only/approval_mode) + Tool/ToolResult。
- `common.py`：`new_id/require_aware/require_non_empty/validate_json_object`（改造复用 DeepCode domain/common）。
→ verify：contracts **无任何 import provider/state/kernel/policy/surfaces**（AST + import-linter）；纯数据可序列化、无实现体。

### P0-T3 L1 数据模型 stub（`state/`，依赖 T2）
Domain_State/Run/context/task_tree/tool_ledger/checkpoints/permission_ctx/error_stack 的 frozen schema（`tuple/frozenset`/immutables）+ `__post_init__` 接缝级不变式（seq≥1、id 前缀、Run.status ∈ {idle,running,awaiting_approval,cancelled,failed,completed}）。**字段留 `Optional/draft`**（C11）。
→ verify：非法值（seq=0、孤儿 item 无 turn、naive datetime）在构造期抛错；实例 `model_copy`/深拷后旧对象不变（真不可变）。**不含 reduce**。

### P0-T4 各层 stub 基类（`kernel/capabilities/policy/providers/surfaces`，依赖 T2/T3）
- `kernel/`：`Loop`/`EventBus`/`PermissionEngine`/`Sandbox` 抽象签名（`ABC` 或 `Protocol`），方法 `raise NotImplementedError`。
- `capabilities/`：`ToolRegistry` 抽象 + `tools/read.py` 仅签名（execute 抛 NotImplemented）；`skills/mcp/subagent` 空目录 + README。
- `policy/`：`PolicyPort` 实现占位类（`propose_action` 抛 NotImplemented）。
- `providers/`：`LiteLLMProvider(ProviderPort)`/`SQLiteStore(StorePort)` 类签名（无网络/无 IO）。
- `surfaces/`：`CliSurface`/`HttpSseSurface` 抽象（`run/cancel/resume` 签名）。
- **铁律**：内核 stub **只依赖 contracts + 注入的 Port**，**禁直接 import policy/surfaces 具体实现**（S3/C14）。
→ verify：import-linter 契约「kernel 不 import policy/surfaces 实现」通过；越界 import self-test 变红。

### P0-T5 wire 契约单一真源（`protocol/event.schema.json`，依赖 T2）
外部事件投影的 JSON-Schema（从 `contracts/events.py` 外部集对齐生/校）；构建期 codegen 生 TS 类型的**钩子占位**（真 TS 到 P7）；CI `--check` 防漂移。
→ verify：schema 与 contracts 外部 EventMsg 一致（`--check` 不漂移）；schema 自身可被 `jsonschema` 校验。

### P0-T6 CI 与 DoD 校验脚本（依赖 T1–T5）
CI：`cold-import` / `layering-guards`（import-linter + ruff + AST，独立 blocking）/ `contract-snapshot`（外部契约 diff）。本地 `scripts/` 提供等价一键校验入口。
→ verify：五 DoD（§5）全绿；CI 在故意破坏分层/契约时报红。

---

## 5. P0 DoD 验收清单（可手工复现，AGENTS §5）

1. **冷导入**：`uv run python -c "import questor"` 及每子包，全绿（AGENTS §5 质量门）。
2. **边界守卫**：import-linter + ruff `banned-api` + 自研 AST 检查器全绿；且**故意越界 import → 变红**（self-test 证明能判红，非假绿）。
3. **可实例化**：contracts/state 数据模型能构造；不变式（`__post_init__`）对非法值（seq≤0、孤儿 item、naive 时间、非 JSON payload）抛错。
4. **纯接口无实现**：所有 Port 为 `Protocol`/`ABC`、方法 `raise NotImplementedError`；**无任何业务/算法/I-O**。
5. **契约单一真源**：`protocol/event.schema.json` 与 `contracts/events.py` 外部集由 CI `--check` 保持一致。
6. **不能跑 Agent 任务**：确认 P0 无循环/无 provider 调用（这是 P0 的**正确**状态，非缺陷）。
7. **不违红线**：C1/C2/C11/C14/C15 与 STRUCTURE S1–S7 全守。

> 达成即 **发布里程碑节点 A**（ROADMAP §4）：可先开源架构文档（design/adr/roadmap/plan），无运行码。

---

## 6. 红线对照（P0 重点）

| 红线 | P0 落点 | 强制 |
|---|---|---|
| C1 分层方向 | 包边界 + 内核只依赖 contracts+Port | import-linter/ruff/AST（自写，参考集零采用） |
| C2 单写者/不可变**形状** | Domain_State frozen+不可变集合（语义在 P1） | 类型 + `__post_init__`；mutate 检查器占位 |
| C11 谨慎演进 | **只锁接缝类型名/关联键、字段留 draft** | Optional + 版本号 + 接缝改动走评审 |
| C13 存内事件（形状） | `Envelope` 带 `seq`、event 类型名定 | contracts 快照 |
| C14 结构边界机器守 | kernel 不 import policy/surfaces 实现 | import-linter 契约 + blocking job |
| C15 单一真源+守卫可信 | `protocol/*.schema.json` + codegen `--check`；守卫带 `--self-test`+fail-on-empty | CI |
| S1–S7 结构补充 | providers 命名/README、skills-mcp-subagent 空 stub、contracts 只放抽象 | 目录 + AST（contracts 无实现） |

---

## 7. 风险与缓解

- **R-P0-A｜stub 膨胀成真实现**：为「顺手」在 contracts/骨架塞逻辑 → 违 S4/C11、把最稳定层做胖。→ 自研 AST 检查器**禁 contracts 出现实现/IO**、CI blocking；评审把关「P0 只做形状」。
- **R-P0-B｜分层守卫假绿**：import-linter 拦不住动态 import（且参考集零采用）、守卫扫不到文件却报过。→ **包边界为主** + ruff 点名禁 + AST 兜底；每条 `--self-test` 判红判绿 + **fail-on-empty**；作独立 blocking job（C15）。
- **R-P0-C｜过早锁字段**：P0 就把 task_tree/断点/recovery pointer 字段钉死 → 后期大范围迁移（01 working-draft 警告）。→ **只锁接缝类型与关联键**，字段 `Optional/draft`，schema 带版本。
- **R-P0-D｜wire schema 与 pydantic 漂移**：三端各写各的。→ **单一真源** `protocol/event.schema.json` + CI `--check`（codegen 钩子在 P7 真接 TS）。
- **R-P0-E｜与 P1 边界含糊**：骨架与实现双写或互相漏。→ §9 显式交接 + P1 文档去重重指。

---

## 8. 被否方案与取舍

- **❌ P0 就写业务让骨架「顺手能跑」**：越 ROADMAP §1.5「只产接口桩、不能跑」，破坏节点 A/B 里程碑分离，未经 P1 §2.5 验证即实现 → 返工面最大。
- **❌ 只用 import-linter 当唯一防线**：本参考集 12 仓**零采用**、且拦不住动态/运行时 import（R09 实扒 + C15）。→ 包边界为主、ruff+AST 为辅、import-linter 仅声明意图。
- **❌ 无 wire schema 真源、直接手写三端类型**：C6「只增不改」会 Python/Rust/TS 三处悄悄分叉。→ 早定 `protocol/*.schema.json`。
- **❌ P0 与 P1 物理合并成一份文档**：违 ROADMAP §0「每 Phase 另写一份」+ 抹掉两阶段**各自可验证 DoD**（AGENTS §4 goal-driven）+ 混了发布节点 A/B。→ **采「独立 P0 文档 + 与 P1 显式交接」**（若你坚持要合成单文件，我可再折，但会失上述好处）。

---

## 9. 与 P1 的交接（handoff）

| 关切 | P0 产 | P1 消费/填 |
|---|---|---|
| 八层包骨架 + 冷导入 | **建 + 守** | 直接复用 |
| 分层三防线 + CI | **建 + self-test 绿** | 复用、加实现层测试 |
| `contracts/` 全签名（Port/Event/State-schema/PolicyPort/ToolSpec） | **锁接缝形状** | 按实现**微调字段**（仍只增不改，C11） |
| `state/` Domain_State 模型 | frozen + 不变式（**无 reduce**） | **写 reduce + 真不可变语义 + COW**（P1 T3） |
| `kernel/loop` | 抽象签名 + `NotImplementedError` | **填 phase pipeline + 终止/取消/护栏**（P1 T7） |
| `providers/litellm`,`store_sqlite` | Port 类签名 | **实现流式装配 + event_log/after_seq**（P1 T4/T9） |
| `capabilities/tools/read` | execute 签名 | **实装读逻辑 + ctx 受控能力**（P1 T5） |
| `kernel/permissions` | 三态/Mode 类型 stub | **实装八步求值 + denylist realpath**（P1 T6） |
| `surfaces/cli`,`http_sse` | 抽象签名 | **实装流式打印 + SSE+after_seq**（P1 T10） |
| `protocol/event.schema.json` | 外部投影真源 | 复用（P7 才 codegen TS） |

**去重重指**：[`plan/01`](./01-p1-minimal-loop.md) 的 §3「工程骨架 bootstrap」与 T1/T2 由「P1 从零创建」改判为「**消费 P0 产物、填实现**」；P1 若发现 P0 契约签名不合用，走 **只增不改**（C6/C11）回改 `contracts/`。

## 10. 执行顺序与提交粒度

**依赖链**：P0-T1 → T2 → {T3, T4} → T5 → T6。T3/T4 可在 T2 后并行。P0 收尾 → 触发节点 A（文档开源）→ 进入 [`plan/01`](./01-p1-minimal-loop.md)。

**建议提交粒度**（英文 Conventional Commits，**每次 commit/push 须用户当轮明确许可**，AGENTS §6）：
`chore: bootstrap layered package skeleton + layering guards` → `feat(contracts): command/event/policy/tool/port signatures` → `feat(state): domain-state schemas + seam invariants (stubs)` → `feat(kernel,capabilities,policy,providers,surfaces): interface stubs (NotImplemented)` → `feat(protocol): event JSON-Schema single source + drift check` → `ci: cold-import + boundary + contract-snapshot jobs` → `docs: plan/00 design-skeleton`。
