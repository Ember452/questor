# Questor 工程约束与不变式（红线清单）

> 架构会不会腐化，取决于这些约束**是否被机器强制**，而不是靠自觉。每条给：**约束 → 为什么 → 怎么机械强制（lint / 类型 / reducer / CI）**。
> 编码期任何"图省事的跨层直调"都算破窗，PR 不予通过。承接 [`00-layering.md`](./00-layering.md)、[`01-state-model.md`](./01-state-model.md)。

**总原则**：接缝早定全、机制按里程碑长；红线靠机器守，不靠人自律。

---

## C1 分层依赖方向（禁跨层直调）
- **约束**：策略层(L4)/能力层(L3) **禁止 import** provider(L5)、store 实现、sandbox、UI；依赖永远"外层→内层"。
- **为什么**：否则换模型/换存储会牵动上层，"变更域隔离"名存实亡。
- **强制**：`import-linter` / ruff 自定义规则，按包声明"allowed layers"，CI 挡住越界 import。
- **局限（评审补）**：静态 lint 是**第一道防线，不能 100% 拦截**动态/运行时 import。真正的防御是**包/模块边界设计**：底层实现类不得从上层 `__init__.py` 导出；lint 只兜底，边界才是主防线。

## C2 单写者 + 不可变视图
- **约束**：只有 Kernel 经 `Command → reduce` 改状态；策略/工具/UI **只提交意图**，拿到的状态是**只读视图**，不是可变引用。
- **为什么**：策略意外改状态 = 污染可信状态 = 断点/回放当场作废，且是最难查的 bug。
- **强制**：**copy-on-write / 持久化数据结构 / 只读投影**，**不要浅 `@dataclass(frozen)` 假装安全**（内层 list/dict 仍可改）。视图按字段暴露（策略只看得到上下文/工具结果/记忆片段，看不到断点/权限/内部元数据），**不做每轮全量深拷贝**。
- **结构共享的根因（评审补）**：共享意味着底层容器是**同一实例**，若 reduce 原地改共享子对象，视图会看到中途变更 → **禁止原地 mutate 内部集合；reduce 永远返回新 State、旧实例不变**。Python：pydantic-v2 frozen **本身仍是浅冻结**（只挡 setattr），**必须配不可变集合**（`tuple/frozenset`/immutables）才算真不可变；Rust 天然所有权。
- **不可变作域限定（评审 R01-G8）**：**C2 的不可变红线只强加于 `Domain_State`**（权威、可持久、可回放）；`LoopState`（per-turn 循环临时态）**允许内部可变槽位**，以"每 phase 返回 verdict + 按名拷回"解耦即可，否则字段一多即不可维护。机器强制（COW/禁原地 mutate）也只针对 `Domain_State`。

## C3 视图 vs 快照
- **约束**：正常 turn 走**只读视图**（按需暴露、结构共享）；**全量快照**只在**回放 / 分支试验**时生成并持久化。
- **为什么**：每轮深克隆大状态 → 任务树深/日志长时拷贝开销爆炸。

## C4 Store 读写都过接口
- **约束**：**写**（记忆/状态/断点）**必须** `Command → Harness 校验 → StorePort`，绝无旁路；**读**（含向量检索）经 **Harness 持有的 `StorePort` 接口**返回授权结果，**不给策略裸句柄**。
- **为什么**：策略直连向量库→记忆逻辑耦合进存储、换库/加审计全崩，且破"只读"约束。热路径读走接口即可，不必排"写命令"那条重路径。
- **强制**：只暴露 `StorePort`；向量库实现不出该模块边界。

## C5 Command（输入事件）/ Event（输出事件）
- **约束**：同一条**带类型的总线**上，两类分开：`Command`=写意图（决策/取消/发起工具/写记忆），`Event`=状态转移/流式的对外广播。
- **为什么**：统一通信又保留"写意图 vs 观测"语义（幂等、校验、重放各不同）。
- **语义铁律（评审补）**：`Command` 可校验、**可拒绝、非 append-only**；`Event` **append-only、发出不可撤回、是状态变更之后的产物**。❗ **Event 绝不能反向作为修改状态的输入**；改状态只来自 Command，否则破坏单写者模型。

## C6 事件内外分层 + 版本
- **约束**：**内部事件**细粒度、Harness 私有、可演进；经**投影层**映射成**外部事件集**才给 Shell/第三方。外部契约带 `v`、**只增不改**、**未知 type 静默忽略**；破坏性变更才 bump + 兼容转换。
- **为什么**：内部重构不外泄、不炸旧客户端；否则迭代几版后各模块事件结构对不齐。
- **强制**：外部事件 schema 快照测试；CI diff 外部契约，删/改字段=红。
- **例外（评审补）**：“未知 type 静默忽略”**不适用于错误类事件**；未知的 error 类事件至少打告警日志（不能静默吐掉）。
- **例外的延伸（ADR-0027 复审补）**：“静默”不限于丢弃——**折叠、合并、丢行同罪**。观测面的节流窗不得吸收 ERROR/CRITICAL 记录（否则同秒两个 run 各失败一次时，第二个 run 在日志里一行都不剩）；治理管线也不得因自身异常把记录丢掉。见 [`pitfalls.md`](../pitfalls.md) 第 2 条。

## C7 终止权在 Harness（走命令）
- **约束**：策略可*建议*终止，但**全局终止**（超时/资源超限/用户停止/安全告警）由 Harness 决定；且终止经 `Cancel` **Command→reduce**，**不 out-of-band 硬杀**。
- **为什么**：防死循环烧算力；硬杀会撕裂状态、断点作废。
- **reduce 不变式（评审补）**：Cancel 要区分来源（用户/超时/安全告警）；reduce 必须同时：置 `run=cancelled` **且回填所有 pending/running 的 tool_call 为 error**，保证 `tool_use/tool_result` 配对。❌ 禁止“只改 status、不回填 tool_ledger”的不一致破损。

## C8 工具执行边界
- **约束**：策略只输出"调用工具 A + 参数"；**参数校验/权限判定/沙箱/超时全在 Harness**。敏感路径 denylist **不可被 mode/rules 覆盖**。
- **强制**：工具执行器入口统一校验；策略层无任何校验代码（C1 已禁 import 沙箱）。
- **两层校验拆分（评审补）**：Harness 做 ① schema 参数合法性(json-schema) ② 权限/denylist/沙箱判定；**业务参数校验不下沉到沙箱执行器**（沙箱只管执行隔离）。

## C9 权限三态一等 + 沙箱可插拔
- **约束**：`allow/ask/deny` 决策模型是 L1/L2 一等字段；`ask`→`awaiting_approval` 状态 + 一条 HITL 事件。沙箱后端(seatbelt/bubblewrap/受限执行)是**可插拔实现 + 优雅降级**，v1 先轻后补。
- **为什么**：决策/封装在 Harness 侧写死一次，换后端不动上层；后补成本极高。

## C10 插件生命周期 + 故障隔离
- **约束**：策略/能力插件有 **init/load/unload/异常隔离**；插件 panic → **Harness 捕获、回滚到上一致状态、发 error 事件**，绝不带崩进程。
- **强制**：插件调用一律包在熔断/超时护栏里。
- **回滚边界（评审补）**：“上一个一致状态”=最近 Checkpoint；**回滚只回 `Domain_State`，已发出的 Event 不撒回**（append-only 不可删）。Shell/Tauri 要处理“先推了一部分事件、紧接着一个回滚/错误事件”这种现像，不得误解为“回滚=抹掉已推事件”。

## C11 状态模型谨慎演进（防过早焊死）
- **约束**：**接缝早锁、字段 v0 后锁**。跑通端到端 + 验证 **2-3 个不同 Agent 策略**后，才把字段 schema 定为稳定并开持久化迁移。
- **为什么**：早期设计不足→后期为新增字段大范围迁移历史断点/事件，是长期维护最痛的返工。
- **强制**：schema 带版本号 + 迁移脚本纳入 CI；接缝类改动走评审，字段演进类允许 draft。

## C12 远程策略 / 分布式：预留非现在
- **约束**：Agent 策略经 `PolicyPort` 暴露，**默认进程内 + 只读视图**；远程化/多机是**后期能力**，**不为它提前把一切序列化**。
- **为什么**：远程强制"下发视图+鉴权+新鲜度一致性"，v1 用不上却拖累每一处。

---

## C13 存储与终态两条铁律（评审补）
- **只存内部事件**：`events` 表存内部事件；外部事件运行时投影、**不入库不存两份**；回放=重放内部再投影（防两份事件不一致）。
- **终态唯一**：reduce 串行、first-writer-wins，一轮至多一条终态事件；并发终止按优先级择一（可配置）。

## C14 结构性边界靠机器守（评审补 S1–S7）
- **实现不跨层 import**：`kernel` 只依赖 `contracts` + 注入的端口，禁直接 import `policy/surfaces` 具体实现（import-linter 契约强制，非口头）。
- **contracts 只放抽象 + 数据**：Port 协议、状态/事件 schema、ToolSpec；实现留在 providers/capabilities/policy（防最稳定层膨胀，C11）。
- **surfaces/外壳零业务**：HTTP/CLI/OpenAI 兼容只"收 Command + 投事件"；**Python↔Rust 仅 HTTP+SSE 跨进程，禁进程内互调**。
- **observability 只依赖 contracts、只读上报、不改状态**。

## C15 外部契约单一真源 + 守卫可信性（评审 R09/R07）
- **跨语言 wire 契约单一真源**：Python↔Rust↔TS 的事件协议用一个语言中立 `protocol/*.schema.json` 承载，构建期 codegen 生 TS 类型 + CI `--check` 阻断漂移（否则 C6"只增不改"三处各写、悄悄分叉）。
- **分层强制靠三道防线**（import-linter 在本参考集零采用且拦不住动态 import）：① 声明式 `.importlinter`（人读意图）② ruff `flake8-tidy-imports.banned-api` 点名禁跨层 import + `ban-relative-imports=all` ③ 自研 AST 检查器。**以包/模块边界为主、lint 为兜底**。
- **每条机械守卫必须可信**：`--self-test`/fixture 证其能判红判绿 + **fail-on-empty**（扫不到文件≠通过）+ 分层守卫作为**不依赖 change-classifier 的独立 blocking job**（否则会被语言 lane 意外门控掉）。

## C16 Command Inbox 是唯一外部写入口（ADR-0013）
- **约束**：CLI/HTTP/桌面/IM/远程适配器只能向对应 run 的 `CommandInboxPort` 提交带来源和幂等键的 Command；禁止 surfaces 直接调用 `reduce()`、Store 或权限引擎。
- **为什么**：外部写意图与 loop 当前状态并发时会产生第二写者，撕裂 Run、seq 与审批状态。
- **强制**：Kernel `RunController` 串行消费；surfaces import 守卫禁止 import reduce/store implementation；契约测试覆盖重复、终态后提交、队满拒绝。

## C17 PermissionCtx 与 capability floor 优先于 mode（ADR-0014/0015）
- **约束**：`Run.permission_ctx` 是 mode/rules/denylist/approval policy 的唯一真源；权限引擎无自建可变配置。OS 能力下限高于用户 mode，`full_auto` 不得把无写围栏 write 或缺能力 exec 降为 allow。
- **为什么**：mode 是审批偏好，不是 OS 隔离声明；让 mode 覆盖 capability 会把配置便利变成不可逆损害面。
- **强制**：纯函数求值、`SandboxDescriptor` 能力探针、matrix 单测、checkpoint round-trip、无围栏静默执行守卫测试。

## C18 ToolCall 生命周期与输出载荷有界（ADR-0016/0019）
- **约束**：`tool_started` 必须由 pending/ready→running 的 Command 产生；审批必须带 `request_id` 并幂等；工具全文/args/raw 输出进入模型、事件、checkpoint 前必须有大小上限与 artifact 引用。
- **为什么**：没有唯一状态转移，UI 重连与 resume 会猜；没有载荷上限，长跑会把内存、SQLite、prompt 与 SSE 同时拖垮。
- **强制**：ToolCall 状态机、approval request 表、字段级协议 schema、事件 payload 长度断言、artifact 写失败返回有界 error。

## C19 回发前配对关卡 + provider 故障不得崩宿主进程（ADR-0028）
- **约束**：任何一次 `ProviderPort.stream` 请求前，`Domain_State` 的 `context` 必须**完全配对**（每个 `tool_use` 都有对应 `tool_result`）；不可调和时 fail-closed 落 `run_failed`，**不得发出非法历史**。provider 侧异常必须在 kernel 边界经 `contracts` 纯分类器归一 `ErrorEntry`（`layer=provider` + 正确 `retryable`），**绝不允许穿出 turn 循环**；取消/KeyboardInterrupt/SystemExit 等 BaseException 必须继续上抛，不得被“吃”成 run_failed。
- **为什么**：串行“一轮一个工具”碰上模型“一轮多个 tool_calls”会在历史里留下悬空 tool_call，OpenAI/Anthropic 兼容网关直接 400；当时该异常无人接，**把整个 CLI 进程带 traceback 打崩、run 不落任何终态**（用户侧不可恢复、事件账本不可解释）。配对是线上协议硬约束，不能靠“模型当轮不并行”赌运气。
- **强制**：关卡写在**全仓唯一**的 provider 调用点内部（`kernel/loop.py::_stream_turn`）；判据取 context 侧 `state/checkpoint.py::open_tool_use_ids`（账本驱动的回填盖不住“context 有、ledger 无”的分叉）；补执行复用 ADR-0021 的 `_settle_open_calls`（含权限/floor，绝不绕过 ask）；`tests/integration/test_pairing_gate_and_provider_fault.py` 含源码级“调用点唯一且关卡在请求前”的 fail-on-empty 守卫。
- **不是并行通行证**：本条只保证“发出前成对”，执行仍严格串行；reader/writer gate 与真并发属 P5（ROADMAP §2.5）。

## C20 观测面不得成为载荷的第二载体（ADR-0027 复审补）

- **约束**：日志/trace 一类旁路面**默认只收自有记录**：非 `questor.*` 的外来记录有效级别下界恒为 INFO，**不因 `file_level=DEBUG` 放宽**；装配**不得下调 root logger** 换取自有 DEBUG（只给 `questor` 子树定级）；投影/LLM 通道的载荷只取静态白名单标量键，白名单本身不得含 prompt/参数/结果类键。第三方库自带 sink 写向何处时，**由引入它的那一个适配器模块治理**（不得让内核 import 它）。
- **为什么**：账本已经装不下的东西（SQL 参数元组、请求体、工具输出）会经由**第三方库的 DEBUG 日志**整份落进主干文件——一次实测里，用户 prompt 原文与 `state_digest` 全快照共写进 4 行。这直接旁路 D4「零原文默认」，并把 C13（日志非第二真相）从纪律退化成泄漏面：日志比 DB 更容易被顺手贴进 issue。逐库加降噪名单永远追不上（本轮就踩过一次：名单写小写 `litellm`，真实名是 `LiteLLM`，整整一条降噪从未生效）。
- **强制**：`pipeline._fanout` 的来源门（`tests/unit/observability/test_pipeline.py`、`test_configure.py`）+ `scripts/check_projection_whitelist.py`（内联读键 ⊆ 白名单 **且** 白名单 ∩ 敏感键禁词 = ∅，`--self-test` 自证能判红）+ `tests/integration/test_log_zero_plaintext.py`（真子进程 canary：不得入文件，且一方记录必须真落盘，防空集假绿）。
- **不越界**：本条只管“载荷能不能进观测面”，不管账本本身怎么写（C13/C16）；也不禁止 P7/P10 在**显式授权 + 独立通道 + 有界截断**下开 preview（刀 3）。

## 天花板（诚实标注，别当免费）
"扩事件协议就能到分布式"是错觉。**跨机**的**状态排序、租约、exactly-once、部分失败恢复**是独立的硬骨头（hermes `hermes_state_*`、wuu `agentcontrol` 就在啃）。本架构*容许*演进到那，但那一跳要单独设计，别写进"只是加事件"。

## 与三份文档的挂点
- 每条 C 对应到 `00-layering` 的某条边界 / `01-state-model` 的某字段；CI 规则清单待实现阶段落进 `pyproject`（ruff/import-linter/契约快照测试）。
- 评审口径：任何 PR 触发 C1-C20 之一 = 打回，附本文件对应条目。
