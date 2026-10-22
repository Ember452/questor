# R08 · 可靠性与可观测实扒参考（加固 04/02 + HARD-CONSTRAINTS 红线）

> **只读实扒产物，非实现、非 04/02/HARD 的替代。** 本文只给**增量与坑**，用于加固 [`docs/design/04-turn-loop.md`](../design/04-turn-loop.md)（§5 工具轮、§8 错误/fallback、§11 L1/L5/X4）、[`docs/design/02-event-protocol.md`](../design/02-event-protocol.md)（§0 铁律3、§3 终止事件、§9 E2/X2）与 [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)（C5/C6/C7/C10/C13/C14）。
> 方法：读全三家相关模块，结论一律带 `文件:行号`（相对各自仓库根）。抽样即不成立——凡未直接读到的行不引用。行号为扫描快照，作定位用，不作契约。三家分别 Python/Go/Python，**借鉴的是机制模型，不是逐行照搬**。
>
> 扫描范围（本轮，全部读全）：
> - **hermes-agent-main**：`agent/error_classifier.py`（1504）、`agent/api_error_summary.py`（249）、`agent/fallback_cooldown.py`（129）、`agent/credential_pool.py`（3138，读全核心：状态/TTL/冷却/DEAD 判定 `80-520/1041-1075/1874-1910`）、`agent/credential_pool_model_cooldowns.py`（131）、`agent/credential_pool_admin.py`（164）、`agent/credential_pool_plugin.py`（105）、`agent/auxiliary_stream_watchdog.py`（180）、`agent/interrupt_control.py`（360）、`agent/interrupt_scope.py`（73）
> - **wuu-main**：`internal/toolerrors/error.go`（30）、`internal/agentcontrol/errors.go`（87）、`failure_sink.go`（100）、`mailbox.go`（141）、`delivery.go`（601）、`worker_terminal_transition.go`（207）、`worker_terminal_ack.go`（525）
> - **CowAgent-master**：`agent/protocol/agent_stream.py`（2962，重点读全重试/fallback/overflow 段：分类 `50-165`、run 粘性 `900-1000`、`_call_llm_stream` `1573-2160`）

**读 02/04/HARD 的结论**：三家的**接缝方向已定且被实扒正面印证**——错误分类与循环解耦（04 §5）、重试/fallback 全走 Command/reduce 不撕裂状态（04 §8、C7）、Event append-only 发出不可撤回（C5/C10、04 X4）、终态唯一（C13、02 E2）、只存内部事件外部是投影（C13/X2）、observability 只读上报（C14）。本文命中 04 §8 与 02 §3 **只有骨架、缺"可落地形状"**这一最大缺口，以及一批**落地坑**。不推翻已定接缝，全部属"跑通后 lock"的未决带（04 §10、02 §8）。

---

## 主题 A — 错误分类：把"结论"与"循环"解耦，产结构化恢复意图

### 现状（04/02/HARD）
- 04 §5"失败≠崩溃：分类可重试/致命，喂回策略下轮自纠；错误进 `error_stack`"；04 §8"Provider 错误→LiteLLM 重试/fallback；耗尽则 `run_failed`（带 `retryable`）"。
- 02 §3 `run_failed` 只有 `error{code,message,retryable}` 一个三元组。
- 缺：分类器**产什么**、**在哪跑**、**谁消费**；"可重试/致命"只是二值，真实世界是**多恢复轴**（重试 / 换凭据 / fallback 模型 / 压缩 / 中止）。

### 增量
- **A-1 分类产物应是"结构化 verdict + 多条恢复 hint"，不是单一 `retryable: bool`。** hermes `ClassifiedError` 把结论拆成四个正交开关：`retryable / should_compress / should_rotate_credential / should_fallback`（[`error_classifier.py:69-94`]），retry 循环"查这些开关而不是自己重新匹配字符串"（模块 docstring [`error_classifier.py:1-6`]）。verdict 由**有序规则表**产出，每条预绑定 hint 组合：`_ROTATE_FALLBACK={rotate+fallback}`、`_ABORT_FALLBACK={retryable:False+fallback}`（[`error_classifier.py:460-490`]）。
  → 04 §5 `error_stack` 与 02 §3 `run_failed.error` 建议从 `retryable` 升级为**多 hint 契约**（`retryable / should_compress / should_fallback / should_rotate_credential`），并把 `error.kind`（枚举 `FailoverReason`，30+ 值 [`error_classifier.py:34-66`]）作为对外 `error.code` 的稳定命名空间。
- **A-2 分类是一条"优先级阶段流水线"，不是 if-else 堆。** hermes `_STAGES` 固定序：插件 hook → provider profile hook → provider 特例 → HTTP 状态 → MoA 形状 → 结构化 code → message 模式 → SSL → 断连+大会话 → transport 类型 → unknown 兜底（[`error_classifier.py:965-971`]）。**顺序即语义**：例 `_by_status` 在 `_by_error_code` 前，因为"handler 总是返回、code 阶段就再也看不到"（[`error_classifier.py:1199-1202`]）；memory-ceiling 必须**先于** overflow 与 usage-limit 判定，否则"memory limit exceeded"含"limit exceeded"被误读成 billing（[`error_classifier.py:226-242`]）。
  → 04 §8 应把"Provider 错误→重试/fallback"具体成**一张阶段优先级表 + 每阶段的判据**，并显式记"阶段顺序是契约的一部分"。
- **A-3 分类器必须可被外部纠正，且纠正本身被故障隔离。** hermes 留两级 hook：通用插件 hook `_plugin_verdict`（[`error_classifier.py:703-720`]）与 provider 自带 `ProviderProfile.classify_api_error` `_profile_verdict`（[`error_classifier.py:723-763`]）；两者**整段包在 try/except 里，import/dispatch 失败即降级到内建流水线、绝不让分类器崩**（[`error_classifier.py:714-716`、`738-740`]）。profile 只要 `should_fallback` 却没给 `retryable` 时，按 reason 补内建默认，使 hook 的裁决"像内建的一样级联"（[`error_classifier.py:751-757`]）。
  → 对应 questor C10"插件一律包在熔断/超时护栏里"：**错误分类也应是一个可插拔 PolicyPort 式的 hook**，且 hook 失败 fail-to-builtin，不 fail-the-loop。
- **A-4 "可重试但要先退避再 fallback"是一类，别和"立即 fallback"混。** hermes `RETRYABLE_CLIENT_REASONS`（rate_limit/upstream_rate_limit/overloaded/context_overflow/payload_too_large/long_context_tier/thinking_signature）——这些 verdict 即便带 `should_fallback`，**级联发生在退避预算耗尽之后**而非立即（[`error_classifier.py:768-774`]）。
  → 04 §8 fallback 触发需区分两档：**即时换链**（auth_permanent/billing/model_not_found 等终态）vs **退避后换链**（限流/过载/溢出）。

### 坑
- **A-P1 关键词分类的"假阳性代价"必须写进注释。** CowAgent 开篇即警告：两条 fatal 分支**都会丢弃整个内存上下文**，故"每个标记必须specific到不会出现在无关失败里"——通用词（"without"/"not found"）曾匹配过多，**裸 "400" 连 token 数 4000 都误判**，遂改用 `\b400\b` 词边界（[`agent_stream.py:59-70`]）。
  → 04 §5 分类若采字符串启发，**红线**：marker 表须防假阳性，且**假阳性=丢上下文的代价**要在规则旁注明。
- **A-P2 别把"尺寸过大"误判成"上下文溢出"**——oversized upload（413 file/image too large）**必须排除在 overflow 外**，否则会为"与上下文长度无关的问题"去 compact/clear 一次健康会话（CowAgent 显式 `deliberately NOT a bare "too large"` [`agent_stream.py:1733-1742`]；hermes 把 image_too_large/memory_ceiling 各立独立 reason [`error_classifier.py:48-49`、`226-249`]）。
- **A-P3 分类为 `format_error` 与 `context_overflow` 的边界**：畸形转录（如死流残留的空 assistant stub）**输入可能很小、压缩造不出缺失的 turn**，须 fail-fast 成 format_error 而非进压缩循环（[`error_classifier.py:286-293`、`1191-1198`]）。questor 04 §5 error_stack 需把"可压缩恢复"与"不可恢复须 fail-fast"分栏。
- **A-P4 HTTP 状态可能被藏在 HTTP-200 的 SSE error 帧里**：聚合器把上游失败作为 `{error:{code:…}}` 塞进 200 流，SDK 只抛无状态 `APIError`——hermes 专门从 body 反推状态码（`_status_code_from_body` [`error_classifier.py:1420-1443`]）。流式 provider 的分类器**不能只信 `.status_code`**。
- **A-P5 cause 链要走、但要有界**：hermes `_from_cause_chain` **最多 5 层**取 status/body/headers（[`error_classifier.py:1381-1392`]）；CowAgent 遍历 `__cause__/__context__` 找 DNS 标记（[`api_error_summary.py:163-172`]）。无界链在循环异常里会死转。

---

## 主题 B — 重试 / fallback 边界：预算、粘性、退避封顶、整链汇总

### 现状（04/HARD）
04 §8 一句话带过"重试/fallback 耗尽则 run_failed"。缺：重试预算怎么给、fallback 链每环几试、退避封顶多少、粘性何时重置、错误怎么汇总上报。

### 增量
- **B-1 fallback 链"每环一次尝试"，primary 才有完整重试预算。** CowAgent `_on_fallback=True` 时 `link_retries=0`（[`agent_stream.py:1586-1590`、`1913-1920`]）：给每条兜底链完整退避会"按链长翻倍等待、还没走到最后一环就超过 web SSE 空闲超时"。换链**fresh `retry_count=0`**再进下一环（[`agent_stream.py:1982-1988`]）。
  → 04 §8 应定死：**primary=满预算重试；fallback 链每环=单次尝试**；退避预算是 run 级 wall-clock 的一部分（呼应 04 §3 全局终止判据）。
- **B-2 退避要封顶，且上限的"为什么"是传输层空闲超时。** CowAgent 429 曲线 `30+retry*15` **封顶 60s**（`RATE_LIMIT_MAX_WAIT`），理由写死："不封顶第 8 次重试就越过 web 通道 600s SSE 空闲超时"（[`agent_stream.py:154-157`、`1952-1955`]）；非限流类用轻量 `(n+1)*2`。hermes primary 冷却则是**指数 60s→2m→…→4h**封顶 `14400`（[`fallback_cooldown.py:45-76`]）。
  → 04 §8/L4（护栏全配置化）应把**退避曲线+上限**列进 `run.budget`，并注明上限=对端传输空闲超时的函数，不是拍脑袋。
- **B-3 fallback 在一个 run 内"故意粘"，跨用户消息才重置。** CowAgent run 起始 `_reset_model_fallback(nested_run=...)`：**新用户消息永远从 primary 重开**；同一 run 内一旦 primary 彻底失败就**留在兜底**，否则每次工具步都白打一次已知宕机的 provider（[`agent_stream.py:947-965`]）。嵌套判定用 `id(self.model)` 是否在 `_ACTIVE_RUN_MODELS` 上下文变量里——**subagent 共享父 model 对象即继承父的 fallback 态**（[`agent_stream.py:50-57`、`961-964`]）。
  → 04 §8 缺"fallback 粘性"语义。建议：**粘性作用域=run**（对应 questor run_id），换 run 复位；subagent/委派继承外层 provider 态。
- **B-4 429 有兜底时"立即切"而非"等"。** 429 是唯一"有备胎就不该等"的错——备胎是另一个 provider 有自己的配额；无链配置才退回等待（[`agent_stream.py:1922-1940`]）。但反过来，hermes `switch_deferred_by_reset` 给了一个 opt-in：**当主模型限流的重开窗口 < `min_switch_reset_seconds` 时，切模型比等待更贵，就跳过 fallback、由重试退避骑过窗口**（[`fallback_cooldown.py:24-42`]）。
  → 04 §8 fallback 触发应可读**provider 声明的重开时间**（`reset_at`），在"切链成本 vs 等待成本"间取小，而非无条件切。
- **B-5 冷却要分"整凭据"与"按模型"两域，且区分 transient / terminal。**
  - hermes 池冷却 TTL：`401=5min / 429=1h / default=1h`，但**当它是唯一可用凭据（sole_credential）时压到 60s**——一小时硬失败显然荒谬（[`credential_pool.py:131-140`、`373-400`]）；provider 给的 `reset_at` **覆盖默认**（`_exhausted_until` [`credential_pool.py:469-481`]）。
  - **按模型冷却**：Anthropic per-model 429 只冷却**被请求的那个模型**，兄弟模型不受影响（[`credential_pool_model_cooldowns.py:1-8`、`61-75`]）。
  - **terminal（DEAD）vs transient（EXHAUSTED）**：`token_revoked/invalid_grant/refresh_token_reused` 等 → DEAD，**永不自愈、只被显式 re-auth 清、绝不靠 TTL**（[`credential_pool.py:85-100`、`1874-1893`]）；模型 entitlement（账号根本没买这个模型）→ **bench 一年**直到 `hermes auth reset`（[`credential_pool_model_cooldowns.py:17-19`、`92-97`]）。
  → questor 无凭据池，但**冷却/失败隔离域**要落进 `run.budget`/error_stack：至少分 transient(有界退避) / account-scoped(整链) / terminal(本次会话永久跳过) 三档，别一律指数重试。
- **B-6 全链耗尽要"合并上报整链错误"，不是只报最后一个。** CowAgent 用 `_exhausted` 累积每环错误，链走完 `spent>1` 时把 `"model_a: err | model_b: err"` 一起抛，避免"看起来像最后那个模型坏了"（[`agent_stream.py:1591-1594`、`1974-2004`]）。
  → 对应 02 §3 `run_failed` / 04 §5 error_stack：终态错误应能携带**整链失败摘要**（多条 {model/kind/message}），不是单条。

### 坑
- **B-P1 "冷却只在离开 primary 时武装"。** hermes `_arm_rate_limit_cooldown`：从一个已激活的 fallback 再链式切换时**不武装 primary 冷却**，因为失败的源不是 primary（[`fallback_cooldown.py:50-61`]）。移植时要还原本条件，否则误冷却主模型。
- **B-P2 单调钟 vs 墙钟不可混比。** provider `reset_at` 是**墙钟 epoch**，`_rate_limited_until` 是 `time.monotonic()`——hermes 显式"经 duration 转换，绝不让 epoch 值进入 monotonic 比较"（[`fallback_cooldown.py:50-52`、`71`]）。questor 重试退避计时**必须同基准**。
- **B-P3 entitlement 与 stale-token 同一句话，须消歧否则振荡。** xAI/Codex 对"未订阅"与"token 过期"返回**同一 403/400 文本**——hermes 用 `[WKE=unauthenticated]` 后缀区分"刷新可救"（[`api_error_summary.py:79-111`]）、Codex 用 `pool.has_available` 先轮转、无剩余才把 `(provider,model)` 标会话级 dead，否则"每轮都在 primary 失败、宣告未验证的 Primary restored、无限振荡"（[`fallback_cooldown.py:79-117`]）。
  → questor fallback 红线：**"恢复主模型"的宣告必须可信**（真 entitlement-ok 才切回），否则会制造对外可见的振荡事件。

---

## 主题 C — 流式看门狗：无进展计时、FD-safe 关 socket、终块保留计费

### 现状（04/02/HARD）
04 §4"Provider 流→直接投 `*_delta`（不落状态）"；02 §3 `heartbeat` 保活。缺：**流卡死/静默**如何检测、如何在不撕裂连接池的前提下中断、半流如何收尾。

### 增量
- **C-1 "无进展看门狗"是独立机制，超时不是等 request budget 自然到期。** hermes 消费者阻塞在 SDK chunk 迭代器里，静默流只有等 httpx read timeout（辅助调用 ≥300s）才发现，宿主早放弃了——故从**一个 Timer 主动掐断本次尝试的 socket**：它**跨线程 FD-safe**、唤醒 owner 的阻塞读、owner 仍在 `finally` 里 close，池丢弃死连接而非回收（[`auxiliary_stream_watchdog.py:1-9`]）。
  → 04 §4 流式段应加一条**看门狗红线**：`*_delta` 流须有"两个 chunk 之间最大静默窗口 + 首 token 前最大窗口"，超时按 verdict 决定"同 provider 重试"还是"直落 fallback"。
- **C-2 首 token 窗口 ≠ chunk 间窗口——推理模型会静默想几分钟。** `first_token_window` 取主循环的云 stale 耐心（reasoning 模型 floor），chunk 间窗口取短（默认 60s）；本地 server 的静默 prefill 则交给 request timeout（None）（[`auxiliary_stream_watchdog.py:40-43`、`135-156`]）。
  → questor `run.budget` 须配**两个独立超时**，别用一个值（否则要么误杀 thinking 模型、要么放任卡死）。
- **C-3 看门狗必须"代际栅栏 + 退役即失效"，绝不误伤被复用连接。** 构造时就**钉住本次尝试的 socket**并在响应把连接交回池前 retire（`_fence_release`）；`_fire` 在锁内三重判据：`_done` / `deadline is None` / `generation != self._generation` 任一即**不动作**；提前醒来的 timer 若 deadline 还没到就重排（[`auxiliary_stream_watchdog.py:56-62`、`79-113`]）。
  → 这是 keepalive 连接复用下**唯一安全**的做法。questor 若用连接池，看门狗须带**同一代际栅栏**，红线级别。
- **C-4 终块已到（有 finish_reason + usage）后的"卡住"= teardown，不推翻已完成响应与已计费 usage。** `consume_chat_stream`：看门狗 fired 但 `acc.finish_reason` 已到手 → **不抛 timeout、保留已计费响应**；只有零输出卡死才报 "no-progress timeout"（同 provider 重试仍允许），mid-stream 卡死才直落 fallback（[`auxiliary_stream_watchdog.py:122-132`、`159-180`]）。
  → 02/04 流式收尾红线：**定稿边界**（拿到 finish_reason）之后的网络尾噪声不应升级为 `run_failed`。

### 坑
- **C-P1 mid-stream 取消/中断只持久化部分文本、绝不持久化半截 tool_use 参数。** CowAgent 每 8 个 chunk 探测一次 cancel（`_CANCEL_PROBE_EVERY`）以平衡反应速度与逐 token 开销；命中即**只 append `full_content` 文本、丢弃可能截断的 tool_use args**（args 截断会过不了校验），发 `message_end{cancelled:True}`（[`agent_stream.py:47-48`、`1670-1694`]）。steer 同理 mid-stream 中止但 `return` 非 raise（[`agent_stream.py:1695-1708`]）。
  → 直接印证 01 §2 tool_use 必配 tool_result / C7"回填所有 pending tool_call"：**流式中途取消时，未闭合的 tool_use 不得进状态**——questor 04 §3 Cancel reduce 需含"截断流不留半 tool_use"这条。
- **C-P2 provider 的 usage 位置不统一。** CowAgent " whenever `chunk['usage']` 出现就读"，因为有的 provider 在 `include_usage` 末块发（choices 为空）、有的挂在普通 chunk 上（[`agent_stream.py:1751-1757`]）。→ 02 §3 `usage_delta`/`include_usage` 采集不能假设"只在末块"。
- **C-P3 reasoning 字段名五家各异。** `reasoning_content`/`reasoning`/`thinking` 三选一再判 list（[`agent_stream.py:1769-1779`]）；**thinking 块绝不能当可见回复**——正是把 CoT 泄漏成"Agent Reply"的根因（[`agent_stream.py:1785-1802`]）。→ 02 §3 `reasoning_delta` 与 `text_delta` 的分离要有 provider 归一层，且**红线：thinking 不进对外正文**。

---

## 主题 D — 取消 / 中断：归属、跨线程传播、可观测基于事件流

### 现状（02/04/HARD）
C7"终止经 `Cancel` Command→reduce、不硬杀；reduce 置 cancelled **且回填 pending tool_call**"；04 §3 全局判定；02 §3 `run_cancelled` 先于 `run_completed`。缺：**谁发起的取消**（用户 vs 系统 vs 租约丢失）如何归因、跨线程/子 agent 如何传播、host 深层同步里创建的 agent 如何被取消。

### 增量
- **D-1 "取消来源"是一等字段，归属决定对外事件文案与账本归责。** hermes `interrupt()` 区分 human-stop 类别（`USER_INTERRUPT_REASONS`）与系统 producer（watchdog/lease-loss/lifecycle）经 `tool_reason` 注入的类别——**系统发起的软中止以前没法自我标注，传 message 会被当成"用户发了新消息"、被错误归责成用户停止**（[`interrupt_control.py:18-32`、`147-155`] #130207/#112647）。`interrupt_skip_wording` **从"记录下来的 reason"派生**而非调用点，"绝不会断言一条根本没存在的用户消息"（[`interrupt_control.py:35-45`]）。
  → 02 §5 `Cancel(reason: user|timeout|safety)` 与 04 §2 `LoopState.cancel_reason` 已含枚举——**增量**：加一条"**归因来源必须落到退出原因/对外事件文案，且从记录派生、不从调用点臆测**"。对应 C7 reduce 不变式"Cancel 要区分来源"。
- **D-2 host 深同步里创建的 agent 收不到 interrupt：用"绑定作用域 + 注册即中断"消除竞态。** `InterruptScope`：host 在 worker 线程跑阻塞命令时看不见 CLI 在内部 fork 的 agent，故绑一个 scope，其下每个 `run_conversation()` 注册自己，`scope.cancel()` 从任意线程硬中断——**cancel 之后才注册的 agent 立即被中断，cancel 永不输给还没开始的 turn**（[`interrupt_scope.py:1-10`、`34-57`]）。
  → questor sidecar/Tauri（R07）同构场景：取消要能穿透到"深在同步工作里新建的执行单元"。建议 Cancel Command 携带**作用域/租约 id**，reduce 层"迟到注册即取消"。
- **D-3 中断要"扇出到工具工作线程 + 递归到子 agent"，且作用域隔离到本 agent 的执行线程。** `is_interrupted()` 在工具里只看见自己 tid，故须把中断位**fan-out 到并发工具的 worker tids**（否则挂起的并发工具跑到自己超时而不停），且**限定到本 agent 执行线程**以免波及其他进程内 agent；再**递归传播给 running child agents**（subagent 委派）（[`interrupt_control.py:106-123`、`209-227`]）。
  → 04 §3/§5：并行工具与子 agent 的取消传播是 **C7 reduce 不变式**（回填 pending）在运行时的另一半——**先让在跑的活真正停下，再回填**。v1 关并行（04 X1）可简化，但子 agent 取消传播仍需（呼应 R03 C-4 wuu tree_freeze）。
- **D-4 redirect：只掐"模型请求"，保留已完成消息、把纠正追加成真 user 消息重跑；工具执行中则降级为 steer，绝不为送指引而杀工具。** （[`interrupt_control.py:280-341`]）。工具跑着时 `redirect` 调 `steer()` 并请求工具 **yield**（终端命令转后台、能 yield 的工具才 yield）（[`interrupt_control.py:303-317`]）。
  → 02/04 缺"活动 turn 重定向"这类终止粒度。它比 Cancel 更细：不结束 run、只废弃当前在飞的模型请求。**列为 v1+ 生长场景**（02 §7 已预留 `peer_*`/`budget_update` 式的只增扩展）。
- **D-5 可观测：把"发生了什么"沉淀成结构化记录 + 事件，且上报面严格只读。**
  - CowAgent 在关键转移**发具名事件**：`model_fallback{reason,model}`（[`agent_stream.py:1977-1981`]）、`message_end{cancelled|steered|empty_retry|stop_reason}`（[`agent_stream.py:1689-1708`、`2106-2111`]）、`agent_start`（[`agent_stream.py:922`]）——**每个都是外部可订阅、含"为什么"的结构化事件**，正是 02 §2"内部事件→外部投影"的活形状。
  - wuu `FailureSink/ReportSink`：`AgentFailure{Source,TaskID,RunID,AgentID,Outcome,Message,Blockers,...}` / `AgentReport{...Summary,Verification,Artifacts,NextSteps}` **结构化落观测面**，字段先归一化（trim）再记账，message 缺省时按 blockers→outcome 兜底（[`failure_sink.go:8-93`]）。
  - → **印证 C14"observability 只依赖 contracts、只读上报、不改状态"**：wuu 的 sink 是纯旁路记录器（`if c.failureSink==nil return nil` [`failure_sink.go:48-51`]），不反向改 worker 状态。questor observability 红线可补一句：**观测记录是终态事实的只读投影，与 Command/reduce 正交**。

### 坑
- **D-P1 中断的"最终变更边界"要带 claim，否则一个已恢复的 turn 会误吞 abort。** hermes `require_generation`：在**同一 liveness lock 下预留 claim**，真实进展会作废它，claim 在"第一个可观测发布点"被消费——**claim 消费与首次发布是一个 activity-lock 临界区**，要么 claim 存活并提交、要么 stamp 先落且 abort 不发布（[`interrupt_control.py:139-145`、`184-191`]）。硬取消 admission 还分两半：**claim 前**只等待 in-flight commit（阻塞返回 False 不设 `_cancelled`，因为一个可能被判_declined_的 abort 不该不可逆地取消 pending fence）；**claim 后**只取消"仍 pending 的 commit"（[`interrupt_control.py:54-70`、`175-194`] #99758）。
  → questor 若允许"turn 已 resume 又收到 cancel"，需一个**代际/claim 栅栏**，不能裸设 cancelled 标志。这是 C7"终止走命令不硬杀"在高并发下的实现细节。
- **D-P2 清中断时"已接受的 steer"别静默消失。** `clear_interrupt`：除硬取消外的所有 caller（redirect 重建/错误恢复/turn 边界卫生）**保留 pending steer**，让它活到既有 drain；只有硬 stop 才丢弃未消费 steer（下一工具迭代不再发生、重注入会惊吓用户）（[`interrupt_control.py:238-265`]）。注释指出旧 bug：无条件清 slot 会"无痕迹地丢掉一条活的用户消息"。
  → 04 §5/§6：turn 循环出错恢复时，**用户已投递的输入不得被错误路径擦除**。

---

## 主题 E — 异常隔离 + 回滚，但已发事件不撤：exactly-once 投递与终态恢复

### 现状（02/04/HARD）
C5"Event append-only 发出不可撤回"；C10"插件 panic→捕获、回滚到最近 Checkpoint、发 error 事件、已发 Event 不撒回、Shell 要处理'半流后回滚'"；04 X4 同；C13"终态唯一、reduce 串行 first-writer-wins"；02 E2 并发终止按优先级择一。缺：**重放会重发事件、如何去重**、**崩溃后终态转移的恰好一次恢复**。

### 增量
- **E-1 "回滚只回 Domain_State、已发事件不撤" → 恢复不重复干活靠"消费端幂等 claim"，不是"抑制重放"。** wuu 把每个终态结果算一个**内容寻址稳定 id**：`agent_result_<sha256(agentID|status|completedAt|result|error)[0:12]>`（[`delivery.go:46-71`]），非终态快照**无可消费 id**（[`delivery.go:48-50`]）。投递走 `EventResultReady→Claim→Release` **三种事件**，claim 是 store 跨进程锁下的 **compare-and-append**（[`delivery.go:133-213`、`276-330`、`343-401`]）。`ClaimAgentResultDeliveryID` 返回 `(claimed, consumedBy)`——**别的投递路已消费就返回 False**（[`delivery.go:145-156`]）。
  → 正解 02 E2/X2 与 01 I7"重放不重复副作用"：**事件必然重放，去重在消费端按稳定 id claim**。questor 02 §3 可给 `tool_completed`/终态事件配**稳定投递 id**（复用 02 §1 关联键 `tool_call_id`/`item_id`），reduce/投递层"claim-then-deliver"。
- **E-2 投递态本身是事件溯源账本，恢复=重放这些事件重建 claim 视图。** wuu `refreshAgentResultDeliveries` 从 durable `EventResultReady/Claim/Release` 重放，rebuild `resultDeliveries` map（[`delivery.go:343-401`]），"每次调用都 refresh，好让第二个 app-server 观察到第一个提交的 claim"（[`delivery.go:403-418`]）。**两阶段提交**：`commitDurablyAppliedNestedResults` **仅在父的持久化转录真含该 resultID 后**才把 claim 从 `nested_pending` 推进到 `nested_followup`——"在此之前崩溃留下可重放的 pending claim；在持久化之后、推进之前崩溃由 startup replay 修复"（[`delivery.go:524-560`]）。
  → 印证 questor 01 §11/ADR-0005"恢复=最近快照+重放其后事件"；**增量**：投递/claim 视图也应可从事件重放重建，不落第二份真相（呼应 C13 X2"外部事件不入库"）。
- **E-3 终态转移的"崩溃恢复权威"要早于 best-effort 通知落盘。** wuu `prepareWorkerTerminal` 是装在 Manager 上第一相，**在最终 worker 快照持久化之前**把"这一确切断代 terminal generation"变 durable，成为后续所有相的 crash-recovery 权威（[`worker_terminal_ack.go:251-264`]）；durable 记录**带 schema 版本**（`wuu/worker-terminal-finalization/v1` [`worker_terminal_ack.go:19-36`]）。`finalizeWorkerTerminalWithAck` 产出三态：`Committed / Continued / Deferred`——**外部 finalizer 失败时记录保持 durable、不消费、留待恢复**（[`worker_terminal_ack.go:266-344`]）。
  → questor 04 §7 checkpoint / C10 回滚：终态意图要**先 durable、后 ack**，ack 失败留 pending；不能"通知发了、状态没落"。这是 C10"回滚到最近 Checkpoint"能成立的前提。
- **E-4 "优雅让位"=把所有权移交给 durable pending 屏障，而非无限重试也不裸放。** `retryWorkerTerminalStep` 对外部 store **无限重试**（每 100ms、仅首次/每 10 次 debug 打点 [`worker_terminal_ack.go:237-249`]），但 `YieldWorkerTerminalFinalizations`：**只在"其确切 terminal intent 已 durable"后才停 in-memory 重试**，把所有权交给 pending-record 屏障（既不因 store 宕机永久卡住、也不释放未记录的终态）（[`worker_terminal_ack.go:346-361`]）。recovery 轮询 `waiting_children` 的 parked 父**故意不重扫**（唤醒路才 re-drive）（[`worker_terminal_ack.go:443-455`]）。durable 记录**跨进程退出存活**，与 OS lease 互补（[`worker_terminal_ack.go:196-202`]，配 R03 E-2 worker_execution_lease）。
  → questor C7/C10 落地：**关闭/宕机恢复序**——先确保终态 durable、再让位、后台轮询恢复未 ack 的意图。可写进 04 §7 与 C10 脚注。
- **E-5 分类为 fatal 也要给"可原地复活"的出口，别一律判死。** wuu `ClassifyError(nil)=fatal`（fail-closed，调用方不必特判 [`errors.go:41-43`]），但失败/取消的 run **保留全 context 并打 `Resumable=true + ResumeHint`**，告诉父"发消息原地复活、而非重开"（`isResumableMailboxStatus` 只对 failed/cancelled [`mailbox.go:95-124`、`113-124`]）。CowAgent 溢出/格式错也**只重置内存上下文、持久历史保留**（[`agent_stream.py:1886-1901`]）。
  → 呼应 01 C-4（resumable/子树冻结）与 04 X4（回滚不撤已发事件）。questor 02 §3 `run_failed.error` 建议带 **`resumable: bool`**，与 `retryable` 正交：`retryable`=能否自动重试，`resumable`=能否人工带上下文复活。
- **E-6 错误载荷是攻击者可影响的面，回滚/上报路径必须先脱敏。** hermes 把 provider/proxy 错误 body 视为 attacker-influenced，**返回前 `redact_sensitive_text`**，否则回显的 `Authorization/x-api-key/request JSON` 会漏进 final_response + 日志（[`api_error_summary.py:201-223`] #36109）；`_mask_api_key_for_logs` 对 Azure Entra bearer **绝不在日志路径里调用可调用对象**、只标 `<entra-id-bearer>`（[`api_error_summary.py:228-237`]）。credential plugin refresh 失败先**采纳 peer 已轮转的 token 再分类**、terminal grant 用 **WARNING 不是 debug** 记（登录丢失时刻）（[`credential_pool_plugin.py:80-105`]）。
  → questor C6"未知 error 事件至少告警"、C10 error 事件、C14 观测——**统一红线**：错误/事件/日志载荷 **fail-safe 脱敏，绝不在日志/观测路径执行凭据**。

### 坑
- **E-P1 "冷却/身份标记"须能跨进程区分"重置过"与"从没有过"**：两者裸值都是 None——hermes 用 `status_cleared_at` 标记解决（[`credential_pool_admin.py:12-18`] #89415），且 add 后**读回 store 校验该行真存在、不在就抛 `CredentialNotSavedError` fail-loud**（[`credential_pool_admin.py:154-163`]）。questor 冷却/DEAD 标志若入持久层，需同样的显式 cleared-marker。
- **E-P2 fail-open vs fail-closed 要按语义选、并写清楚。** wuu 池外的未知 token `token_is_blocked` **fail-open**（没行可归因冷却）（[`credential_pool_model_cooldowns.py:48-59`]）；而配额读 `QuotaReader` **失败绝不造假**、entitlement 判定 fail-closed（呼应 R07 [`provider_coordinator.go`]、R03 E-P2 身份门）。→ questor 04 §11 L1"策略输出不可信即拒"是 fail-closed 侧；C9 权限/凭据判定需逐点标注 open 还是 closed。
- **E-P3 观测/上报的节流窗**：选择逻辑在**每次模型调用**都跑，池空时未节流的日志"每次选择都打"，Windows 多进程共享一个带跨进程锁的 rotating log 会**风暴锁、钉住一核、卡住事件循环**（[`credential_pool.py:152-160`]）。→ questor observability 上报（heartbeat/usage_delta）须**带节流窗**，别在热路径无条件打点。

---

## 落到 04 / 02 / HARD 的具体增量清单（均为未决带 / 落地补充，不动已定接缝）

| 位置 | 增量（建议） | 关键证据 |
|---|---|---|
| **04 §5 工具轮 / error_stack** | 错误 verdict 从"可重试/致命"二值升级为**多恢复 hint**（retryable/compress/fallback/rotate）+ 稳定 `kind` 枚举；分类器=可插拔 hook、失败 fail-to-builtin | `error_classifier.py:69-94`、`460-490`、`703-763` |
| **04 §5/§6** | 分类须防**假阳性丢上下文**（词边界、oversized≠overflow、format_error vs overflow）；cause 链有界 5 层 | `agent_stream.py:59-70`、`1733-1742`；`error_classifier.py:226-249`、`1191-1198`、`1381-1392` |
| **04 §8 错误/fallback** | 定形：**primary 满预算重试 / fallback 每环一次**；退避**封顶**=传输空闲超时的函数；fallback **run 内粘、跨 run 复位**、subagent 继承；429 有备胎即切、或读 `reset_at` 骑窗口；**即时换链 vs 退避后换链**两档 | `agent_stream.py:154-157`、`1586-1590`、`1913-1920`、`1922-1940`、`1948-1967`；`fallback_cooldown.py:24-42`、`45-76`；`error_classifier.py:768-774` |
| **04 §8 / C7 reduce** | 冷却/失败隔离分三档：**transient(有界退避) / account(整链) / terminal(会话永久跳过)**；provider `reset_at` 覆盖默认；sole 凭据短冷却 | `credential_pool.py:131-140`、`373-400`、`469-481`；`credential_pool_model_cooldowns.py:1-8`、`17-19`、`61-75` |
| **04 §8 / 02 §3 run_failed** | 终态错误携带**整链失败摘要**（多条 {model/kind/message}）；带 `resumable:bool`（与 `retryable` 正交） | `agent_stream.py:1591-1594`、`1974-2004`；`mailbox.go:95-124` |
| **04 §4 流式** | 加**看门狗红线**：双超时（首 token / chunk 间）；keepalive 池下**代际栅栏+退役即失效**；有 finish_reason 后卡住=teardown 不升级 run_failed；mid-stream 取消只留文本不留半 tool_use | `auxiliary_stream_watchdog.py:1-9`、`40-43`、`56-62`、`79-113`、`122-132`、`159-180`；`agent_stream.py:1670-1694` |
| **04 §4 / 02 §3** | usage **不假设只在末块**；reasoning 字段多别名归一；**thinking 绝不进对外正文** | `agent_stream.py:1751-1757`、`1769-1779`、`1785-1802` |
| **04 §3/§5 / 02 §5 Cancel / C7** | `cancel_reason` **归因落到退出原因/事件文案、从记录派生不从调用点臆测**；取消**扇出工具 worker tid + 递归子 agent**、隔离到本执行线程；高并发下"代际/claim 栅栏"防误吞 abort；错误恢复**不擦已接受 steer** | `interrupt_control.py:18-45`、`54-70`、`106-123`、`139-145`、`184-191`、`209-227`、`238-265`；`interrupt_scope.py:1-10`、`34-57` |
| **02 §7 生长场景** | 预留更细终止粒度"**活动 turn 重定向**"：只掐模型请求、保留完成消息、纠正追加为真 user 消息；工具中降级 steer+yield、不为送指引杀工具 | `interrupt_control.py:280-341` |
| **02 §3 / 01 I7 / C13 X2** | 终态/工具事件配**稳定投递 id**，reduce/投递"claim-then-deliver"；**投递/claim 视图可从事件重放重建、不落第二份真相**；两阶段推进（父转录含 id 才 pending→followup） | `delivery.go:46-71`、`133-213`、`343-401`、`403-418`、`524-560` |
| **04 §7 / C10 回滚** | 终态意图**先 durable 后 ack**、ack 失败留 pending（带 schema 版本）；**优雅让位=移交 durable pending 屏障**，既不永久卡也不裸放未记录终态；durable 记录跨进程退出存活（配 OS lease） | `worker_terminal_ack.go:19-36`、`251-264`、`266-344`、`346-361`、`443-455` |
| **C6 / C10 / C14** | 错误/事件/日志载荷 **fail-safe 脱敏、绝不在日志路径执行凭据**；terminal grant 用 WARNING；跨进程"已重置"要显式 cleared-marker、add 后读回校验 fail-loud | `api_error_summary.py:201-223`、`228-237`；`credential_pool_plugin.py:80-105`；`credential_pool_admin.py:12-18`、`154-163` |
| **C14 观测** | observability 上报是**只读旁路投影**（sink 为 nil 即 no-op、不反改状态）；热路径打点**带节流窗**防风暴锁/钉核卡事件循环 | `failure_sink.go:8-93`；`credential_pool.py:152-160` |

## 与已定案的一致性（实扒正面印证，无需改）
- **04 §8"全走 Command/reduce，状态不被撕裂"** = hermes 分类器只产 hint、retry 循环消费、终止经命令不硬杀；中断最终发布走 activity-lock 临界区（D-P1）。
- **C5 / C10 / 04 X4"Event 发出不可撤回、回滚只回 Domain_State"** = wuu 明确不抑制重放、靠消费端幂等 claim 去重（E-1/E-2）；CowAgent 溢出"只重置内存上下文、持久历史保留"（E-5）。
- **C13"终态唯一、reduce 串行 first-writer-wins"** = wuu terminal finalization 以"确切 generation"durable 记录为权威、Deferred 不消费（E-3）；投递三态 committed/continued/deferred 天然互斥。
- **02 §9 E2 并发终止按优先级择一** = wuu `ClassifyError`/terminal outcome 单 owner + claim 互斥；hermes 优先级取消在 reduce 侧，实现细节可参照 D 主题。
- **02 §2 内部事件→外部投影** = CowAgent `model_fallback/message_end(cancelled|steered|empty_retry)` 具名结构化事件，即投影形状（D-5）。

## 冲突 / 需走 ADR 的分叉（别当免费）
- **F1 provider 重试在哪一层？** 04 §8 现写"Provider 错误→ProviderPort/LiteLLM 重试/fallback"。实扒三家**重试/fallback/冷却/链式换模型逻辑全在 agent 层**（hermes retry 循环、CowAgent `_call_llm_stream` 递归、wuu orchestrator 层 `ClassifyError`），而非 provider 内。**这与 C1"策略/能力层禁 import provider"存在张力**：若重试策略要读 error kind、驱动换模型，而 kind 来自 ProviderPort 返回的归一化错误——需明确**"分类归 ProviderPort/contracts，重试/fallback 编排归 Kernel(L2)"**，否则要么策略碰 provider、要么 provider 长出策略。→ 建议记 ADR：**错误分类=纯函数进 contracts（不 import provider 实现），重试/fallback 决策=Kernel**。
- **F2 看门狗掐 socket 是语言/传输特定。** hermes 靠 `httpx`+可拿到 raw socket+`_shutdown_socket` FD-safe（C-1/C-3）。questor LiteLLM+asyncio/SSE 无同等"从陌生线程安全掐本尝试 socket"的保证；连接池代际栅栏机制可移植，**实现别照搬**，需按 async 取消模型重设计（`anyio` cancel scope 之类）。
- **F3 exactly-once claim 账本是 P1+ 重活。** wuu 的 `EventResultReady/Claim/Release` 三事件 + 跨进程 CAS + 两阶段 pending→followup + durable terminal 屏障（E-1..E-4）是**分布式/多进程一致性**范畴（00 天花板、C12/C13）。v1 单进程内可先只做"**稳定投递 id + 消费端去重集**"，把 CAS/两阶段留 P10 加固或跨机时再启（呼应 04 X1"v1 关并行"式取巧）。
- **F4 冷却域（多凭据池 / per-model bench）对 questor 未必需要。** hermes 的 `credential_pool*` 是为**多 OAuth 凭据轮转**而生，questor BYOM 单用户场景可能只有一把 key。**借鉴的是机制**（transient/account/terminal 三档 + provider reset_at 覆盖 + fail-open/closed 语义），不是整套池。若 v1 无池，B-5 简化为"单凭据短冷却 + terminal 会话级跳过"即可，别把 3138 行池逻辑当必须。

## 未覆盖 / 存疑（诚实标注）
- `credential_pool.py`（3138）未逐行读全：仅读状态/TTL/冷却/DEAD/available 核心段（`80-520`、`1041-1075`、`1874-1910`）；`_available_entries`/`select`/轮转策略(fill_first/round_robin/random/least_used [`credential_pool.py:120-129`])、跨进程持久化合并、`_sync_entry_from_pool_store`、refresh 主流程未展开——若要"池轮转/failover 全序"细节需另份 R08b。
- hermes retry 循环本体（`run_agent.py` 消费 `ClassifiedError` 的 backoff/fallback walk/`restore_primary_runtime`）、`chat_completion_helpers._maybe_disable_streaming`（空帧→关流）、`retry_utils`（`parse_retry_after_seconds`/`reset_delay_from_message`）未读——本文只读到分类器**产出端**，退避**执行端**从 CowAgent/fallback_cooldown 侧面印证。
- CowAgent `_switch_to_fallback` / `_reset_model_fallback` / `_smart_compact_to_budget` / `_trim_messages` 的具体实现（在别模块）未读全，仅从 `_call_llm_stream` 调用点与 docstring 取其语义。
- wuu `delivery.go`/`worker_terminal_ack.go` 只读 agentcontrol 侧恢复协议，未展开 `threadStore.ClaimResultDelivery`/`AppendEvent`/CAS 底层（R03 B/E 已扫 agentthread store 层）。`worker_execution_lease.go` 未重读（R03 E-2 已覆盖 OS 文件锁租约与 durable 终态意图）。
- observability 只读到 failure_sink/mailbox 的**记录形状**与 credential 日志节流的**坑**，未扫 wuu `report.go`/`activity.go` 全量指标/trace 面；questor 若要"metrics/trace 上报协议"需补扫。
- 行号为扫描快照；后续以三家仓库 HEAD 为准；本报告不产码、未跑任何目标仓库构建/测试。

> **下一步（供决策）**：F1（分类进 contracts / 重试编排归 Kernel）是**唯一需先记 ADR** 的接缝，直接决定 C1 分层是否被重试逻辑击穿。其余 F2–F4 是"机制可移植、实现别照搬 + v1 取巧"的落地口径，可并入 04 §8/§10 与 C7/C10 脚注。A–E 的增量清单可直接喂 04 §4/§5/§8 扩写与 02 §3 run_failed 字段细化。
