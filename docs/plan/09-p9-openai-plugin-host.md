# Phase P9 详细计划 — 对外接口（OpenAI 兼容）+ 插件宿主（cordis 式 DI/热插拔）

> 起手**必读**：[`AGENTS.md §0/§4.5/§5/§5.5/§6`](../../AGENTS.md) · [`docs/ROADMAP.md §1(P9行)/§1.5/§2/§5`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)
> **§0 未填完 = 本 Phase 计划未就绪、不能开工**（ROADMAP §0 硬门槛）。
> 本文最初为 **READ-ONLY 规划产物**；**两路对抗式评审已执行并收口（见 §4.3，M1/M2/S1/S2/S3/R1 全关）**，Blocker/Major 已闭 → 已按 ADR-0012 建 worktree 分支 `feat/p9-openai-plugin-host`（基线 `090e5cb`）进入实现。
> **实现状态（2026-10-18）**：T0–T11 已全序落地、每条 TDD 先红后绿、每步过守卫、细粒度原子提交；详 §9 落地偏差回填。push/merge 逐次征询（PR-only）。
> 状态：`docs/plan/09-p9-openai-plugin-host.md`，基于 `main` HEAD `090e5cb`（PR #149 合入 P8）。ADR-0043~0047 已落册转正。测试基线：继承 P8 `739 passed / 5 skipped`；P9 收尾 **797 passed / 5 skipped**（+58 用例）。
> 规范：Conventional Commits 标题**小写动词开头**（`feat: add …`），CI `pr-lint` 会拦；commit/push **逐次征求许可**（AGENTS §6，绝不擅自提交/推送）。

---

## 0. Peer-Repo 扫描（**必填**，AGENTS §4.5 · 综合取优）

**现场重列 `project-main/` 目录**（`Get-ChildItem`，2026-10-18 实测，12 个兄弟仓，剔除 `questor*` worktree 与 `build/编码/新建文档`）：
`Agent-S-main / autogen-main / cordis-main / CowAgent-master / crewAI-main / DeepCode-main / EvoFlow-main / GenericAgent-main / hermes-agent-main / MetaGPT-main / OpenManus-main / wuu-main`。
**规范工作区 = `questor/`（main，`090e5cb`）**；`git worktree list` 实测仅注册了主工作区，其余 `questor-*` 目录为历史副本，Phase 2 起手须按 ADR-0012 新建 `questor-p9-openai-plugin-host` linked worktree。

**许可核验（ADR-0031 免文件内署名，但许可类型仍逐仓核，实读 LICENSE 首行/正文）**：MIT = **cordis / wuu / DeepCode / MetaGPT / OpenManus / hermes / GenericAgent / CowAgent**（CowAgent LICENSE 正文为标准 MIT 授权句，`Copyright (c) 2022 zhayujie`）→ 可安全改造复用；Apache-2.0 = Agent-S；**CC-BY-4.0 = autogen**（`Attribution 4.0 International`，代码引用谨慎，本 Phase 只取其多 agent runtime 设计口径、不搬码）；**EvoFlow = PolyForm Noncommercial（`Required Notice … EvovexAI`）→ 只读设计、绝不搬码进 MIT 仓**（本 Phase 参照其 gateway 路由形状）。

| 能力 | 扫描仓（`file:line`） | 结论（复用/改造/自写） | 复用/改造说明 · 许可/边界注意 |
|---|---|---|---|
| **OpenAI 兼容 wire / SSE chunk 投影** | **CowAgent** `channel/web/api/openai_compat.py:255-278`（`_base_chunk`：`object:"chat.completion.chunk"`、`choices[{index,delta,finish_reason}]`、专有收 `cow_event` 扩展位）、`:343-344`（`_sse_frame` `data:{json}\n\n`）、`:281-340`（`_ToolEvents` tool_start/tool_result→事件外挂）、`:434-447`（content/reasoning delta 映射）、`:465-470`（worker 边界异常→`_STREAM_ERROR`、finally→`_STREAM_END`）；**DeepCode** `app_server/service.py:1`、`core/providers/openai_compat.py:1`（又一 OpenAI 形状）；**EvoFlow** `backend/app/gateway/routers/openai_compat_apps.py:1`（只读设计） | 改造（取 wire 形状，落我们投影层） | `http_sse.py:8` 已注明 SSE 帧风格改形自 CowAgent `openai_compat.py`——本 Phase 在同一 `create_app` 上挂 `/v1/chat/completions`。**不搬 CowAgent 的 threading/queue 传输**（我们是 asyncio bus 订阅）；标准字段走 OpenAI 语义、专有进 `x_questor`（design/02 §10）。 |
| **策略/能力注册表 + 热替换** | **cordis** `packages/core/src/registry.ts:125-214`（`RegistryService`：plugin 按 callback 键、`Plugin.Runtime{fibers:DisposableList}`、`delete()`→逐个 `fiber.dispose()`）、`fiber.ts:107-224`（`FiberState.PENDING→ACTIVE`、`dispose`、`assertActive`、`restart`）、`service.ts:33`（`ctx.reflect.provide`）、`@Inject` 依赖声明、`hmr/index.ts`（热重载）；**MetaGPT** `metagpt/roles/role.py:1`、`roles/__init__.py`（角色注册） | 改造（取**注册/生命周期/隔离形状**，**不引 TS Fiber/Reflect 容器**） | cordis 是 TypeScript（cosmokit/装饰器/proxy），**字面移植违 AGENTS §2**；只借"按 id 注册、可 dispose 的 fiber 生命周期、trust isolate"概念。P9 落 `PolicyRegistry`（进程内纯结构）+ 薄生命周期协议（见 §4.1 与 ADR-0047）。 |
| **插件宿主 / 热插拔 + 故障隔离** | **DeepCode** `core/plugins/host.py:44-49`（`LocalPluginHost`："inert discovery — reads manifests，**never imports plugin code / starts a process / activates MCP / executes hooks**"）、`registry.py:32-70`（`LocalPluginRegistry`：json+lock 原子、`PLUGIN_REGISTRY_SCHEMA_VERSION=1`、`MAX_REGISTERED_PLUGINS=256`、`PluginAlreadyRegisteredError`/`PluginRegistrationNotFoundError`/`PluginRegistryError` 三分）、`domain.py`（`PluginComponentStatus`/`PluginSnapshot`/`PluginDiagnostic`）；**本仓已存** `capabilities/tools/registry.py:60-99`（`register/unregister` 只影响**下一次 `freeze_for_run`**、活 run 不变）、`kernel/loop.py:389-395`（policy 抛错→`WARNING` 回滚、C10 已存）、`capabilities/mcp/manager.py`、`capabilities/skills/catalog.py` | 改造 + 复用现成注册点 | 本仓 tools/skills/mcp **已是可热插的注册点**；P9 **不重造 cordis 容器**，只补：统一 `init/teardown` 生命周期 + 每插件调用熔断护栏（C10）+ `tools_changed` 事件（design/02 §7 预留名）。inert-discovery 纪律直抄 DeepCode（发现≠执行）。 |
| **跨进程/多机 exactly-once claim·delivery_state·lease**（接回 P8 后置） | **wuu** `internal/agentcontrol/worker_execution_lease.go:1`（241 行 worker 租约）、`delivery.go:1`（601 行投递账）、`spawn_slot.go:1-109`、`mailbox.go`；`internal/appserver/turn_execution_lease.go:1`（421 行）、`thread_lifecycle_lease.go`；**hermes** `gateway/delivery_ledger.py:1`（564 行 claim/deliver/ack）、`agent/stream_delivery.py:1`（377 行） | 改造（取 claim-then-deliver + lease 形状，落 SQLite 单写者） | P8 已把"完整 claim/delivery_state 账本 = P9"写死（ADR-0021:8/14、ADR-0038:16/21）。**v1 = at-least-once + 去重键**（复用 ADR-0013 inbox `idempotency_key`）；投递/claim 视图**从事件重放重建、不落第二真相**（design/02 §10、C13/C15）。**跨机租约/DB 分布式锁 = C12 天花板，本 Phase 不越界**。 |
| **多前端 gateway / credential 池 / 后台审阅** | **hermes** `gateway/`（多前端面）、`agent/credential_pool.py:1`（3138 行，MIT）、`agent/subagent_lifecycle.py:286-290/442`（correlation/result_hash 去重键，P8 已引） | 参照（形状/判据，不搬整文件） | 本仓 BYOM 走 `providers/litellm_adapter.py`，P9 **不引入** credential 轮转/退避链（`retryable` 编排消费者仍归 P10，ADR-0028:74）。 |
| **OpenAI 入站 body 解析 / 非文本 part 拒** | **CowAgent** `channel/web/api/openai_compat.py:1`（请求校验/路由）、**OpenManus** `server/entrypoint` 形状；**本仓** `contracts/errors.py::classify_provider_error`（ADR-0028 纯分类器）、ADR-0036 决策 5 | 自写（本仓契约不兼容多模态：`ContentBlock` 仅 text/tool_use/tool_result，`全 src` 对 `voice|audio|tts|asr|vision|modalit` 零命中，ADR-0036:11） | 归一化拒绝**必须走 ADR-0028 同一错误分类器**（错误语义单一真源），surface 层 fail-fast；详见 §4 T7 与 ADR-0044。 |

> **结论**：P9 主复用源 = **CowAgent `openai_compat`（MIT）** 的 OpenAI chunk/finish_reason/[DONE]/错误外挂形状 + **DeepCode `plugins/host`（MIT）** 的 inert-discovery/原子注册/错误三分宿主形状 + **cordis（MIT）** 的注册-生命周期-隔离概念（**只取形状、不移植容器**）+ **wuu `worker_execution_lease`/hermes `delivery_ledger`（MIT）** 的 claim/deliver/ack 判据。OpenAI 投影、PolicyRegistry、能力热插拔宿主、claim/delivery 账本**均落本仓契约、不逐行照抄**（AGENTS §4.5 优先适配、ADR-0031 免署名）。

---

## 1. 目标与可验证判据（DoD）

- **进入条件**（ROADMAP §1 P9 行）：**P7**（桌面壳 sidecar，已合入 `b2361ff`）。P8 已合入（`090e5cb`），本 Phase 站在 P1–P8 全部接缝之上。
- **一句话目标**：① 本机 loopback 上的**任意外部 OpenAI-SDK 客户端**能用 `POST /v1/chat/completions` 驱动 questor（纯投影适配器）；② 策略/工具/技能/MCP **可热插拔、破损/panic 不崩内核**（cordis 式注册+生命周期，非远程 DI）；③ **接回 P8 后置**的跨进程 claim/delivery 账本（单机多进程）。

### DoD（可复现行为 + 判据；严格区分 已验证 / UNVERIFIED）

| # | 判据（可复现） | 验证方式 | 档位 |
|---|---|---|---|
| ① | 外部 OpenAI 客户端 `stream=true` 调 `/v1/chat/completions`：收 `chat.completion.chunk` 序列（首帧 role delta、`text_delta`→`choices[].delta.content`、`tool_*`→`tool_calls`、终态→`finish_reason`+`data:[DONE]`），`stream=false` 收聚合体；**经鉴权外部 API lane（API-key/bearer）与桌面 loopback 面均可调** | 集成：`httpx` 真打 `create_app` ASGI（脚本化 provider），断言 chunk 序 + `[DONE]` 唯一终结 + `finish_reason` 正确；**无/错 API-key → 401 fail-closed** | **已验证**（脚本化 provider） |
| ② | **OpenAI 面是投影适配器不是第二写者**：入站必转 `SubmitMessage`→**Command Inbox**（C16），出站只读 `bus.subscribe`；全仓无 `surfaces/*openai*.py` 直调 `reduce`/store | 源码级守卫 `check_layering_ast` FORBIDDEN_IMPORTS + 复用 `check_cross_run_no_bypass`（无 foreign `.run=`） | **已验证** |
| ③ | **非文本/语音 content part 归一化拒绝**：`image_url`/`input_audio`/`file`/语音类 part → 明确"provider 能力不支持" OpenAI error object（**不崩、不静默降级成纯文本继续跑**） | 判红集成：喂含 `image_url` 的 body → 断言 HTTP 400 error object、**run 未创建、无 durable 事件、无 traceback** | **已验证** |
| ④ | **能力热插拔不崩内核**：turn 循环中 `register`/`unregister` 一个工具/技能/MCP → 只在**下一次 `freeze_for_run`** 生效、活 run 面不变、发 `tools_changed`；插件 `init`/`propose_action` 抛错 → **被熔断捕获、WARN、内核继续**（C10） | 单元（注册冲突 first-writer-wins 既有）+ 集成：跑 run 中途热插工具断言面稳定；注入抛错插件断言 run 不崩、发 error/warning | **已验证** |
| ⑤ | **PolicyRegistry 错误二分 + fail-open**：id 写错→`UnknownPolicyError`（附名册）；加载破损→`BrokenPolicyError`（**留名不静默消失**）；目标不可用→**回落默认策略 + WARN，run 照样起**（绝不让 run 起不来，C10） | 单元：三条判红（Unknown/Broken/fail-open），断言降级后 run 仍 `run_started` 且带默认 `policy_ref` | **已验证** |
| ⑥ | **热替换 = 新 run 快照冻结、活 run 不 mid-swap**（ADR-0009）+ **A/B 按 `fingerprint` 路由**：`run_started` 带 `policy_ref{id,fingerprint}`（additive、不 bump `v`）；换 registry 内容只影响新 run | 集成：改 registry 后既有 run 的 loop 不变、新 run `policy_ref` 反映新 snapshot；同 fingerprint 落同桶（确定性 fixture） | **已验证** |
| ⑦ | **跨 run 子代际 claim/delivery 幂等 + 单机多进程单写者**：`ReportChildTerminal`/投递配**稳定投递 id**、claim-then-deliver-then-ack；同投递 id 二次 ack = no-op；run 租约防两进程双驱（`BEGIN IMMEDIATE`） | **两真 OS 子进程共享一套 SQLite** 集成（Windows 本机跑）+ 单元：同键二次 claim 判重、租约 epoch 防双驱；投递视图从事件重放重建（无第二真相，C13） | **已验证（单机多进程，两真子进程）**；**跨机故障切换 = UNVERIFIED（C12 天花板）** |
| ⑧ | **协议只增不破**：`EVENT_SCHEMA_VERSION=1` **不动**；`run_started.policy_ref`、`tools_changed` 为 additive；OpenAI wire 是**另一契约**（独立 schema），不塞进 questor `event.schema.json` | `check_protocol_schema --check/--self-test` 绿 + 新 `check_openai_compat_schema --self-test` 能判红 | **已验证** |
| — | 真 LLM 驱动 OpenAI 面 / 真远程网络暴露 / 真双进程跨机 exactly-once / 真窗口 | —— | **UNVERIFIED，不冒充**（本机 loopback + 脚本化 provider；网络暴露与跨机属 C12/后续 ADR，见 §2） |

---

## 2. 本 Phase 不做（范围纪律，防过度工程）

1. **P10 全量后置**：可恢复压缩**生产者**、评测回归网（evals 任务级）、observability **刀 3**（追踪面板 / `questor logs` 消费命令 / OTel / `--log-payload` preview 实装）均不做。
2. **跨机 / 分布式**（C12 天花板）：不做跨主机排序/租约/分布式 consensus/部分失败恢复。**桌面 sidecar 仍 loopback-only（ADR-0032 原样不动）**；**但 P9 新增一条并行、独立的鉴权外部 OpenAI API lane**（可 opt-in 非 loopback bind + 强制 API-key/bearer fail-closed + 保守权限，ADR-0043 对 ADR-0032 分道 scoping）；**跨机 = 天花板不做**。
3. **不把业务/校验下沉 Shell**（C14）：OpenAI 面只"收 Command + 投事件"，参数 schema 校验/权限/沙箱仍在 Harness；入站的多模态拒是**协议级输入校验**（在适配器边界、非状态写），不新立第二套业务。
4. **不把 OpenAI 兼容做成第二写者或第二事件真相**（C2/C13/C15/C20）：`event_log` 仍只存内部事件；OpenAI SSE 是运行时投影、不入库、不 `log_envelope` 逐消费者双投（承 ADR-0033 / pitfalls #5）。
5. **不引 cordis TS 容器、不为远程/微服务提前序列化一切**（C12）：`PolicyView/PolicyIntent` 保持纯 frozen 数据即止，v1 不引入任何 RPC/传输（ADR-0009 决策 3）。
6. **不做 credential 轮转/退避/fallback 链**（ADR-0028:74 归 P10）：`run_failed.error.retryable` 已供客户端决策，本 Phase 不自动重试。
7. **不"顺手把 P6 多模态加回来"**（ADR-0036 整阶段移除）：只落**归一化拒绝**这一条硬判据，不新增任何 vision/ASR/TTS provider。
8. **不动工具级 reader/writer gate / 真并发派发**（ADR-0039 后置）：热插拔是 run 级 freeze，与并行 gate 正交。

---

## 3. 前置 ADR 门（ADR-0043 起；**ADR 未落册则对应子任务不许开工**）

> 依 ROADMAP §5 + AGENTS §5.5：**协议/状态扩面 · 新对外契约 · 跨阶段账本落地**属难回退决策，先 ADR 后文档。编号从 **0043** 起（0042 已被 P8 占用）。下表即"7 个真矛盾"的裁决落点。

| ADR | 标题（拟） | 裁决内容 | 守住的点 | 阻塞子任务 |
|---|---|---|---|---|
| **0043** | OpenAI 兼容 = 投影适配器（wire 单一真源 + 映射表 + 断连即取消 + 独立鉴权外部 API lane） | 定死：① 入站经 `SubmitMessage`→Command Inbox（C16），出站只读 `bus.subscribe` 投 OpenAI SSE（映射表见 §4.2）；② **OpenAI wire 单一真源 = 独立 `protocol/openai_compat.schema.json` + `contracts/openai_wire.py` 数据类**，**questor `event.schema.json` 不承载 OpenAI 形状、`v` 不 bump**；③ 标准字段走 OpenAI 语义、专有进 `x_questor`；④ **无原生续传 = 断连经 inbox 提 `Cancel`、不假装 resume**；⑤ 内核三终态（completed/cancelled/failed）不因兼容面简化；⑥ **独立"鉴权外部 OpenAI API lane"**（区别于桌面 sidecar loopback bootstrap 面）：可对算子配置 **opt-in 非 loopback bind + 强制 API-key/bearer fail-closed**（密钥绝不入库/进事件/进日志，C20/ADR-0019）、非 loopback 建议 TLS；**桌面 sidecar `--serve` 的 loopback 红线（ADR-0032）原样保留**、本 lane 是其**并行第二面（分道 scoping、非推翻 ADR-0032）**；⑦ **安全硬边界**：经本 lane 起的 run 采保守权限默认（`permission_mode=default`、`ask` 工具**超时 fail-closed deny**——外部无审批通道不得自动放行、lane 工具 capability floor 默认收窄，承 C17） | C2/C13/C14/C15/C16/C17/C20 · ADR-0007/0032(分道scoping)/0033 · design/02 §9 X5/§10 | T2/T6/T7/T9 |
| **0044** | 非文本/语音 content part 归一化拒绝（P9 硬判据，承 ADR-0036 决策 5） | `image_url`/`input_audio`/`file`/语音 part → **surface 层 fail-fast 返 OpenAI error（不起 run、不崩、不降级）**；defense-in-depth：若经中间/工具路径到达 `_stream_turn`，走 **ADR-0028 `classify_provider_error` 同一分类器**归一 `run_failed`；README/VISION 能力叙述改诚实"仅文本模态"。**契约 additive**：`contracts/errors.py::ErrorKind` 增 **`UNSUPPORTED_MODALITY="unsupported_modality"`**（现 enum 无此项、400 原落 `FORMAT_ERROR`；ADR-0036 决策 5 要"明确能力不支持"故单列一等 kind，`retryable=False`；属稳定命名空间增量、走本 ADR、不破既有 kind） | ADR-0036 决策 5 · ADR-0028 · C19/C14/C6 | T7 |
| **0045** | PolicyRegistry 落地 + `run_started.policy_ref`（状态/协议 additive + AB 分桶） | ① `PolicyRegistry`（L4 `policy/registry.py`，进程内纯结构）：条目 `{id, factory, trust(system\|user\|project), broken?}`、trust 优先级 project>user>system、错误二分（`UnknownPolicyError` 附名册 vs `BrokenPolicyError` 留名）、**fail-open 回落默认+WARN**（C10）；② **发现边界钉死 = 组合根注册固定名册，无磁盘扫描/HMR**（防过度工程）；③ `Run` 增 additive `policy_ref{id,fingerprint}`、`run_started` data 增 optional `policy_ref`（**不 bump `v`**，先 schema→代码→codegen）；④ **A/B 分桶算法定死**（design/05 §6 待定项）：`bucket = stable_hash(fingerprint) % n` + 算子可覆写的显式 split 表；⑤ 热替换/AB **装配接缝落在 surface/组合根解析后注入 `PolicyPort`**（loop 仍只认注入端口，C1；语义承 ADR-0009 不重决） | C1/C6/C11/C12 · ADR-0009 · design/05 §2/§3/§6 | T1/T2/T3/T4 |
| **0046** | 能力热插拔宿主（**薄生命周期 + 熔断隔离，非 cordis 容器**） | ① 定义 `PluginLifecycle` 协议（`id`/`init()`/`teardown()`）+ `PluginHost` 编排器：register/deregister 统一走**已存的 tools/skills/mcp 注册点**，只加"每插件调用一律包 try/except 熔断护栏 → 捕获、WARN/error 事件、内核继续"（C10）；② 热更只影响下一次 `freeze_for_run`、活 run 面不变（承 `tools/registry.py:97-104` 现成语义）；③ **`tools_changed` additive 事件**（design/02 §7 预留名转已定义，`data.domain ∈ {tools,skills,mcp,plugins,settings}`）；④ **不引 cordis Fiber/Reflect、不为远程序列化**（C12）；inert-discovery 纪律借 DeepCode `host.py:44-49`（发现≠执行）；⑤ 宿主落层定死（`capabilities/_host` 或新 `plugin_host/`，见 §4.1），`check_layering_ast` 许可 | C1/C10/C12/C14 · design/00 横向 DI · design/02 §7/§10 · ADR-0036 | T1/T5/T9 |
| **0047** | 跨进程 exactly-once claim/delivery_state 账本 + 单机多进程 run lease（接回 ADR-0021/0038 后置；**全局最优可演进底座**） | ① `StorePort` **纯增量**扩展（不破签名/信封/关联键，C6）：`claim_delivery/delivery_state/ack_delivery`（claim-then-deliver，投递视图**从事件重放重建、不落第二真相**，C13/C15）+ `acquire_lease/renew_lease/release_lease`（`{run_id, holder_epoch, ttl}`，靠 SQLite `BEGIN IMMEDIATE` 单写者）；② `ReportChildTerminal`/`peer_ended` 投递配**稳定投递 id**（承 design/02 §10 投递幂等、ADR-0011）；③ 孤儿子对账复用现成 `list_unfinished_runs()`/`watermark()`（ADR-0022）；④ **接口按"未来跨机 = 换后端非重构"设计（全局最优、为后续大扩展铺路），但本 Phase 不实现跨机**（C12 天花板）；⑤ **用两真 OS 子进程共享一套 SQLite 端到端验单机多进程**（本机 Windows 可跑）→ DoD⑦ 升 **"单机多进程 = 已验证"**、**跨机 = UNVERIFIED**；与 ADR-0043 咬合：**鉴权外部 API lane 若作独立进程跑 = 本 run-lease 防双驱的首个真实单机多进程消费者**；v1 语义 = at-least-once + 去重键（`idempotency_key`） | C2/C12/C13/C15/C16 · ADR-0011/0013/0021/0022/0038 | T8 |

> **T0 = ADR 门**：ADR-0043~0047 全部落册（可先 draft、随实现转正）后，T1 起才允许动代码。缺 ADR 的子任务视为未就绪。

---

## 4. 子任务分解（T0…Tn；每条配判红用例，先红后绿）

> **真依赖点名（承 ADR-0029 教训："字段存在 ≠ gate 存在"）**：`Run.policy_ref` **字段存在** ≠ A/B **路由门存在**（必须有 registry 解析 + 分桶消费者）；`tools_changed` **type 存在** ≠ **emit 生产者存在**（必须真在 register/deregister 处发）；OpenAI **wire schema 存在** ≠ **投影适配器存在**（必须真订阅 bus 并映射）；`claim_delivery` **方法存在** ≠ **崩溃一致性接入**（必须真在 `ReportChildTerminal` 投递路径上 claim-then-deliver）。每条 T 的判据必须**绑定到消费者被接通**，不接受只加字段/加桩。

| T | 目标 | 涉及层 | 依赖 | 验证方式（含判红） | commit 粒度 |
|---|---|---|---|---|---|
| **T0** | ADR-0043~0047 落册（draft）+ 就地修订 `design/02 §3`（run_started 增 policy_ref）、`§7/§10`（tools_changed 转已定义）、`design/05 §2/§3/§6`（registry 落地 + AB 分桶定死）；登记并**核对 `HARD-CONSTRAINTS.md` 现场数 = C1–C20**（见 §5 顺带发现） | docs | — | 文档自检 + ROADMAP §5 口径一致 | `docs(adr): open ADR-0043..0047 for P9 openai-compat + plugin host` |
| **T1** | 契约 additive：`contracts/policy.py` 加 `PolicyRef{id,fingerprint}` 值对象（frozen）+ `PolicyRegistry` 所需 `trust` 枚举；`contracts/state_schema.py` `Run` 加 optional `policy_ref`（**默认 None=不破坏既有快照 round-trip**）；`kernel/events.py` `EXTERNAL_EVENT_FIELDS[RUN_STARTED]` 加 `policy_ref`、新增 `EventType.TOOLS_CHANGED`（domain + 计数白名单；**live-only：入 `LIVE_ONLY` 集、不占 durable seq、不入库**，承 C13/design-02 X2） | L0/L2 | T0 | 冷导入 + `check_protocol_schema`（暂缺 schema→预期红，T2 补）+ checkpoint round-trip（旧快照无 policy_ref 仍可读） | `feat(contracts): additive PolicyRef, Run.policy_ref, tools_changed` |
| **T2** | wire 单一真源：① `protocol/event.schema.json` `run_started.$defs` 加 **optional** `policy_ref` 对象、`enum`+`$defs`+`if/then` 加 `tools_changed`；重生成 TS codegen；② **新建 `protocol/openai_compat.schema.json`**（chat `request` + `chat.completion.chunk` + error object，**独立契约**）+ `contracts/openai_wire.py`（请求/choice/chunk/error 数据类 = Python 侧权威形状） | L0/protocol | T1 | `check_protocol_schema --check` 绿 + `--self-test`；`check_openai_compat_schema`（T9 落，此处先建被其读取） | `feat(protocol): run_started policy_ref + tools_changed + openai_compat wire schema` |
| **T3** | **`PolicyRegistry`（L4 `policy/registry.py`）**：`register(entry)`/`resolve(policy_id, bucket_key)->PolicyPort`；trust 优先级 project>user>system、最近根覆写重名；`UnknownPolicyError`（附名册）vs `BrokenPolicyError`（附 reason、**留名不静默消失**）；**fail-open**：目标不可用→回落默认+WARN（C10，run 必起）；**AB 按 fingerprint 分桶**（ADR-0045 算法）；纯进程内、无磁盘 IO、kernel 不 import 它 | L4 | T0/T1 | 单元（DoD⑤三判红 + DoD⑥ 分桶确定性）；`check_layering_ast`（registry ✗ providers/surfaces） | `feat(policy): in-process PolicyRegistry (trust/errors/fail-open/AB-fingerprint)` |
| **T4** | 装配接缝：`surfaces/cli.py:133`（现硬编码 `ReActPolicy()`）改为**经 `PolicyRegistry` 解析**（默认 id 可 config/env 覆写）→ 注入 `DefaultTurnLoop(policy=...)`（loop 仍只认 `PolicyPort`，C1）；run 创建时把解析到的 `PolicyRef` 写入 `Run` → `reduce.py:191` 处 `run_started` data 带出 `policy_ref`；**热替换 = 新 run snapshot、活 run 不变** | L4/L6/L1 | T1/T3 | 集成（DoD⑥：改 registry→新 run 用新 snapshot、活 run loop 不变；run_started 带 policy_ref） | `feat(surfaces,reduce): resolve policy via registry, snapshot policy_ref into run_started` |
| **T5** | **能力热插拔宿主**（`capabilities/_host.py` 或新 `plugin_host/`，ADR-0046 定层）：`PluginLifecycle` 协议（id/init/teardown）+ `PluginHost`（register/deregister 统一调**已存** tools/skills/mcp 注册点；每次插件调用包**熔断护栏**→异常捕获、WARN/`tools_changed`/error、内核继续；inert-discovery：发现不执行） | 横向(L3/组合根) | T0/T1 | 集成（DoD④：跑 run 中热插工具→面稳、发 tools_changed；注入 panic 插件→不崩）+ 单元 | `feat(capabilities): plugin host with init/teardown lifecycle + fault isolation breaker` |
| **T6** | **OpenAI 兼容投影面 + 鉴权外部 API lane**（L6）：在 `create_app`/`EventServer` 挂 `POST /v1/chat/completions`；入站解析 body → 校验（非文本→T7）→ 末条 user text 转 `SubmitMessage` 经 **inbox**（C16，禁直 reduce）起 run；出站 `bus.subscribe(run_id)` → **映射表**（§4.2）投 OpenAI chunk；标准字段 OpenAI 语义、专有进 `x_questor`；**断连→经 inbox 提 `Cancel`、不假装 resume**；**不新增 bus observer/log_envelope**（复用 `EventServer` 单条投影，ADR-0033）；载荷走有界 preview/artifact_ref（C18）。**鉴权外部 lane**：独立 serve 入口（如组合根 `--serve-openai`，区别于 sidecar `--serve`）+ **API-key/bearer fail-closed（无/错 key→401、密钥不入库/进日志 C20）**+ 保守权限默认（承 ADR-0043⑥⑦）；非 loopback bind 为算子 opt-in | L6/组合根 | T0/T2/T4/T7 | 集成（DoD①②③⑧：httpx 真打 ASGI、chunk 序、[DONE]、断连取消、投影不外泄全文；**无/错 key→401 fail-closed、密钥不落盘 grep canary**）+ 源码守卫 | `feat(surfaces,composition): OpenAI-compat adapter + authenticated external API lane`（可拆两子提交：核心投影 / 鉴权 lane） |
| **T7** | **非文本/语音归一化拒绝**（surface fail-fast + 归一 defense-in-depth）：OpenAI 面解析 content part，遇 `image_url`/`input_audio`/`file`/语音 → **不起 run、HTTP 400 返 `{error:{type:"invalid_request_error",code:"unsupported_modality",message:"provider capability not supported: <type>"}}`**（复用 `contracts/errors.py::classify_provider_error` 做单一错误语义；OpenAI-wire `error.code` 是适配器作用域字符串、非 questor `ErrorKind`）；defense-in-depth：若多模态块经中间/工具路径到 `_stream_turn` → ADR-0028 归一 `run_failed`（新增 additive `ErrorKind.UNSUPPORTED_MODALITY`）；README/VISION 诚实"仅文本模态" | L6/L0/docs | T0/T2 | **判红**（DoD③）：喂含 `image_url` 的 body → 断言 400、run 未创建、无 traceback、无 durable 事件；defense-in-depth 单元：构造达 `_stream_turn` 的多模态块 → `classify_provider_error` 归 `ErrorKind.UNSUPPORTED_MODALITY`（新增 additive kind）`run_failed`、不可重试 | `feat(surfaces): normalize-reject non-text content parts + additive ErrorKind.UNSUPPORTED_MODALITY (ADR-0036 gate)` |
| **T8** | **接回 P8：claim/delivery 账本 + 单机多进程 run lease**（L5 `providers/store_sqlite` + `contracts/ports.py` additive）：StorePort 加 `claim_delivery/delivery_state/ack_delivery` + `acquire/renew/release_lease`（`{run_id,holder_epoch,ttl}`）；`SubagentOrchestrator` 的 `ReportChildTerminal` 投递路径**真接** claim-then-deliver + 稳定投递 id；投递视图从事件重放重建、`_SCHEMA` 幂等 `IF NOT EXISTS`、未知版本 fail-closed；**跨机不做**（C12），at-least-once+去重键诚实 | L5/L0/L6 | T0/（承 P8 ADR-0038） | 单元（DoD⑦：同投递 id 二次 ack no-op、lease epoch 防双驱）+ 集成 tmp_path SQLite | `feat(providers,ports): claim/delivery_state ledger + single-host run lease` |
| **T9** | 守卫扩面：新建 `scripts/check_openai_compat_schema.py`（OpenAI wire drift 门：mapping 表引用的 questor type ⊆ `EventType`、wire schema 良构、**拒未知 content part**、`--self-test` 能判红、fail-on-empty）；`check_protocol_schema --self-test` 加 `run_started.policy_ref` + `tools_changed` valid/bad；`check_layering_ast` FORBIDDEN_IMPORTS 加 OpenAI surface ✗ `state.reduce`/store、`plugin_host` ✗ 外呼；`check_projection_whitelist` 确认 `policy_ref`/`tools_changed` 正文不入 `_DATA_KEYS`（C20）；`check_thin_client` 若 OpenAI 面生 TS 客户端则扩 | scripts/L* | T1–T8 | 各脚本 `--self-test` 判红 + `check` 判绿 + fail-on-empty | `test(gates): openai_compat drift gate + protocol/layering/projection扩面` |
| **T10** | 集成回归（DoD 全条）：`test_p9_openai_e2e`（真打 ASGI 流式/聚合、finish_reason、[DONE]）；`test_p9_disconnect_cancels`（断连→run_cancelled、不 resume）；`test_p9_non_text_rejected`（判红）；`test_p9_policy_registry_errors`（Unknown/Broken/fail-open）；`test_p9_hot_swap_new_run` + `test_p9_ab_fingerprint`；`test_p9_hotplug_tool_stable` + `test_p9_plugin_panic_breaker`；`test_p9_claim_delivery_idempotent` + lease 防双驱；`test_p9_out_of_band_projection`（承 pitfalls #5：OpenAI 订阅者不双投，每 seq 恰一行） | tests | T1–T9 | pytest integration + 真文件 canary | `test(integration): P9 openai + policy registry + hotplug + claim/delivery DoDs` |
| **T11** | 文档收尾（活文档，AGENTS §5.5）：`design/02 §3` run_started+policy_ref、`§7/§10` tools_changed；`design/05 §2/§6` registry 落地口径；`ROADMAP §1`(P9 DoD 落定)/`§1.5`(P9 备注：非文本拒 + claim/delivery 落地)；`CHANGELOG [Unreleased]`；`plugin_host`/`surfaces` README；README/VISION 仅文本模态诚实；ADR-0043~0047 转正 | docs | 全部 | 文档自检 | `docs(p9): sync design/02,05 + ROADMAP §1.5 + CHANGELOG + capability honesty` |

> **开工次序**：T0 → (T1→T2) → T3 → T4 → (T7) → T5 → T6 → T8 → T9 → T10 → T11。每条 T 内部按 TDD：**先写判红用例跑红 → 最小实现转绿 → 过冷导入/守卫 → 提交**（AGENTS §4/§5、细粒度原子提交）。

### 4.1 宿主落层与依赖方向（评审须钉，实现者不得再自行决策）

- **`PolicyRegistry` 落 L4 `policy/`（rank 4）**：只 import `contracts`（L0）；kernel（L2）**绝不 import 它**——loop 只认注入的 `PolicyPort`（`loop.py:50/229`），registry 的解析发生在 **surface/组合根（L6/组合根）**，与 `ReActPolicy()` 现装配点同处（`cli.py:133`）。`check_layering_ast` 守（policy rank 4 不得 import providers(5)/surfaces(6)）。
- **`PluginHost` 落 `capabilities/_host.py`（L3, rank 3）或新 `plugin_host/` 横向**：只能 import `contracts` + 各能力注册表；**不 import surfaces/providers 具体实现**；熔断护栏不吞 `CancelledError`/`SystemExit`（承 `loop.py:389-395` + ADR-0028 BaseException 纪律）。ADR-0046 定层，`--self-test` 的 `check_layering_ast` 兜底。
- **OpenAI 面不新增写路径**：只 `registry.submit(run_id, SubmitMessage, source="openai", idempotency_key=…)` + `bus.subscribe`；`check_cross_run_no_bypass` 拦 foreign `.run=`；`EventServer` 已挂的**唯一** `log_envelope` observer（`http_sse.py:76`）被复用，OpenAI 端点**绝不再调** `log_envelope`（ADR-0033 / pitfalls #5）。

### 4.2 OpenAI 事件 → chunk 映射表（ADR-0043 落地，design/02 §10）

| questor 外部事件 | OpenAI wire | 说明 |
|---|---|---|
| `run_started` | 首帧 `{delta:{role:"assistant",content:""}}` | `policy_ref` 等非 OpenAI 标准字段进 `x_questor`（不外泄内部 id 除非必要） |
| `text_delta.data.delta` | `{delta:{content:<delta>}}` | live-only，不入库；`x_questor.seq` 可选 |
| `reasoning_delta` | `{delta:{reasoning_content:<delta>}}` | 承 CowAgent `:438-445`；或收 `x_questor` |
| `tool_started`(name/args_summary) | `{delta:{tool_calls:[{index,id,function:{name,arguments 分片}}]}}` | questor `tool_call_id`→OpenAI `tool_calls[].id`；按 index 归组 |
| `tool_completed`(status/preview/artifact_ref) | 续 `tool_calls` 或 `x_questor.tool_status` | **不塞全文**（C18/ADR-0019），只有界 preview/指针 |
| `run_completed` | `{delta:{},finish_reason:"stop"}` + `data:[DONE]` | 内核仍落 `run_completed`（三终态不简化） |
| `run_cancelled` | `{delta:{},finish_reason:"stop"}`(或 `x_questor.cancelled`) + `data:[DONE]` | 断连即取消，无续传 |
| `run_failed` | 末帧 `finish_reason` + `{error:{type,code,message,retryable}}`(或 `x_questor.error`) + `[DONE]` | **错误编进 finish_reason**（design/02 §10）；非文本→`code:"unsupported_modality"` |
| 非文本/语音 part（入站） | HTTP 400 `{error:{code:"unsupported_modality"}}` | **不起 run**（T7/ADR-0044），defense-in-depth 才落 `run_failed` |

---

### 4.3 对抗式评审收口记录（Phase 2 开工前，两路；Blocker/Major 已全关）

> 本 Phase 产物是计划文档（非代码），CodeReview 子代理仅适用代码变更，故两路对抗评审**由规划者 inline 执行**并留痕；进入实现后每条 T 的判红/判绿 + 守卫 `--self-test` 是后续机械复核。

**路①（契约完备性/不变式破坏）— 发现与收口：**
- **M1（Major）`tools_changed` 发射语义**：若当 durable，能力增删发生在 loop 之外、且 `freeze_for_run` 已固定活 run 面 → 会陷入"要么违 reduce-purity（host 直 `bus.emit` durable）、要么无 run 可挂"。**收口**：`tools_changed` 定为 **live-only 告警**（入 `LIVE_ONLY`、不占 durable seq、不入库），由 **loop 自身**在检测到能力名册 `generation` bump 后的安全点发一条，通知外部观察者"名册已变、下次 freeze 生效"；活 run 面**不变**、host 只 bump `generation` 不碰 bus（避免第二发射者）。已写进 T1/T5。
- **M2（Moderate）`--resume` 的 `policy_ref` 冻结**：ADR-0009 要求"整 run 同一份"，`rebuild_run` 须从快照**恢复**创建时冻结的 `policy_ref`、**绝不重新解析 registry**（否则活 run 被换策略撕裂）。收口：T4 补判据——resume 后不重发 `run_started`（`was_idle=False`）、恢复的 `Run.policy_ref` == 崩溃前快照值；`check_replay_determinism` 加含 `policy_ref` 的 fixture。
- **I1（Info）状态 additive schema 版本**：`Run` 加 `policy_ref` 后 `snapshot`/`from_snapshot` 须容忍缺字段（旧快照读得出、默认 None），`store_schema_version` 不因此破坏性升版——已由 T1 "旧快照无 policy_ref 仍可读" 覆盖。

**路②（范围漂移/安全边界/第二写者/载荷外泄/热插拔稳定性）— 发现与收口：**
- **S1（安全·Major）鉴权外部 lane 的权限面**：OpenAI wire 无审批通道 → 若降为 allow 即"外部进程无 HITL 驱动高危工具"。收口：本 lane 起 run **`permission_mode=default` + `ask` 超时 fail-closed deny + lane 工具 capability floor 默认收窄**（C17）；写/执类默认不因"外部可调"放行。已写进 ADR-0043⑦/T6/§5 C17/C9。
- **S2（第二写者/第二真相）外部 lane 作独立进程**：与桌面 sidecar 共享 SQLite 时若同 run_id 双驱 → 靠 T8 run-lease（epoch 单写者）拦；OpenAI 入站仅经 inbox 提 Command（C16）。DoD⑦/§5 C2 覆盖。
- **S3（载荷外泄）密钥/正文**：API-key 绝不入库/进事件/进日志（真文件 grep canary，pitfalls #1/C20）；OpenAI `tool_calls`/投影只带界 preview/artifact_ref（C18/ADR-0019）。T6/T9/§6 覆盖。
- **R1（范围）防过度工程**：cordis 只取形状不移植容器（ADR-0046）；发现=组合根固定名册无磁盘 HMR（ADR-0045）；跨机 claim/lease 天花板不做（C12）。§2/§7 覆盖。

**结论**：M1/M2/S1/S2/S3/R1 均已在 §1 DoD / §3 ADR / §4 T / §5 自检 / §6 守卫就地收口，无未决 Blocker/Major → **满足开工前置门**。

---

## 5. 契约与红线自检（逐条 C1–C20，**现场数以 `HARD-CONSTRAINTS.md` 为准 = 20 条**）

| 红线 | 合规判定 | 说明 / 例外（需 ADR） |
|---|---|---|
| **C1** 分层依赖方向 | 合规 | OpenAI 面 L6、PolicyRegistry L4、PluginHost L3/横向、claim/delivery L5+L0；kernel 不 import policy 具体/surfaces；`check_layering_ast` 扩 FORBIDDEN_IMPORTS（T9） |
| **C2** 单写者+不可变视图 | 合规（核心） | OpenAI 入站只经 Command Inbox 改状态；出站只读投影；投递/claim 视图从事件重放重建、不反哺状态 |
| **C3** 视图 vs 快照 | 合规 | 无每轮全量深拷；`run_started` snapshot 语义承 ADR-0020 |
| **C4** Store 读写过接口 | 合规 | registry/host/策略/OpenAI 面均经注入 Port；不持裸句柄 |
| **C5** Command/Event 分离 | 合规 | SubmitMessage=Command、OpenAI chunk=Event 投影；Event 不反哺状态 |
| **C6** 事件内外分层+版本 | 合规 | `policy_ref`/`tools_changed` additive、**`v` 不 bump**（ADR-0045/0046）；OpenAI wire 是**另一契约**（独立 schema） |
| **C7** 终止权在 Harness | 合规 | 断连→`Cancel` Command（经 inbox）非硬杀；三终态不简化 |
| **C8** 工具执行边界 | 合规 | OpenAI `tools` 入站映射 ProviderRequest，校验/权限仍在 Harness；宿主热插不改校验链 |
| **C9** 权限三态一等 | 合规 | OpenAI 面无需审批旁路：`ask` 经 `approval_request` 投影为 `x_questor`（外部客户端不自动批准，fail-closed 超时 deny 既有） |
| **C10** 故障隔离 | 合规（P9 核心） | 插件 panic→熔断捕获、内核继续（T5）；BrokenPolicy→留名+fail-open 默认（T3）；子/OpenAI provider 崩→归一 `run_failed`（ADR-0028） |
| **C11** 状态谨慎演进 | 合规（例外走 ADR） | `Run.policy_ref` 是 additive 且 ADR-0009 早已承诺 run 内快照冻结 policy_id+fingerprint → 属"字段接上消费者"非新接缝（ADR-0045） |
| **C12** 远程/分布式预留非现在 | 合规 | 进程内 registry、无 RPC/序列化（ADR-0009 决策 3）；**桌面 sidecar loopback-only（ADR-0032 原样保留）**；**鉴权外部 API lane = ADR-0043 对 ADR-0032 分道 scoping、强制 fail-closed 鉴权+保守权限**；跨机 claim/lease 天花板不做（§2-2） |
| **C13** 存储/终态两铁律 | 合规 | OpenAI SSE 运行时投影不入库；每 run 恰一终态（first-writer-wins `_closed`）；claim/delivery 从事件重建非第二真相 |
| **C14** 结构性边界机器守 | 合规 | OpenAI/CLI/HTTP 只"收 Command+投事件"；Python↔Rust 仍 HTTP+SSE；每条守卫 `--self-test`+fail-on-empty |
| **C15** 外部契约单一真源+守卫可信 | 合规 | ① questor `event.schema.json`⟂`EventType`⟂`EXTERNAL_EVENT_FIELDS`⟂TS codegen 三/四处 lockstep（`check_protocol_schema`）；② **OpenAI wire 新独立单一真源** `openai_compat.schema.json`+`contracts/openai_wire.py`⟂`check_openai_compat_schema`（漂移判红） |
| **C16** Command Inbox 唯一外部写入口 | 合规（核心） | OpenAI/IM/远程只 `submit(SubmitMessage/ResolveApproval/Cancel,…)`；**禁直 reduce/store/权限**（DoD②源码守卫）；claim/delivery 经 reduce 记账 |
| **C17** PermissionCtx/floor 优先于 mode | 合规（P9 安全重点） | OpenAI/外部 lane 不引入提权旁路；full_auto 不越 capability floor；**鉴权外部 lane 默认收窄工具 floor、`ask` 超时 fail-closed deny**（承 ADR-0043⑦） |
| **C18** ToolCall 生命周期+载荷有界 | 合规 | OpenAI `tool_calls` 投影携 `tool_call_id` 配对；正文走 preview/artifact_ref（ADR-0019），不内联全文 |
| **C19** 回发前配对+provider 故障不崩 | 合规 | 关卡仍在唯一 `provider.stream` 调用点（`loop.py::_stream_turn`）；非文本 defense-in-depth 走此归一，绝不穿出 turn 循环；**OpenAI provider 调用点复用同一关卡**（不新立裸 `.stream(`） |
| **C20** 观测面不作第二载体 | 合规 | OpenAI 面**不新增** `log_envelope`（复用 `EventServer` 单条 observer）；`policy_ref`/`tools_changed`/OpenAI 载荷不进 `projection._DATA_KEYS`；每 seq 恰一行（承 pitfalls #5） |

**事件协议"只增不破信封/关联键/终止序"核验**（design/02 §0/§6/§7）：
- 信封 `{v,seq,run_id,turn?,ts,type,data}` **不动**；关联键 **不改名**（`policy_ref` 是 `run_started.data` 内嵌对象、非新关联键）。
- **终止序不破**：`run_cancelled` 先于 `run_completed`、一轮恰一终态；`tools_changed`/`policy_ref` 非终态事件。
- `v=1` **不 bump**（additive；`check_protocol_schema` 断言 enum==$defs==branches==contracts 白名单键集）。
- **OpenAI wire ≠ questor 事件契约**：wire 形状只在 `openai_compat.schema.json`/`contracts/openai_wire.py`，questor `event.schema.json` 不收 OpenAI 字段（矛盾 #2 裁决）。

> **顺带发现（不属本 Phase、仅登记，承 ADR-0036 记账范式）**：`capabilities/tools/registry.py:36/63` 注释引用 `C08 单一真源`/`C21 命名冲突守卫`，但 `HARD-CONSTRAINTS.md` 现场只有 **C1–C20**（无 C21，"C08"亦非文内措辞）。属早于本决策的注释-文档漂移：命名冲突守卫实质由 **C17 capability floor** 覆盖、单一真源由 **C15** 覆盖。**T0 顺带核对**，但**不新增 C21**（不为本 Phase 造红线）、**不回改** registry.py 逻辑（属代码改动、越界）；若转正需独立 ADR。普通 bug 走 Issue（AGENTS §5.5）。

---

## 6. 测试与守卫扩面

**单元**
- `PolicyRegistry`：Unknown（附名册）/Broken（留名、不静默）/fail-open 回落默认+WARN run 仍起（DoD⑤）；trust 优先级 project>user>system；AB 分桶同 fingerprint 确定性落同桶（DoD⑥）。
- PluginHost：register/deregister 只影响下一次 freeze；插件 `init`/`propose_action` 抛错→熔断捕获、发 error/warning、内核继续（DoD④）；不吞 `CancelledError`。
- OpenAI 映射纯函数：`text_delta`→`delta.content`、`tool_started`→`tool_calls`、`run_failed`→error in `finish_reason`、`[DONE]` 唯一终结。
- 非文本 part：`image_url`/`input_audio`/`file`/语音各一条判红 → `classify_provider_error` 归 additive `ErrorKind.UNSUPPORTED_MODALITY`（DoD③）。
- claim/delivery：同投递 id 二次 claim/ack 幂等；lease `holder_epoch` 防双驱；未知 `store_schema_version` fail-closed。

**集成（真打 ASGI，脚本化 provider）**
- `test_p9_openai_e2e`：`httpx`→`create_app`，断言 chunk 序 + `finish_reason` + 唯一 `[DONE]`；`stream=false` 聚合体。
- `test_p9_disconnect_cancels`：客户端中途断 SSE → 服务端经 inbox 提 `Cancel` → run 落 `run_cancelled`、**不提供 after_seq 续传**（不假装 resume）。
- `test_p9_hotplug_and_panic`：跑 run 中 `register`/`unregister` 工具 → 活 run 面不变、下一 freeze 生效、发 `tools_changed`；注入 panic 插件 → run 不崩（DoD④）。
- `test_p9_hot_swap_new_run`：换 registry → 活 run loop 不变、新 run `run_started.policy_ref` 反映新 snapshot（DoD⑥）。
- `test_p9_claim_delivery_idempotent`：`ReportChildTerminal` 投递 claim→deliver→ack；崩溃重放同投递 id 不双回灌；孤儿 `list_unfinished_runs` 检出（DoD⑦）。
- `test_p9_out_of_band_projection`（承 pitfalls #5）：同 run 开 **CLI+SSE+OpenAI** 三消费者，主干日志每 seq **恰一行**（OpenAI 面不双投）。

**守卫扩面**（`--self-test` 必能判红 + `check` 判绿 + fail-on-empty，C15）
- **新 `check_openai_compat_schema.py`**：mapping 表引用的 questor type ⊆ `EventType`；`openai_compat.schema.json` 良构；**喂未知 content part 必判红**；`--self-test` fixture valid 全过 / bad（缺字段、超字节、含 `image_url`）全拒。
- `check_protocol_schema --self-test`：加 `run_started.policy_ref`（可选、未知字段拒）+ `tools_changed`（domain 枚举）valid/bad fixture。
- `check_layering_ast`：OpenAI surface ✗ `questor.state.reduce`/store；`plugin_host` ✗ surfaces/providers 具体实现；`PolicyRegistry`(policy rank4) ✗ 外呼上层。
- `check_cross_run_no_bypass`（P8 已存）：覆盖 OpenAI 面源码（无 foreign `.run=`）。
- `check_projection_whitelist`：`policy_ref`/`tools_changed`/OpenAI 载荷键 ⊄ `_DATA_KEYS`、∩ DENY_KEYS=∅。
- `check_thin_client`：OpenAI 面若产 TS SDK/示例客户端，只消费协议、零业务下沉。
- 冷导入 `uv run python -c "import questor.surfaces.openai_compat, questor.policy.registry, questor.capabilities._host"`。

**locale / 跨平台钉宿**（承 P8 M1 + `main` cp1252 教训）
- OpenAI 面**入站可为非 ASCII**（外部客户端）：出 wire JSON 必 `ensure_ascii=False` + `Content-Type: text/event-stream; charset=utf-8`；测试内**两端钉 `utf-8`/`PYTHONUTF8`**，断言非 ASCII `content` 往返不崩、错误 object 的 `message` 为 ASCII-safe 或经显式编码（用户可见面不依赖宿主代码页，AGENTS §5.6）。
- claim/delivery/lease 用 `tmp_path` SQLite（`BEGIN IMMEDIATE`）；**另加两真 OS 子进程共享一套 SQLite 的集成测试验单机多进程双驱被 lease 拦**（DoD⑦）；不依赖真机窗口/真 LLM/真网络。
- 鉴权外部 lane：无/错 API-key → 401 fail-closed；密钥不得出现于事件/日志/快照（真文件 grep canary，承 pitfalls #1/C20）。

---

## 7. 落地风险 & 备选

| 风险 | 触发条件 | 缓解 | 被否备选 |
|---|---|---|---|
| **OpenAI 面变第二写者/第二真相** | 图快在 surface 直 reduce 或落 OpenAI 事件入 `event_log` | DoD② 源码守卫 + `check_cross_run_no_bypass` + C13/C20；投影不入库 | 让兼容面自持状态 → 否（破 C2/C15/C20） |
| **多消费者带外双投**（OpenAI+CLI+SSE） | 在 OpenAI 消费者循环再调 `log_envelope` | 复用 `EventServer` **唯一** observer；`test_p9_out_of_band_projection` 真文件 canary（每 seq 恰一行） | 逐消费者投影 → 否（pitfalls #5 明令禁止） |
| **非文本静默降级成文本** | 只取 `text` part 忽略其余、继续跑 run | 判红用例硬拦（DoD③）：不起 run 直接 400；defense-in-depth 归一 `run_failed` | 丢弃多模态块继续 → 否（ADR-0036 决策 5 明禁"绝不静默降级"） |
| **假装 resume 误导外部客户端** | 给 OpenAI 面接 after_seq 重放 | 显式"断连即 `Cancel`、无续传"（X5）；desktop `/events` 才有续传 | 兼容面加游标续传 → 否（违 design/02 §10 "无原生续传"） |
| **过度工程：移植 cordis 容器** | 把 TS Fiber/Reflect DI 硬搬进 Python | ADR-0046 只取生命周期+隔离形状、复用现成注册点；薄宿主（AGENTS §2） | 建通用 DI 框架 → 否（单用途抽象、违 §2/C12） |
| **热插拔撕裂活 run** | register 中途改在跑 run 的工具面 | 承 `tools/registry.py:97-104` freeze 语义 + `PluginHost` 只影响下一 freeze；DoD④ 判据 | 运行时改活 run 面 → 否（模型看到中途变化的面） |
| **BrokenPolicy 静默消失 / 破 fail-open** | 加载失败即从名册抹掉 / 起不来 run | 留名 + `BrokenPolicyError`；fail-open 回落默认+WARN（DoD⑤） | 静默丢弃/让 run 崩 → 否（C10、design/05 §2） |
| **跨机 exactly-once 误承诺** | 把多机 lease 当已支持写进 DoD | §1-⑦ 严格标"真双进程故障切换 UNVERIFIED"；§2-2 C12 天花板不做 | 声称跨机可用 → 否（诚实边界） |
| **外部 API lane 旁路 HITL / 裸暴露** | 为"外部可调"开非 loopback 却无鉴权/无权限收窄 | **强制 API-key/bearer fail-closed（401）** + 保守权限默认（`ask` 超时 deny、lane 工具 floor 收窄，C17）+ 密钥不入库/进日志（C20）；sidecar loopback 面不动 | 无鉴权直接对外暴露 → 否（安全边界失守） |
| **`provider.stream` 第二调用点裸奔** | OpenAI 面另起一处 provider 调用 | 一律复用 `loop.py::_stream_turn` 唯一调用点（C19 源码守卫已存） | OpenAI 面直连 litellm → 否（绕开关卡/归一） |

---

## 8. 收尾（活文档，AGENTS §5.5）+ 偏差回填 + 开工前置门

- [x] **偏差回填**（实现收尾时写"实际 vs 计划"）：本节追加"P9 落地备注"，与 `docs/plan/07 §8`/`08 §9` 同风格；Reality-wins（VISION §0.4）。
- [x] **UNVERIFIED 诚实边界**（定死不冒充）：真 LLM 驱动 OpenAI 面 / 真远程跨机 exactly-once（C12）/ 真开窗口 / TLS 终结属部署侧——逐条列（单机多进程两真子进程 = 已验证；鉴权外部 lane 本机 loopback 验证、真广网部署属算子）。
- [x] `ADR-0043`：OpenAI = 投影适配器（wire 单一真源 + 映射表 + 断连即取消 + 不 bump v）。
- [x] `ADR-0044`：非文本/语音归一化拒绝硬判据（承 ADR-0036 决策 5）。
- [x] `ADR-0045`：PolicyRegistry 落地 + `run_started.policy_ref` + AB 分桶算法。
- [x] `ADR-0046`：能力热插拔宿主（薄生命周期+熔断隔离、非 cordis 容器）。
- [x] `ADR-0047`：跨进程 claim/delivery_state 账本 + 单机多进程 run lease（接回 ADR-0021/0038）。
- [x] `design/02-event-protocol.md`：§3 run_started 加 policy_ref、§7/§10 tools_changed 转"已定义"、§9/§10 OpenAI 投影映射落地注记。
- [x] `design/05-policy.md`：§2 registry 落地口径、§6 AB 分桶算法去"待定"。
- [x] `docs/ROADMAP.md` §1（P9 DoD 落定）+ §1.5（P9 备注：非文本拒 + claim/delivery 落地）；**序列仍 P8→P9→P10**（ADR-0036）。
- [x] `CHANGELOG.md [Unreleased]` 追加 P9 条目。
- [x] `README.md` / `docs/VISION.md` 能力叙述诚实"当前仅文本模态"（ADR-0036 决策 5 强制项）。
- [x] 新模块职责/层靠**中文模块 docstring 就地自述**（`capabilities/_host.py`、`surfaces/openai_compat.py`、`contracts/openai_wire.py`、`policy/registry.py` 均已写）；无遗留 stub README 需去。
- [x] `docs/pitfalls.md`：本 Phase **未新增跨子系统陷阱**——“热插撕裂/双投/非文本降级/双驱”均由硬机制守卫与测试兜住（tools_changed 发射唯一性、cross_run_no_bypass、run-lease、fail-closed 鉴权），属普通约束非“会再踩的架构陷阱”，按 §5.5 纪律不入 pitfalls（普通 bug 走 Issue）。

**开工前置门（本计划定稿后、实现开始前）**：
1. 两路对抗式评审并行——**①契约完备性/不变式破坏**（信封/关联键/终止序、`v` 不 bump、四处 lockstep、回放/claim 一致）；**②范围漂移/安全边界/第二写者/载荷外泄/热插拔稳定性**（§2/§5/§7）。
2. **Blocker/Major 全关** → 按 ADR-0012 建 linked worktree `d:\DEVELOP\Project-main\questor-p9-openai-plugin-host`、分支 `feat/p9-openai-plugin-host`（基线 `090e5cb`）。
3. 实现严格按 **T0 先 ADR**、每条 TDD **先红后绿**、细粒度原子提交；**每次 commit/push 逐次征求许可**（AGENTS §6）；本地合 PR-only、不直推 main、不 `--no-verify`。

---

## 待拍板清单（每条：选项 · 推荐 + 代价 · 落成 ADR）

> 以下 4 条中 **D-1 / D-2 已由用户 2026-10-18 拍板**（见各条 ✅）；D-3 / D-4 的推荐默认已随实现落地（additive `tools_changed`；AB `stable_hash(fingerprint)%n` 默认 n=1 + 可覆写 split 表）。§1–§7 按此写死。

**D-1 ✅ 已拍板（用户 2026-10-18）：加鉴权、可网络暴露、可违旧文档口径。**
- 定夺：**新建独立"鉴权外部 OpenAI API lane"**（与桌面 sidecar loopback bootstrap 面**并行、分道**）——可算子配置 **opt-in 非 loopback bind + 强制 API-key/bearer fail-closed**（密钥不入库/进事件/进日志，C20/ADR-0019）、非 loopback 建议 TLS；**桌面 sidecar `--serve` loopback 红线（ADR-0032）原样保留**，属对 ADR-0032 的**显式分道 scoping、非推翻**，记入 **ADR-0043** 并就地注记 ADR-0032。
- **安全硬边界**（OpenAI wire 无审批通道→必钉）：经本 lane 起 run 采保守权限默认（`permission_mode=default`、`ask` 工具**超时 fail-closed deny**、lane 工具 capability floor 默认收窄，高危 write/exec 不因"外部可调"降 allow，承 C17）。

**D-2 ✅ 已拍板（用户 2026-10-18）：取全局最优、为后续大扩展铺路的最完整底座。**
- 定夺：**建完整、可演进的 durable claim/delivery_state 账本 + 单机多进程 run lease**（接口按"未来跨机=换后端非重构"设计，但**本 Phase 仍不实现跨机**，C12）；**真接 `ReportChildTerminal`/投递路径**；**用两个真 OS 子进程共享一套 SQLite 在集成测试里端到端验单机多进程**（本机 Windows 可跑）→ DoD⑦ 升 **"单机多进程=已验证"**、**跨机=UNVERIFIED（天花板）**。与 D-1 咬合：鉴权外部 API lane 若作独立进程跑，正是本 run-lease 防双驱的首个真实单机多进程消费者。落 **ADR-0047**。

**D-3 热插拔是否新增 `tools_changed` 事件类型？**
- 选项：(a) **additive 新增 `tools_changed`（domain: tools|skills|mcp|plugins|settings），承 design/02 §7 预留名（推荐）**；(b) 用现有 `warning` 携带变更、不新增类型。
- 推荐 (a)：外部 OpenAI 客户端与桌面需明确"能力面变了"的信号；(b) 代价 = 语义挤进告警、消费者难判。均**不 bump `v`**、不碰信封/关联键/终止序。落 **ADR-0046**。

**D-4 A/B 分桶键与默认档位？**
- 选项：分桶键 = **内容 `fingerprint`（推荐，承 ADR-0009 决策 2"非版本号"）**；算法 (i) `stable_hash(fingerprint) % n` + 算子可覆写显式 split 表（推荐，确定性可测）/ (ii) 纯算子手工表。
- 推荐 (i)+默认 `n=1`（单桶=不分流，安全默认）：需要灰度时才配 split 表。代价：默认下 A/B 不自动分流（刻意保守，防误路由）。落 **ADR-0045**（design/05 §6 "AB 分桶算法"由此转"已定")。

---

## 9. 落地偏差回填（实现收尾，AGENTS §5.5 Reality-wins，2026-10-18）

- **实际 vs 计划**：T0–T11 全序落地，无偷工减料。**两处计划内细化**：① T1/T2 的事件 additive（`tools_changed` + `run_started.policy_ref`）合并为一个 lockstep 提交（含 TS codegen + `check_protocol_schema` fixture 扩面），避免跨提交留协议守卫判红（"每 commit 绿"优先于"按 T 边界切开"）；② `--serve-openai` 外部 lane 的组合根入口在 T6c 之后补，默认 loopback + fail-closed（无 key 拒起），与 ADR-0043 一致。
- **已机器验证**：`test_openai_wire`(11)/`test_openai_projection`(4)/`test_openai_endpoint`(5：流式+聚合+401 fail-closed+400 非文本拒+断连→Cancel)/`test_policy_registry`(7)/`test_policy_assembly`(4)/`test_plugin_host`(8)/`test_capability_generation`(3)/`test_claim_delivery_lease`(4)/`test_run_lease_multiprocess`(1：**两真 OS 子进程共享 SQLite 端到端验单机多进程单写者**)/`test_p9_policy_hotswap`(1)/`test_tools_changed_lockstep`(5)。全量 **797 passed / 5 skipped**（继承 P8 739 + P9 新增 58）。守卫全绿：协议 23 types lockstep、新 `check_openai_compat_schema --check/--self-test`（进 `boundaries`）、`check_layering_ast` 0 违规（114 文件）、replay 5 fixtures、projection whitelist、cross-run no-bypass、secret-projection、output-budgets、verify_p0 冷导入；全树 ruff clean。信封/关联键/终止序零动、`v` 不 bump、四处 lockstep。
- **UNVERIFIED（诚实边界，不冒充）**：真 LLM 驱动 OpenAI 面（本机无 key，ASGITransport + 脚本化 provider 覆盖 wire 逻辑而非真模型）；真跨机 exactly-once（**单机多进程两真子进程=已验**，跨机属 C12 天花板未做）；真广网部署/TLS 终结（属算子侧，`--serve-openai` 默认 loopback）；OpenAI lane 的 `ask`-超时-deny 真审批交互（C9 fail-closed 既有，本 lane 无审批 UI 故默认拒）。
- **对抗评审收口**：见 §4.3——M1（tools_changed live-only 发射语义）/M2（resume 冻结 policy_ref）/S1（鉴权 lane 权限面）/S2（多进程双驱 run-lease）/S3（密钥/载荷不外泄）/R1（不植 cordis 容器）均已落进对应 ADR/T 并在代码/守卫/测试兑现。
