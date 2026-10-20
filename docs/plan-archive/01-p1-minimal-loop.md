# Questor 计划 1（P1）· 最小可跑循环 · 开发计划

> 用途：P1 的**详细开工计划**（ROADMAP §0/§3 约定「每 Phase 开工前另写一份 `docs/plan/NN-<phase>.md`」）。
> 母文档 [`VISION.md`](../VISION.md)；阶段口径 [`ROADMAP.md`](../ROADMAP.md) §1/§1.5/§2.5；契约 [`design/00`](../design/00-layering.md)–[`05`](../design/05-policy.md) + [`HARD-CONSTRAINTS`](../design/HARD-CONSTRAINTS.md)；决策 [`adr/0001`](../adr/0001-from-scratch-not-port.md)–[`0011`](../adr/0011-seq-semantics.md)。
> 实扒证据：`docs/references/R01/R03/R08` + 本计划 §2 的参考扫描表。
> **前置姊妹文档**：[`plan/00-design-skeleton.md`](./00-design-skeleton.md)（P0）—— P0 产八层包骨架 + `contracts/` 全签名 + 分层三防线 + 契约单一真源；**P1 在其上填行为**。交接见 plan/00 §9 与本文 §0/§3/T1/T2。

---

## 0. 定位与原则

**一句话**：P1 用「单模型 + 一个 `read` 工具 + 流式 + 可取消」的**最小能力面**，把「返工代价高的承重接缝一次砌到位」。

两条别混的轴（本计划的核心取舍，经用户确认）：

- **能力面守界**（ROADMAP §2.5 / AGENTS §5 原型口径，越界须先记 ADR）：
  单 turn、**串行工具**、单模型、一个 `read`、**无并行 / 无 MCP / 无子 agent**。P1 唯一目的 = 证明整套设计**自洽无逻辑漏洞**，不是把功能做全。
- **工程面砌实**（AGENTS §0「写全、别欠建」）：事件溯源/seq、真不可变、内外投影+版本闸门、权限引擎骨架、写门 checkpoint、async 流式+看门狗、PolicyPort 契约具体化——这些**早定形、后置=大改**（C11），故 P1 就位。区分线 = 「necessary vs gratuitous」：**砌的是接缝形状与不变式，不是提前实现未来能力**；未来能力只以 `draft/unimplemented` **契约占位**（ROADMAP §1.5 R2）。

**前置与现状（reality wins，VISION §0.4 / AGENTS §5.5）**：仓库当前**无 `src/`、`pyproject.toml` 近乎空**（仅 name/version/py≥3.13）。「可编译接口骨架」= **P0 的交付物**（详见 [`plan/00`](./00-design-skeleton.md)：八层包骨架 + `contracts/` 全签名 + 分层三防线 + `protocol/event.schema.json`）。**P1 的硬前置是 P0 已完成**；本计划 §3/T1/T2 因此从「从零 bootstrap」改判为「**承接 P0 骨架、填实现**」，避免两文档双写同一工作。此归属澄清不改 ROADMAP 阶段口径，无需 ADR。

---

## 1. 范围

### 1.1 进 P1（做且验收到 DoD）
- L0 契约：Command/Event 信封与 union、状态 schema、PolicyPort、ToolSpec、各 Port 接口。
- L1 状态 + `reduce`：Domain_State 真不可变、单写者、不变式（配对 / 森林）。
- L2 内核：turn phase pipeline、终止双向+梯度、取消回填、护栏 P1 子集、策略异常隔离。
- L2 事件总线 + 内外两层投影 + 版本闸门。
- L5：ProviderPort→LiteLLM 流式适配；StorePort→SQLite append-only 事件溯源 + checkpoint。
- L3：`read` 一个内置工具 + 工具路由（校验/权限/记账/超时）。
- 权限引擎骨架（三态/三 mode/denylist/求值次序，P1 验 deny 路径）+ CLI `TerminalApprover`。
- L4：进程内**硬编码单 ReAct 策略**（实现 PolicyPort）。
- L6：CLI 终端（DoD 主面）+ 本地 HTTP+SSE（验 `after_seq` 续传）。
- 横切：轻量结构化日志 / ErrorEntry 错误栈（P1 就落，ROADMAP §1.5 R4）。

### 1.2 留接口位、**不实现**（守 §0 能力面，防膨胀 / 破 ADR）
| 项 | 后置 Phase | P1 只做的 |
|---|---|---|
| 并行工具（reader/writer/饥饿 gate） | P5 | `parallel_safe` 仅 `ToolSpec` schema 占位；执行强制串行 |
| MCP 工具映射 | P5 | `ToolSpec` 形状兼容；无进程隔离 |
| 子 agent / DAG 调度 | P8 | `TaskNode.kind=subagent` 字段、`edge_kind` 预留、deps 仅读校验 |
| 多模态 / 语音事件 data | P6 | 事件 `type` 占位（`voice_attached`/`artifact` 等只增名） |
| 完整 fallback 链 / 凭据池 / 多 hint 分类 | P10 | 单模型；`run_failed.error{code,message,retryable,resumable}` 形状到位 |
| 沙箱后端（seatbelt/bubblewrap/Windows）与 capability floor | P2（ADR-0015） | `SandboxPort` 探针接口 + P1 `none` 后端时 exec/write/network/high **直接 deny**（T4 fail-closed，03 §10）；P2 再允许有围栏的降级 ask，但不得把 floor 降为 allow |
| 三层记忆 / Deep Dream | P4 | `WriteMemory` Command 位；不接向量库 |
| Tauri 桌面壳 | P7 | 不做；P1 仅 CLI + 本地 SSE |

> 任何把上表能力塞进 P1 的冲动 → 先记 ADR 再动（ROADMAP §5）。

---

## 2. 参考扫描与复用（AGENTS §4.5 必做）

**本轮实际扫描集**（`Get-ChildItem project-main` 当下为准，共 12 仓）：hermes-agent / wuu / DeepCode / CowAgent / MetaGPT / cordis / EvoFlow / autogen / crewAI / OpenManus / GenericAgent / Agent-S。P1 直接相关的取证：

| P1 能力 | 取证 `file:line`（相对各仓根） | verdict |
|---|---|---|
| ProviderPort→LiteLLM 流式 | crewAI `lib/crewai/src/crewai/llm.py:854-900`(sync)、`:1584-1650`(async)：`stream=True`+`stream_options{include_usage:True}`、finish_reason/response_id **增量跟踪**（末 usage 块 `choices` 空）、dict/obj 双态防御解析、`defaultdict(AccumulatedToolArgs)` 累积 tool args | **改造复用** → `providers/litellm_adapter.py`（套 ProviderPort） |
| turn 循环 + 取消不变式 | CowAgent `agent/protocol/agent_stream.py:991-1004`(turn 顶探针)、`:1138`(工具间探针)、`:1231-1282`(finally **恒闭合 tool_result** + 中断补 emergency error block)、`:1291-1335`(耗尽→注入总结→**pop**)、`:1838-1840`(取消绝不当可重试)；hermes `agent/conversation_loop.py:1380-1494`(`_LoopState`/`_run_phase` 按名拷回，见 R01) | **改造复用不变式**；循环体自写走 Command/reduce |
| L0 事件协议形状 | DeepCode `core/events/protocol.py`：SQ(UserInput/Interrupt/Shutdown)=Command、EQ(EventMsg frozen union)=Event、`type` 判别 `init=False`、`message_id` 关联、`AgentMessagePhase`(commentary/final)、`summarize_call`(:342 防泄敏)、`summarize_result`(:374 截断) | **改造复用** + 补我们 `v/seq/run_id/ts` 信封 + 内外两层投影 |
| 权限引擎（P1 验 deny 地基） | DeepCode `core/harness/permissions.py:264-404`：三态/三 mode、不可覆盖 `SENSITIVE_PATH_PATTERNS`、二维通配 last-match-wins、求值次序=03 §11 八步、`_candidate_paths`+`_PATCH_PATH_PREFIXES`(抽路径词典)、`never→deny`、`reason` 面向模型可读 | **改造复用**；**补缺口**：其 `normpath`→ 我们需 `realpath+expanduser+evalsymlink`(03 §11) |
| 终端 HITL 审批 | DeepCode `core/harness/approval.py` `TerminalApprover`：y/n/always、非交互→deny fail-closed、`as_async`=`asyncio.to_thread` | **改造复用** → `surfaces/cli` |
| SSE 发射帧 | CowAgent `channel/web/api/openai_compat.py:343-344`(`data:{json}\n\n`)、`:567`(`[DONE]`)、`:797-799`(headers)、`:523-528`(queue+idle 超时) | **改造复用** 帧/头/看门狗；`id:<seq>`+`after_seq` 二者皆缺 → **自写** |
| 事件溯源 + `after_seq` 续传 | DeepCode `core/persistence/event_repository.py:21-56`(append `MAX(seq)+1 WHERE thread`)、`:58-78`(replay `WHERE seq>after ORDER BY seq`)、`:80-120`(sequence_head / `newest_row` rowid 水位)、`persistence/migrations.py:160-170`(event_log `UNIQUE(thread,seq)`+`idx_events_replay`)、`:1448`(`BEGIN IMMEDIATE`) | **改造复用** → StorePort/SQLite event log + replay（双游标 ADR-0011） |
| checkpoint 写门 | CowAgent `agent/protocol/step_writer.py:128-144`(`_closed_prefix`=每个 tool_use 已应答的最长前缀)、`:22-25`(按 `id` 身份非下标去重)；DeepCode `core/sessions/transcript.py:132-154`(`{reset,retain}` 恢复指针) | **改造复用** `_closed_prefix`+replay（`provider_state`/DAG 留 P3） |
| ReAct 单步策略概念 | OpenManus `app/agent/react.py`(think/act/step)、`app/agent/base.py:170-186`(`is_stuck` 重复检测+nudge) | 概念**参考**；实现自写对齐 PolicyPort |
| PolicyPort 契约形状 | wuu `internal/loopdriver/contract.go:14-76`(LoopPolicy/Gateway/Create-Resume + 版本门控 checkpoint)，见 R01 §② / G-6 | **参考** 具体化 `contracts/policy.py` |

**纪律**（AGENTS §4.5）：复用一律守分层（C1/C14，重包到 Port 之后）、尊重各仓 **license + 署名**、真移植处**文件内标 provenance**、优先适配本项目契约非逐行照搬。许可核对在每个实现 PR 落文档时补记。

---

## 3. 承接 P0 骨架（前置产物，P1 在其上开工）

> 下面这棵树是 **P0（[`plan/00`](./00-design-skeleton.md)）建好的骨架**（含 stub 全签名 + 分层三防线）；P1 不改结构，只把各层 `NotImplementedError` 的 stub **填成实现**并在 `pyproject` 加实现依赖。

```
questor/
├── pyproject.toml  # 加依赖 + ruff/import-linter 配置
├── .importlinter   # 八层依赖契约（人读意图，C15 防线①）
├── src/questor/
│   ├── contracts/      # L0  纯抽象+数据：events/state_schema/policy/tool/ports
│   ├── state/          # L1  Domain_State + reduce
│   ├── kernel/         # L2  loop/ events(总线) / permissions
│   ├── capabilities/   # L3  tools/read.py（skills/mcp stub 空目录+README）
│   ├── policy/         # L4  react_policy.py（进程内单策略）
│   ├── providers/      # L5  litellm_adapter.py / store_sqlite.py / clock / id
│   ├── surfaces/       # L6  cli.py / http_sse.py（零业务）
│   ├── config/         # 配置+secrets 边界
│   ├── observability/  # 结构化日志/error_stack 汇总（只读）
│   └── __main__.py     # 入口（CLI；sidecar 启动点占位）
└── tests/{unit,integration}/
```

- **依赖钉版**（uv、Python 3.13）：`litellm`、`pydantic>=2`、`immutables`、`jsonschema`、`fastapi`+`sse-starlette`、`aiosqlite`、`pytest`/`pytest-asyncio`、`import-linter`、`ruff`。
- **三道分层防线**（HARD C15 / R09：import-linter 在参考集零采用且拦不住动态 import）：① `.importlinter` 声明式契约 ② `ruff` `flake8-tidy-imports.banned-api` 点名禁跨层 import（附「改走哪个 Port」）+ `ban-relative-imports=all` ③ 自研 AST 检查器（禁 reduce 内原地 mutate、禁 contracts 出现实现）。每条守卫带 `--self-test` + **fail-on-empty**（扫不到文件≠通过）。

---

## 4. 实现步骤（T1→T13，依赖有序）

> 每步 `→ verify:` 是自检钩子（AGENTS §4 目标驱动）；单测随模块镜像目录。

### T1 承接 P0 骨架（前置：[`plan/00`](./00-design-skeleton.md)）
P0 已产八层包骨架 + 分层三防线 + 冷导入/CI；P1 仅在 `pyproject` 补实现依赖（`litellm`/`fastapi`+`sse-starlette`/`aiosqlite`/`pytest-asyncio`），把 P0 的 stub 基类接进装配。
→ verify:P0 五 DoD 仍绿（冷导入/边界/契约快照）；新增依赖可导入；未破坏 contracts 边界。

### T2 微调 P0 契约签名（`contracts/`，依赖 T1）
> P0 已把 `contracts/` 全签名锁成**形状**；P1 只按实现需要**微调/补全字段**，严守**只增不改**（C6/C11）：
- `events.py`：Command union(`SubmitMessage/ProposeAction/ResolveApproval/Cancel/WriteMemory/RequestCompactHint`)、内部 Event、外部投影 EventMsg、信封 `{v,seq,run_id,turn?,ts,type,data}`、关联键常量(`run_id/turn/tool_call_id/card_id/item_id` **定死**)。占位：`kind=subagent`、多模态/语音 type、`parallel_safe`。
- `state_schema.py`：`Session/Run/context/task_tree/tool_ledger/checkpoints/permission_ctx/error_stack` 的 frozen schema（内部集合用 `tuple/frozenset`/immutables）。
- `policy.py`：`PolicyView` / `PolicyIntent`(`ProposeToolCall|ProposePlanUpdate|AdviseCompact|SuggestFinish|SuggestCancel`) / `PolicyPort`(`id/fingerprint/propose_action` + 可选 `init/dispose/on_tool_result`)；含 `LoopPolicy` + 版本门控 checkpoint 位（R01 G-6）。
- `tool.py`：`ToolSpec`(name/params JSON-Schema/capability/risk/`parallel_safe`占位/available/read_only/approval_mode) + `Tool.execute(args,ctx)->ToolResult{status,result,display?,files?,artifact?}`。
- `ports.py`：`ProviderPort/StorePort/Clock/Id/SandboxPort`(能力探针 `fences_writes/fences_network/isolates_process_tree`)。
→ verify:contracts 内无任何 import provider/kernel/policy/surfaces（AST 检查器 + import-linter）；纯 frozen 数据可序列化。

### T3 L1 状态 + reduce（`state/`，依赖 T2）
- Domain_State 真不可变（pydantic-v2 frozen **配不可变集合**，C2 非浅冻结）。
- `reduce(state, command) -> (new_state, events[])` = **唯一写入口**；reduce 内强制不变式 I1：`tool_use↔tool_result` 配对、TaskNode v1 仅森林(deps 只读校验、拒成环)；**永产新态、禁原地 mutate**(X3)。
- 非法 Command → reduce 拒绝 + 产 error 事件（不靠上层自觉，01 I1）。
- `PolicyView` 靠 COW/结构共享按字段暴露（策略看不到断点/权限/内部元数据，C2/C3）。
- `LoopState`（放 kernel，见 T7）允许内部可变槽、不持久(R01 G-8)。
→ verify:单测——改视图抛错；提交孤儿 tool_use 被拒；旧 state 实例在 reduce 后逐字节不变（COW 断言）。

### T4 L5 ProviderPort→LiteLLM（`providers/litellm_adapter.py`，依赖 T2）
- 改造 crewAI 流式装配：`stream=True`+`include_usage`、增量 `finish_reason/response_id`、tool-args 跨块累积；**usage 不假设只在末块**、reasoning 字段多别名(`reasoning_content/reasoning/thinking`)归一、**thinking 绝不进对外正文**(R08 C-P2/P3)。
- 错误归一为 `ErrorEntry`(01 §8) envelope；分类=**纯函数进 contracts**、重试/fallback 编排归 Kernel（ADR-0010）。P1 单模型、满预算重试即可，fallback 链仅留接口位。
→ verify:假 provider 回放（cassette）测流式装配含 tool 分片；越层 import provider 被禁。

### T5 L3 `read` 工具（`capabilities/tools/read.py`，依赖 T2）
- workspace 根内读文件 → `ToolResult`；`ctx` 只给受控能力（workspace root / `is_cancelled()` / `report_progress()` / StorePort 读），**无裸句柄**（03 §2）。T1 约束：工具**只返回 ToolResult、绝不提交 Command/改状态**。
→ verify:工具 import provider/store/sandbox/UI 被禁；越界路径返回 error 而非崩。

### T6 权限引擎（`kernel/permissions/`，依赖 T2/T3）
- 改造 DeepCode `permissions.py`：三态 `allow/ask/deny`、三 mode `default/plan/full_auto`、二维通配 last-match-wins、mode 默认、`approval_policy=never→ask降deny`、read-only 上限 fail-closed、`reason` 面向模型可读+给合法替代。
- **补 `realpath+expanduser+evalsymlink`** 规范敏感路径（03 §11；DeepCode 只 normpath）。五层校验前 3 层：JSON 合法→JSON-Schema→arg-key 词典抽 path/command/patch 前缀。
- `denylist` 命中直接拒**且不计入失败重试**、仍写进 ToolLedger 审计（01 §6）。
→ verify:读 `.env`/`.ssh/*` → deny 不可被 rules/mode 覆盖；plan mode 拒写类；never→deny。

### T7 L2 turn 循环内核（`kernel/loop/`，依赖 T3/T4/T5/T6）
- phase pipeline：`begin_turn → build_request(view, tools_frozen) → perform_call(投 *_delta **不落状态**) → assemble_message(reduce→message_completed) → propose_action(PolicyPort) → route → maintenance(turn 边界 checkpoint + loop-guard + 压缩检查位)`；每 phase 返回新 `LoopState` + events[]（hermes `_run_phase` 按名拷回，04 §2）。
- **终止双向 + 梯度**（R01 G-1/G-2 `[P1]`）：可**拒绝过早 Finish**（pending tool_use 未闭合 / stall「说继续没工具」→ 注入**有界 nudge** 续跑）；硬终止前 预算 0.9→checkpoint 提示、wall-clock 80%→wrap-up、耗尽→**一次无工具 grace call**→仍不收则**强制无工具总结**（注入→取→pop、`retry_on_empty=False` 防空转成环）。
- **取消（C7）**：走 `Cancel Command→reduce` 置 `cancelled` **且回填所有 pending/running tool_call 为 error**（CowAgent finally 恒闭合范式）；`cancel_reason` ∈ `{user|timeout|budget_exhausted|no_progress|safety|owner}` **从记录派生**；取消错误**绝不进重试/fallback**(R01 F8)。
- **护栏 P1 子集**：工具入参重复(同 tool+args 连续 N 次→中断)、续跑上限(只认显式归一 continue、非续跑即归零，R01 G-3)、cancel 安全点探针(turn 顶 / 工具间 / 流式途中每 K chunk)。阈值全进 `run.budget` 配置化(04 L4)。
- **策略异常隔离（X4）**：PolicyPort panic→捕获、回滚 `Domain_State` 到 turn 前一致态、发 error 事件；**已发 delta/外部事件不撤回**（客户端处理「半流后回滚」，C10）。
- 工具轮（串行）：`permission_gate → validate → 执行(read 直连；exec/write P1 走 none 后端→deny) → 记 ToolLedger → 回填 tool_result → reduce → 发 tool_* → verdict=continue`。
→ verify:三条异常路径各一集成用例「先红后绿」；turn 边界恰一终态事件；取消后无孤儿 tool_use。

### T8 事件总线 + 内外投影 + 版本闸门（`kernel/events/` + `surfaces`，依赖 T2/T3）
- `EventBus`：Command **受理即占 durable seq**（早失败也能落终态，02 §10）；Event append-only、发出不可撤回、**终态唯一 first-writer-wins**(C13)、并发终止按优先级择一(取消>安全>超时>预算，可配)。`*_delta/heartbeat/tool_progress` **不占 durable seq**（live-only，02 §10）。
- 投影层：内部细粒度→外部精简集（映射表+字段白名单+截断+`hidden` 可见位）；版本闸门（不符→`resync_required{expired|ahead|unknown_request|version_mismatch}`）；未知 `type` 静默忽略、**未知 error 类至少告警**(C6)。
→ verify:回放=重放内部事件再投影、外部不入库(X2/C13)；版本不匹配产 resync；delta 不落状态。

### T9 事件溯源存储 + checkpoint（`providers/store_sqlite.py`，依赖 T2/T3/T8）
- 改造 DeepCode `event_repository.py`：`event_log(run_id, seq, type, turn, item_id?, payload_json, ts)`；`append` 用 `COALESCE(MAX(seq),0)+1 WHERE run_id`（per-run 逻辑 seq）+ `UNIQUE(run_id,seq)` + `idx_replay(run_id,seq)`；`replay(run_id, after_seq, through?, limit)` = `WHERE seq>after ORDER BY seq`（= `after_seq` 续传）；`sequence_head` + 全局物理 `rowid` 水位（双游标 ADR-0011）。
- 写序：**先 append log（原子）→ 再更新 snapshot/index；snapshot 缺/损坏→由 log 重放**（01 §13/R03 B-2，log 是唯一真相）。`BEGIN IMMEDIATE` 落单写者（C2）。JSON 禁 NaN/Inf、时间 UTC tz-aware（R03 B-P3）。
- checkpoint：turn 边界轻量快照（投影+指针，I4）+ `_closed_prefix` **写门**（durable 永不半 tool_use，R03 C-1）；恢复 = 最近快照 + 重放其后事件（ADR-0005）+ 悬空 user-turn 兜底。（**实现期修正**：P3 发现截断与 HITL 续跑冲突，最终不截断、改“完整快照 + 派发侧补齐”，`closed_prefix` 仅用于识别在途集——见 [ADR-0020](../adr/0020-durable-write-gate-and-log-authority.md)/plan/03 §6；配对由进入 provider 前的 settle 保证，每次回发前的关卡见 [ADR-0028](../adr/0028-pairing-gate-and-provider-fault-normalization.md)。）
→ verify:kill-重启从 checkpoint 续跑；`after_seq` 重放不丢不重；损坏 snapshot 回退重放。

### T10 L6 传输面：CLI + 本地 HTTP+SSE（`surfaces/`，依赖 T7/T8/T9）
- `cli.py`（**DoD 主面**）：起 run → 消费事件流 → 流式打印 assistant text → `Ctrl-C`→ 发 `Cancel` Command → ask 走 `TerminalApprover`。
- `http_sse.py`：改造 CowAgent SSE 帧/headers + **自写** 行首 `id: <seq>` 与 `Last-Event-ID`/`after_seq`→接 T9 `replay`；`POST /run·/cancel·/resume`。仅「收 Command + 投事件」**零业务**(S6)。
→ verify:`curl` SSE 断连后带 `after_seq` 重连补齐；CLI 问一句答一句可中断。

### T11 L4 进程内策略（`policy/react_policy.py`，依赖 T2/T3/T4/T7）
- 硬编码单 ReAct 策略实现 `PolicyPort`：读 `PolicyView` → 出**单步意图**（调 `read` / `SuggestFinish`）。**非法工具名/参数** → 包成被拒 Command + error 事件、verdict=continue、错误回填 context 下轮自纠（04 L1，不崩循环）。
- run 内 policy 快照冻结（`policy_id+fingerprint`，ADR-0009）；注册表/热替换/AB **后置 P9**（仅留 `fingerprint` 位、`run_started` 带 `policy_ref`）。
→ verify:故意返回不存在工具名 → 不崩、产 error、下一轮继续。

### T12 轻量可观测/错误栈（`observability/`，依赖 T2/T8）
> **兑现状态（2026-10-17，日志刀 2 PR-B / ADR-0027）：骨架已兑现**——装配缺口（四入口 + `questor.bus` 出声 + console 绑 stderr）由刀 1 PR-A 补齐；**双通道汇流（带内桥 + 带外投影）/ `LogEntry` 中间表示 / 白名单值域 / 脱敏 / 节流 / 关联 id（run_id/turn）/ 按日 JSONL 文件面（errors/llm 分流 + 软阈值降级）/ LLM 零原文观测 / G-L1..L12 守卫**由刀 2 PR-B（`docs/log/` 全套）落地，组合根 `__main__` 已接完整管线（运行时首次生效）。规格真源 `docs/log/DESIGN.md`（原 `ErrorEntry` 路线由 `LogEntry` 中间表示取代，见 DESIGN D3）。**仍随刀 3**：§14 `questor logs` 消费命令、`--log-payload` preview 实装、OTel/metrics。
- 结构化日志 + `ErrorEntry` envelope 汇总（`layer∈{kernel,tool,provider,persist}`）+ 事件流即观测面；**只依赖 contracts、只读、不改状态**(S7)；热路径打点带节流窗（R08 E-P3）。
→ verify:observability import kernel/policy 实现被禁；错误事件载荷脱敏（不记凭据，R08 E-6）。

### T13 测试与验收（`tests/`，依赖 T1–T12）
- 单元镜像：不可变、reduce 配对、权限 deny、`_closed_prefix` 写门、SSE `after_seq` 幂等重放、投影版本闸门、流式 tool-args 累积。
- 集成（假 Provider 录回放）：跑通 §5 五验证项 + kill-重启续跑。
→ verify:`pytest` 全绿 + 冷导入 + `lint-imports` + AST 守卫 + ruff。

---

## 5. DoD 验收清单（= ROADMAP §2.5 + AGENTS §5）

1. **单 turn、串行工具**（`parallel_safe` 仅占位）跑通 `SubmitMessage → turn 循环 → ProposeAction 调 read → tool_completed → run_completed`；
2. **三条异常路径不崩**：① 用户取消 ② 工具被 deny（命中 denylist）③ PolicyPort 返非法意图（→被拒 Command+error+continue）；
3. **SSE 断线 + `after_seq` 续传不丢不重**（集成测试证）；
4. **简单 checkpoint 断点恢复**：kill 进程重启能续跑/回放（无并行）；
5. **终端「问一句→流式答一句」、中途可取消且状态/事件一致**（手工复现，非模糊声明）；
6. **质量门**：冷导入 + import-linter/ruff/AST 守卫绿 + 单测+集成过 + **不违任一 C1–C15 红线**。（注：本项验收时红线全集仅至 C15；现全集见 `HARD-CONSTRAINTS` 至 **C19**，P1 代码在 C16–C19 下亦已复验——见 §11.1。）

---

## 6. 红线对照（P1 如何机械守）

| 红线 | P1 落点 | 强制方式 |
|---|---|---|
| C1 分层方向 | 内核只认注入的 Port | `.importlinter`+ruff banned-api（T1） |
| C2 单写者+不可变 | `reduce` 唯一入口、Domain_State 深不可变 | immutables/tuple + AST 禁原地改 + 单测断言旧态不变 |
| C3 视图/快照 | PolicyView 只读投影、快照仅回放时 | COW/结构共享 |
| C4 Store 走接口 | 读写均经 StorePort，策略无裸句柄 | Port 抽象 |
| C5 Command/Event | 只有 Command 改状态、Event 不反哺 | 类型总线分开（T2/T8） |
| C6 内外投影+版本 | 外部精简集、未知忽略、error 告警 | 投影层+契约快照 diff（T8） |
| C7 终止走命令 | Cancel Command→reduce 回填 pending | 内核判定+reduce 不变式（T7） |
| C8 工具边界 | 校验/权限/沙箱/记账全在 Harness | 工具路由入口（T6/T7） |
| C9 三态一等+沙箱可插拔 | 三态入 L1/L2、P1 none 后端→deny | PermissionCtx+SandboxPort 探针 |
| C10 故障隔离+回滚 | 策略 panic→回滚 Domain_State、事件不撤 | 熔断护栏（T7） |
| C11 谨慎演进 | 接缝定死、字段占位、schema 带版本 | 关联键常量+只增不改+契约快照 |
| C12 远程预留 | 进程内、纯 frozen、无 RPC | 设计约束 |
| C13 存内事件+终态唯一 | event_log 存内部、first-writer-wins | reduce 串行（T8/T9） |
| C14 结构边界机器守 | kernel 不 import policy/surfaces 实现 | import-linter 独立 blocking job |
| C15 单一真源+守卫可信 | protocol schema 真源 + 守卫 self-test | codegen+`--check`、fail-on-empty |

---

## 7. 风险与缓解

- **R-A｜COW 语言级坑**：pydantic frozen 仍**浅冻结**，内层 list/dict 可被改。→ immutables/tuple + 自研 AST 检查器禁 reduce 内 mutate + 单测「reduce 后旧实例逐字节不变」（04 X3）。
- **R-B｜`after_seq` 不丢不重**：CowAgent/DeepCode 皆**无** `id:<seq>`+after_seq 精确重放，需自写。→ 以 DeepCode replay 为基，投递幂等简化为「稳定 `tool_call_id` + 消费端去重集」（R08 F3，CAS 留 P10），写门 `_closed_prefix` 保配对。
- **R-C｜取消撕裂状态**：→ 只走 Command→reduce 回填 pending、绝不上抛当可重试；「取消只在下个 checkpoint 生效」有尾窗（02 §10）需在文档与事件里诚实标注。
- **R-D｜「提前砌实」与「能力守界」失衡**：→ 严守「砌形状/不变式、不提前实现能力」；§1.2 后置表为硬清单，越界先记 ADR。
- **R-E｜复用代码击穿分层**：DeepCode permissions/event_repo 若原样搬会 import 其内部。→ 重包到 Port 之后、内核不 import 具体实现、import-linter 作**不依赖 change-classifier 的独立 blocking job**（C15）。
- **R-F｜许可/署名**：改造复用多处（DeepCode/CowAgent/crewAI）。→ 真移植处文件内标 provenance、随实现 PR 核对各仓 license（AGENTS §4.5）。

---

## 8. 被否方案与取舍

- **❌ 纯薄桩过 P1**：只够点亮 DoD、接缝留白 → 欠建必要工作（违 AGENTS §0）、且 P3/P5/P9 回头大改已锁接缝（违 C11），返工最痛。**用户明确不要此路。**
- **❌ P1 全量做并行/MCP/子 agent/完整沙箱**：越 ROADMAP §2.5 原型口径、需 ADR、稀释「证明设计自洽」目标、放大爆炸半径。
- **❌ 直接 fork DeepCode 内核**：其 SQ/EQ 单投影（无内外两层）、无 pydantic 深不可变、`normpath` 非 `realpath`、无 PolicyPort 分层——与我们契约不同构，且违「从零自研」（ADR-0001）。→ 只**改造复用其已验证片段**并守分层。
- **✅ 取舍结论**：「**接缝砌实 + 能力守界**」——以最小可复现串行能力，承载最稳的接缝形状与不变式；提前做仅针对「后置=重构」的承重墙，能力位只占位不实现。

---

## 9. 文档 / ADR 回写 & 里程碑

- 本文件即开工基线；实现中**偏差回填本文** + 遵循 VISION §0.4（reality wins）（AGENTS §5.5）。
- P1 若暴露新红线（realpath 缺口、reduce 原地改的 AST 强制方式、after_seq 尾窗语义）→ 补 `HARD-CONSTRAINTS` 或对应 `design/*`。
- 阶段口径若变（把某提前砌实接缝升为正式跨阶段决策）→ **先记 ADR**（ROADMAP §5）；当前实现细节走本文件。
- **发布里程碑节点 B**（ROADMAP §4）：P1 完成即开源「最小可运行原型（终端 Demo）」，拿第一批真实反馈。

## 10. 执行顺序与提交粒度

**依赖链**：**P0（[`plan/00`](./00-design-skeleton.md)）先行 → P1** T1(承接骨架)→T2(微调契约)→{T3,T4,T5}→T6→{T8,T9}→T7→T10→T11→T12→T13。T8/T9 可与 T7 并行准备（契约先行）。

**建议提交粒度**（细粒度、英文 Conventional Commits，**每次 commit/push 均须用户当轮明确许可**，AGENTS §6）：
`chore(p1): add impl deps + wire P0 stubs` → `feat(contracts): fill contract fields (additive)` → `feat(state): domain state + reduce invariants` → `feat(providers): litellm stream adapter` → `feat(capabilities): read tool` → `feat(kernel): permission engine` → `feat(kernel): event bus + projection` → `feat(providers): event-sourcing store + checkpoint` → `feat(kernel): turn loop` → `feat(surfaces): cli + local sse` → `feat(policy): in-proc react policy` → `test(p1): DoD 五验证项` → `docs: fill plan/01 deviations`。

## 11. 实现偏差回填（reality wins，AGENTS §5.5；据 2026-10-15 对抗审计 `docs/audit/P0-P1-review-2026-10-15.md` 全量修复）

审计判定 P1 存在两个已复现 Blocker 与若干阻断/应修项，本session已逐条修复并补证伪测试（当前 `pytest` 64 passed、四守卫全绿）。与本文原承诺的偏差：

**已修复（含测试）**
- **C2 假不可变**（Blocker）：`ToolCall.args` / `ContentBlock.input·payload·provider_state` / `Envelope.data` 改 `immutables.Map` 深冻结（`contracts/common.py: freeze/thaw`），序列化/校验边界 `thaw` 还原。测试 `test_leaf_dict_is_immutable` / `test_cow_states_do_not_share_mutable_leaf`。本文 §0「工程面砌实」据此补实。
- **Cancel seq 碰撞**（Blocker）：`reduce` 的 Cancel 分支改为「本次事件连续取号 `run.seq+1..+n`、`Run.seq` 推进到最大事件号」，回填事件与终态不再同 seq（旧路径落库 `IntegrityError`）。测试 `test_cancel_persist.py`（带 store）。
- **A1 checkpoint/断点恢复**：`state/snapshot.py` 序列化 + loop turn 边界 `save_checkpoint` + `kernel/recovery.py: resume_run`（取最近快照重建 Domain_State）。测试 `test_checkpoint_and_resume_roundtrip`（关库重开模拟新进程）。
- **A3 capability/risk fail-closed**：loop 工具路由读 `spec.capability/risk` + `SandboxPort` 探针；无后端时 exec/write/network/high → **deny**（非 ask/裸执行）。测试 `test_sandbox_gate.py`。
- **A2 护栏**：`Budget` 的 `repeat_tool_limit`（同工具同参连续）、`max_consecutive_continuations`（空答）、`deadline_seconds`（墙钟）、`max_tokens`（用量）全部接进 loop 并触发 `run_failed`；新增「拒绝过早 Finish」（有未闭合 tool_use 时不 finalize，续跑）。测试 `test_loop_hardening.py`。
- **C10 策略故障隔离**：`propose_action` 抛错 → 捕获、发 `warning` 事件、**回滚 Domain_State 到 turn 起点**、连续 3 次则优雅 `run_failed`（外部已发 delta 不撤）。测试 `test_run_survives_panicking_policy_and_fails_gracefully`。
- **A4/入口/活文档/守卫细节**：`python -m questor` 接 CLI；CHANGELOG 补 P0/P1+Fixed；bus 终态清理订阅队列（`_closed` 保留以守终态唯一）；`check_protocol_schema` 加 fail-on-empty。

**诚实降级为 draft（本次未强制，非“已完成”）**
- 梯度终止的「软预警 checkpoint 提示 / wall-clock wrap-up 提示 / 一次无工具 grace call / 耗尽强制总结」需额外 provider 往返，属 04 §13/§3 `[加固]`，**P1 未实现**（当前：预算/截止/重复到点直接 `run_failed`）；这些字段与接缝已就位，P10 加固期补全。
- 流式看门狗双超时、idle-progress 看门狗、POSIX/PowerShell shell 命令解析、跨机/多进程一致性：分别后置到 P2/P10；P1 不做。

**未改的结论**：能力面仍守 §2.5 串行最小集（无并行/MCP/子 agent），审计 scope-drift 核验亦确认未越界；真实 LiteLLM 端到端与跨真实 HTTP 的 SSE 断连重连仍 **UNVERIFIED**（无 key / 环境无 uvicorn），列入 §7 未覆盖项。

### 11.1 追加回填（2026-10-16，真机崩溃核验 → **ADR-0028**）

用户真实使用中“模型一轮发 ≥2 个 tool_call”→ provider 400 → **CLI 进程带 traceback 直接退出、run 不落终态**。
本节只追加、不改上方 2026-10-15 的审计结论：

- **T4「错误归一为 `ErrorEntry`(01 §8)」当时只做了形状、未接线**：`ErrorLayer.PROVIDER` 生产路径 0 使用、
  `ProviderPort.stream` 唯一调用点裸奔、src 内 `FORMAT_ERROR`/retry 零生产者。本轮落下：
  `contracts/errors.py::classify_provider_error`（ADR-0010 的纯函数）+ kernel 边界捕获→`run_failed`。
- **T4「满预算重试」字面未执行（故意）**：本轮不自动重试——先有关卡/分类，重试编排才有意义；退避/fallback
  链/凭据池按 §1.2 后置表仍归 P10。400 配对违规已钉为 **不可重试**，否则届时会把同一个确定性错误打满预算。
- **DoD §5-2 的“三条异常路径不崩”事实上不够**：provider 故障必须并列为**第四条**。本轮已补进
  `HARD-CONSTRAINTS` **C19**（机制强制，不靠自觉）；§5-2 保留原文作为当时的验收基线，不回改。
- **turn 粒度变更（已走 ADR，属本阶段行为修正、非能力越界）**：一条 assistant 里的 N 个 tool_use 在同一
  次回发前**串行**闭合（仍不启用并行，§2.5 口径不变）。因此 `repeat_tool_limit` 仅覆盖策略提议路径，
  关卡补执行不计入重复签名；总 turn 数不增。
- **同片雷区两个额外缺陷**（本轮一并修）：① stop-gate 的 `continue` 同样带悬空回发；② 被
  `AppendAssistantMessage` 拒收的 assistant 会经 `FinalizeRun(final=…)` **走私回 context**，留下一条永不配对
  的 tool_use 且因 `completed` 不进 `--list`/resume。现均 fail-closed 出声。
- **改名（ADR-0021 的派发函数）**：`_resume_settle_open_calls` → **`_settle_open_calls`**（resume 入口与
  每-turn 关卡两个安全点共用；行为逐字不变）。上方 A2 项里“拒绝过早 Finish”的机制保留，仅回发前多了关卡。
- 测试：`tests/integration/test_pairing_gate_and_provider_fault.py`（10）、`tests/unit/test_provider_error_classification.py`（8）。
  真网关异常形状（litellm 版本相关的 `status_code` 载体）仍 **UNVERIFIED**（无 key）。
