# P0 交付报告 · 设计与可编译接口骨架

> 目的：让你读完后能一句话讲清"P0 到底做了什么、架构怎么切、为什么这么取舍"。
> 口径：以**仓库当下代码**为准，非设计稿愿景。判据来自 [`docs/plan/00-design-skeleton.md`](../plan/00-design-skeleton.md)、[`docs/ROADMAP.md`](../ROADMAP.md) §1。

---

## 1. 一句话概括

P0 交付了一副**"空而有形状"的骨架**：八层包结构全部建好、所有跨层接口（契约）签名锁死、三道分层守卫把边界变成机器可检查的红线、事件协议有单一真源——但**不含任何业务逻辑，跑不了 Agent 任务**（这是 P0 的正确状态，不是缺陷）。

**可验证判据（DoD）**：能照这套骨架编译、实例化每个 stub、并证明分层边界守得住。→ **全部达成**。

---

## 2. 交付物清单

| 交付物 | 位置 | 说明 |
|---|---|---|
| 八层包骨架 | `src/questor/{contracts,state,kernel,capabilities,policy,providers,surfaces,config,observability}` | 每层一个包，`__init__` 不向外导出实现类（守边界） |
| L0 契约全签名 | `contracts/`：`events` `state_schema` `policy` `tool` `ports` `common` `errors` | Command/Event 信封与类型、状态 schema、PolicyPort、ToolSpec、各 Port 抽象、共享不变式原语 |
| L1 数据模型 stub | `state/domain_state.py` | `Run`/`Context`/`TaskTree`/`ToolLedger`/`PermissionCtx` 等 frozen dataclass + 构造期不变式（**无 reduce**） |
| 各层 stub 基类 | `kernel` `capabilities` `policy` `providers` `surfaces` | `ABC`/`Protocol` + `raise NotImplementedError`，只锁签名 |
| 预留空能力目录 | `capabilities/{skills,mcp,subagent}/README.md` | 占位不塞码（对齐后期 P5/P8） |
| 事件协议单一真源 | `protocol/event.schema.json` + `scripts/check_protocol_schema.py` | 外部事件投影的唯一 JSON-Schema，CI `--check` 防与代码漂移 |
| 三道分层守卫 | `.importlinter` + `ruff banned-api` + `scripts/check_layering_ast.py` | 见 §4；每条带 `--self-test` + fail-on-empty |
| 工程与 CI | `pyproject.toml`（uv、Py3.13 钉版）+ `.github/workflows` + `scripts/verify_p0.py` | 冷导入 / 边界 / 契约快照一键校验 |

**实测复核**：36/36 模块冷导入通过；`lint-imports` 4 契约全 KEPT；AST 守卫扫描 0 违规且能判红；`protocol --check` 显示 17 类事件与 `EventType` 锁步。

---

## 3. 架构全景（P0 定形的部分）

八层，**依赖只能由外向内**，内层永远不知道外层存在：

```
L7 Shell/UI       Tauri/Web（占位，P7 才接）        ← 只消费事件协议
L6 Surfaces       CLI · HTTP+SSE 服务端              ← 只收 Command + 投事件，零业务
L5 Ports+适配器   ProviderPort→LiteLLM · StorePort→SQLite · Clock · Id · Sandbox
L4 Policy         ReAct/规划/记忆策略（可插拔）      ← 只读状态快照 → 返回意图
L3 Capabilities   工具注册表 · Skills · MCP · 子agent
L2 Kernel/Harness turn 循环 · 工具路由 · 权限 · 事件总线  ← pure mechanism，不碰模型/UI
L1 State          Domain_State（纯数据 + 不变式 + reduce）
L0 Contracts      跨层共享"词表"：状态schema·事件类型·ToolSpec·各Port   ← 最稳定
──────── 横向：Config · Observability（只依赖 L0、只读、不改状态）
```

P0 把**每一层的"接缝"**（谁调谁、传什么类型、关联键是谁）钉死，字段留 `Optional/draft`。核心接缝：

- **单写者**：只有 `reduce(state, command)` 能改状态（P1 实现）。
- **Command/Event 两条通道**：写意图 = Command；状态转移广播 = Event；瞬态流式 delta 不落状态。
- **权限三态一等**：`allow/ask/deny` 是状态里的正式字段，不是散落的 if。
- **Port 注入**：内核只认抽象端口，模型/存储/沙箱全部从外面插进来。

---

## 4. 关键决策与取舍

| 决策 | 选择 | 为什么 / 放弃了什么 |
|---|---|---|
| **从零自研 vs 移植** | 从零自研（ADR-0001） | 放弃移植 CowAgent/DeepCode。它们的投影、不可变、权限模型与我们契约不同构，改它们的返工更贵。只"取最硬的设计当参照、代码自己写"。 |
| **分层怎么强制** | **三道防线**：`.importlinter`（声明意图）+ ruff `banned-api`（点名禁跨层）+ 自研 AST 检查器 | 关键取证：**扫遍 12 个参考仓，`import-linter` 零采用**，且它拦不住动态 import。所以不能只靠一个工具——包边界为主、lint 点名禁、AST 兜底。放弃"只用 import-linter"。 |
| **守卫可信性** | 每条守卫带 `--self-test` + **fail-on-empty** | 防止"扫不到文件却报通过"的假绿。故意造一个越界 import 必须判红，才算守卫有效。 |
| **契约演进** | 只锁**接缝类型名 + 关联键**，字段留 `draft` | C11 防过早焊死。参考仓的教训：状态模型一旦全字段钉死，后期大改代价极高。 |
| **事件协议** | 早定 `protocol/*.schema.json` 单一真源 | 防 Python/Rust/TS 三端各写各的分叉（C15）。TS codegen 钩子先占位，P7 才真接。 |
| **P0 是否顺手写业务** | **坚决不** | 越过 ROADMAP §1.5"只产接口桩"会破坏发布里程碑节点 A/B 的分离，未经 P1 验证即实现 → 返工面最大。 |

---

## 5. 实现相对纸面计划的偏差（reality wins）

P0 收尾时记录的实际做法与 `plan/00` 原计划的差异（均为合理微调）：

- **contracts 多两个文件**：增补 `state_schema.py`（值对象/枚举）与 `errors.py`（错误分类）。原因：`policy`(L4) 和 `state`(L1) 都要引用这些词汇，而 contracts 是最内层不能被外层依赖——放这里才不破分层。属 additive。
- **`.importlinter` 必须纯 ASCII**：import-linter 用 OS 默认编码读配置，Windows/中文 locale 下中文注释触发 `gbk` 解码崩溃 → 配置改纯英文。
- **契约类型名坑**：横切独立性要写 `type = independence`（字段 `modules`），误写成 `independent_packages` 会被当未知类型直接报错。
- **依赖分期**：P0 运行依赖只 `pydantic`/`immutables`/`jsonschema`；`litellm`/`fastapi`/`aiosqlite` 按计划推到 P1 再加（P0 只锁 Port 不绑实现）。`immutables` 此时只是"声明了还没用上"——**直到 P1 才真正用它做深冻结**。

---

## 6. 诚实边界（P0 有意不做的）

- **不能跑 Agent 任务**——无循环、无 provider 调用、无存储读写、无权限求值。这是 P0 的正确状态。
- **无真不可变语义**——`state/` 只有 frozen dataclass 形状，跨态 COW/深冻结语义留 P1 的 `reduce`。
- **无跨语言 TS 类型**——schema 真源已立，codegen 到 P7。
- 所有 `NotImplementedError` 是**诚实标注的 stub**，不是隐藏的技术债。

---

## 7. 它带来了什么 / 下一步

**价值**：P0 把"返工代价最高"的东西——分层纪律、接缝形状、机器守卫——一次性立到位。此后 P1–P10 无论怎么加功能，都被这三道防线约束着**不塌回一坨**。这也正好触发**发布里程碑节点 A**：可先只开源这套架构文档（design/adr/roadmap/plan + 骨架），面向硬核开发者。

**下一步 = P1**：在这副骨架上"填肉跑出行为"——写 `reduce`、接 ProviderPort 流式、实装 `read` 工具与权限引擎、把 turn 循环驱动起来。交接契约见 [`plan/00`](../plan/00-design-skeleton.md) §9。→ 读 [P1 交付报告](./P1-completion-report.md)。
