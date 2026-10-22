# R02 · 02-event-protocol.md 外部参考扫描增量报告

> **定位**：本文件是基于外部优秀项目实扒后的**增量评审报告**，不是权威契约本体；采纳项再并回 [`02-event-protocol.md`](../design/02-event-protocol.md)。
> **方法**：读全不抽样、只提增量与缺口、每条带 `文件:行号` 证据（对齐"外部参考扫描驱动的文档优化流程"）。
> **扫描面**：
> - CowAgent：`bridge/agent_event_handler.py`、`agent/protocol/step_writer.py`、`channel/web/core/channel.py`(SSE)、`channel/web/core/_common.py`(SSEStreamState)、`channel/web/api/chat.py`(Last-Event-ID)、`channel/web/api/openai_compat.py`
> - wuu：`internal/providers/types.go`(StreamEvent)、`internal/appserver/model.go`(`applyStreamEventLocked`)、`internal/appserver/server.go`(`sanitizeStreamEvent`/`sanitizeStreamLifecycle`)、`internal/appserver/protocol.go`(通知词汇表)、`internal/appserver/turn_handlers.go`(lease/seq)、`internal/agent/stream_runner.go`(版本闸门)
> - DeepCode：`core/events/{protocol,llm_events,parts,session}.py`、`app_server/protocol/{notifications,retry,codec,methods}.py`、`app_server/{peer,dispatcher,websocket,native_client}.py`
> - hermes：`agent/stream_delivery.py`、`agent/display.py`
>
> **五段结构**对应 02 的五个打磨目标：① 事件类型完备性 ② 内外分层投影 ③ seq/after_seq/resync ④ 版本兼容 ⑤ OpenAI 兼容投影。

---

## 1. 事件类型完备性

02 §3 外部事件 v0 有 15 个 type。外部实现普遍比这更完备，以下是**缺口**（只列 02 现在没有、且被≥1 个真实实现验证的）。

- **1.1 item 生命周期三件套缺 `item_started`/`item_removed`**
  02 §1 已把 `item_id` 列为"永不改名"关联键（L18），但 §3 事件集只有 `message_completed`，没有 item 的开/合/撤。
  证据：wuu `itemStarted`/`itemCompleted`/`itemRemoved` 是独立外发通知 `model.go:1378-1405`；provider 重连回滚时**显式发 `itemRemoved` 撤掉在途条目**`model.go:654-678,680-687`。
  增量：补 `item_started`、`item_removed`；`item_removed` 承载"部分输出被回滚/撤回"，供客户端精确删行而非整屏刷新（配合 §3-6）。

- **1.2 缺 `*_replace`（全量替换）**
  02 只有 `text_delta`/`reasoning_delta`。Responses 兼容 provider 会**整体改写**已流式文本。
  证据：wuu `EventContentReplace → agent_message_replace`（`item.Text = ev.Content` 直接覆盖累积）`model.go:714-734`；thinking 同理 `EventThinkingReplace` `model.go:754-773`。
  增量：加 `text_replace`/`reasoning_replace`（携 `item_id` 权威全量），并写明客户端语义="replace 覆盖此前累积 delta"。与 delta 同属 live-only（见 §3-3）。

- **1.3 `message_completed` 缺 `phase`，且"一轮一条 assistant"假设过简**
  证据：DeepCode `AgentMessagePhase(COMMENTARY|FINAL_ANSWER|UNKNOWN)` `protocol.py:85-90`；一轮可发**多条 commentary**(`AgentMessageCompleted`) 再一条 `AgentMessage(final_answer)` `protocol.py:93-130`；wuu 明示"流式 phase 是 provisional，只有 completion 才能把文本 promote 进 answer 区" `model.go:696-698`；hermes Codex `phase=commentary|analysis(hidden scratchpad)`、`show_commentary=false` 时 commentary 落到 reasoning 通道 `stream_delivery.py:124-146`。
  增量：`message_completed.phase` 一等；协议允许一轮多条 assistant 定稿（commentary*+final）；流式期间 phase 只作预览、不作定区依据。

- **1.4 `reasoning_delta` 缺 channel/source 维度**
  证据：DeepCode `ReasoningChannel(SUMMARY|PROVIDER_TRACE)`，且**raw trace 绝不投影为可见 Part** `llm_events.py:38-43`、`parts.py:132-136`；hermes 把 provider 内联 `<think>` 被 scrub 掉的文本**回退**投给 reasoning 通道、原生 reasoning delta 一到即停回退 `stream_delivery.py:319-323`。
  增量：reasoning 事件带 `channel(summary|trace)`+`source(native|inline-scrubbed)`；trace 默认不外投影（见 §2-2）。

- **1.5 缺 turn 控制生命周期（排队/插话/挂起）**
  02 §3 只有 `turn_started`。
  证据：wuu 通知 `turn/queued`、`turn/dequeued`、`turn/steered`、`turn/unsteered`、`turn/held` `protocol.go:162-166`；DeepCode 方法 `turn/enqueue`、`turn/steer` `methods.py:76-77`。
  增量：补 `turn_queued`/`turn_steered`/`turn_held`（用户在 run 跑动中插话改向），并配 §5 Command `Steer`/`Enqueue`。**这是 02 §7 生长场景完全没覆盖的"中途转向"维度。**

- **1.6 缺非致命 `warning`（终态失败之外的告警载体）**
  02 只有终态 `run_failed` + §0-3"未知 error 至少告警"，但没有"turn 存活的问题"这一档。
  证据：DeepCode `ErrorEvent.warning=true`"报一个 Turn 存活的问题…绝不表示 Turn 自身失败" `protocol.py:397-403`；wuu 通知 `server.warning` `notifications.py:6`。
  增量：加 `warning`（非终态、不阻断 run），正好作为 §0-3"告警"的具名事件载体，并与终态 `run_failed` 语义分离。

- **1.7 task/plan 事件宜带结构快照 + 迁移不变式**
  证据：DeepCode `PlanUpdated` 携带**全量 plan 快照**且强制"至多一个 in_progress"不变式 `protocol.py:188-240`（L236-237），且**工具与事件共用同一 parser 防校验/UI 漂移** `protocol.py:203-240`。
  增量：`node_updated` 明确语义（delta vs 快照），并在协议标注合法状态迁移不变式（呼应 01 §3 TaskNode 状态集与 I1 DAG 校验）。

- **1.8 `usage_delta` 应关联到具体模型回合**
  证据：DeepCode `ModelUsageRecorded.response_ordinal` `protocol.py:173-180`；hermes 每事件带 `iteration`(=api_call_count) `stream_delivery.py:282-290`。
  增量：usage 带 `response_ordinal`/`iteration`，区分"本轮第几次 provider 调用"，供成本归因与重试观测。

- **1.9 能力/配置热变更事件族比 `tools_changed` 更细**
  02 §7 只列 `tools_changed`。证据：wuu `skills.changed`/`plugins.changed`/`mcp.changed`/`settings.changed` `notifications.py:9-12`；DeepCode MCP OAuth 系列方法 `methods.py:43-45`。
  增量：`tools_changed` 加 `domain(skills|plugins|mcp|settings)`，或枚举为族。

- **1.10 缺 thread/session 级 lifecycle**
  证据：wuu `thread/started`、`thread/resumed`、`thread/updated` `protocol.go:158-160`。
  增量：补 `thread_started`/`thread_resumed`/`thread_updated`（`thread_resumed` 与 §3 重连语义直接相关）。

- **1.11 compact 应是事件族（attempt vs replacement）**
  证据：wuu `CompactPhase`/`CompactReason`/`CompactSummary`，且 summary **仅在真正重写历史的 completed 上出现、metadata-only 的 attempt 记录刻意不带** `types.go:768-775`；DeepCode 控制面 `/compact` `session.py:622-635`。
  增量：`compact_started`/`compact_applied`，`reason(auto|manual|overflow)`，区分 attempt 记录与 replacement（对齐 01 I2）。

---

## 2. 内外分层投影

02 §2 目前是**两层**（内部总线 → 显式投影层 → 外部事件集）。外部实现给出三条增量：**分得更细、投影更严、按表面二次投影**。

- **2.1 内部至少是三层，不是一层**
  证据：DeepCode 明确三层判别式并逐一说明 `core/events/__init__.py:1-18` —— **L0 provider-stream**（`llm_events.py`：每个 provider 归一到同一 union，"provider 怪癖绝不出边界" `llm_events.py:5-7`）/ **L1 message-parts**（可持久化的结构化投影 `parts.py:1-20`）/ **L1 SQ-EQ wire**（`protocol.py`）。
  增量：把 02 §2 的"内部事件"再分 **provider-stream 层** 与 **kernel-domain 层**，投影发生在 kernel-domain→外部。收益：换 provider 不牵动 kernel 事件（对齐 C1 变更域隔离、01 §0 只读视图）。

- **2.2 投影 = 字段白名单 + 可见性位 + 深拷贝**
  02 §2 说"字段白名单 + 截断"但无 `hidden`、无拷贝语义。
  证据：wuu `sanitizeStreamEvent` 逐字段白名单拷贝，且 **`ev.Message != nil && !ev.Message.Hidden` 才外投**（隐藏消息根本不进外部 payload）`server.go:1301-1348`（L1307）；`ToolResultDetail`/`AgentActivity` 外投前 `Clone()`/值拷贝 `server.go:1316-1326`。
  增量：外部事件可带 `hidden`/可见性位；投影产物必须是**脱离内部实例的拷贝**——内部对象后续 mutate 不得改到已发事件（这是 C2 不可变在事件边界的落点）。

- **2.3 raw 字段与 normalized 字段双轨**
  证据：wuu `StopReason`(raw-ish provider 细节) 与 `FinishReason`(normalized 语义) 并存 `types.go:787-791`；`ProviderEventType` 保留 provider 原始终态事件仅用于更严格完成校验 `types.go:781-783`。
  增量：外部契约的语义判定**只允许依赖 normalized 枚举**；raw 字段仅观测、禁入兼容判定（防 provider 细节渗进外部契约）。

- **2.4 投影层按 surface 做二次呈现裁剪/合并（fan-out）**
  02 §2 只说"外部=精简稳定集"，未提"精简集之上每表面还各自裁剪"。
  证据：CowAgent 同一内部事件按通道分策略——微信侧 `WEIXIN_THINKING_INSTANT_MAX=7` 超限即缓冲合并 `agent_event_handler.py:8,99-114`；`reasoning_update` 对 channel 直接丢弃 `agent_event_handler.py:45-46`。hermes 一个 delta fan-out 到 display + TTS 两 sink `stream_delivery.py:33-36`；事件带 `surface` 字段 `stream_delivery.py:282-290`。
  增量：明确"外部事件集(稳定) → 每 surface 再投影(呈现层)"的两级；信封带 `surface`；IM 合并限流是投影层职责而非内核简化（呼应 X5"内核不为兼容面简化"）。

- **2.5 展示语义 ≠ 协议语义（反面确认分层纪律）**
  证据：hermes 的"reasoning/analyzing…"是**终端 spinner 的 cosmetic 动词**（本地皮肤/语言配置生成），非任一协议事件 `display.py:846-868`；`render_edit_diff_with_delta` 把工具结果里的结构化 diff 在展示层渲染 `display.py:811-824`。
  增量：02 §2 可补一句红线——**表面呈现派生态（spinner 文案、diff 高亮、进度条）不得回写成协议事件字段**，工具结果可带 `display`(给人)与 `result`(给模型)分离载荷（01 §4 已有，强调不外泄派生展示逻辑）。

---

## 3. seq / after_seq / resync（续传与回放）

02 §4 + §9 E1/E2/T2/X2 已有骨架。外部实现把 resync 从"游标过期回一个 resync_required"**细化成有因、有界、分通道**的机制。

- **3.1 `resync_required` 必须分因（≥3 种），且带权威边界 seq**
  证据：CowAgent 两因——`cursor < first_seq-1`→`reason:event_cursor_expired` 带 `first_available_seq`；`cursor > latest_seq`→`reason:event_cursor_ahead` 带 `latest_available_seq` `channel.py:1327-1340`；进程重启内存态丢失→`error reason:unknown_request` `channel.py:1288-1296`。
  增量：02 §4 把 resync_required 从"游标过期"扩为 `{reason ∈ expired|ahead|unknown_request|version_mismatch, after_seq, first/latest_available_seq}`；expired→从 first_available 续、ahead/unknown→全量重放快照。比 E1"丢弃 UI 态+拉快照+重订阅"更精确（客户端能判"续"还是"重放")。

- **3.2 有界重放窗 + "保最新一条" + 明确回放源**
  证据：CowAgent 重放缓冲双上限 `SSE_REPLAY_MAX_EVENTS=5000`/`SSE_REPLAY_MAX_BYTES=4MB`，裁剪时"**即使最新事件单独超限也保留至少一条**"，越界由 stream_response 显式报游标过期 `channel.py:50-54,112-120`。
  增量：02 §4 定重放窗策略（max_events+max_bytes、保底一条）。**并明写 questor 差异优势**：因走事件溯源持久层（01 §9/§11 append-only `events`），回放源是 `events` 表而非进程内存，**重启仍可续传**——这是相对 CowAgent（重启即 `unknown_request`，日志只在内存 `channel.py:1288-1292`）的增强点，要写进 02 免得实现退化成内存态。

- **3.3 seq 只编号 durable 事件；delta/heartbeat/keepalive 不占 seq、不进续传游标**
  证据：DeepCode 通知 `item.delta` 注释直言"**Streamed text, live only: offsets instead of a durable sequence**" `notifications.py:4-5`；wuu 外发 delta 通知 params 只有 `ThreadID/TurnID/ItemID/Delta`，无 seq `model.go:705-713`。
  增量：02 §3/§4 明确 **`seq` 仅覆盖"状态类"事件**；`*_delta`/`*_replace`/`tool_progress`/`heartbeat` 属 live-only、走 item 内 offset、**不参与 `after_seq` 续传游标**；回放=重放 durable 事件再投影，delta 由重放重新生成（呼应 X2/I3）。

- **3.4 传输保活 ≠ 应用 heartbeat**
  证据：CowAgent 用 SSE 注释行 `: keepalive\n\n` 做传输保活，**不产事件、不占 seq** `channel.py:1367`。
  增量：区分"传输层 keepalive(注释帧)"与"应用层 `heartbeat`(长任务、可选、live-only)"。

- **3.5 语义终态 vs 传输关闭分两个标记 + "取消尾窗"**
  证据：CowAgent `done`(内容定稿，置 main_done) 与 `stream_end`(传输终止) 分离 `channel.py:122-128`；**Cancel 只在下个 checkpoint 生效，run 还会继续吐尾事件（工具结果/部分回复）**，流因此延长 `CANCEL_GRACE_SECONDS=60` 而非立刻断 `channel.py:1303-1307,1380-1382`；卡死兜底：`main_done` 后超 `SSE_POST_DONE_TAIL_SECONDS` 强制 `stream_end` `channel.py:1317-1323,1353-1357`。
  增量：02 §3/§9 补——(a) 终态事件(run_completed) 与传输终止(stream_end sentinel) 是两个标记；(b) **收到 `run_cancelled` 不代表流结束，客户端须读到 stream_end 再关**；(c) 到尾窗上限强制 stream_end 防悬挂。直接细化 E2/T2。

- **3.6 背压/溢出 → replayRequired，且区分 notification(可丢) vs event(必可回放)**
  证据：DeepCode 队列溢出→`{code:NOTIFICATION_QUEUE_OVERFLOW|EVENT_QUEUE_OVERFLOW, dropped:n, replayRequired:true}` `peer.py:186-210`；单帧过大→`NOTIFICATION_TOO_LARGE`+replayRequired `peer.py:300-310`；"**溢出即断开该客户端**，绝不静默丢回复；durable 事件仍可回放" `websocket.py:34-37`；回放按 `sequence` **二分找"能塞进一帧的最大前缀"** `peer.py:260-300`。
  增量：02 §4 加溢出/超限处理——回 resync_required 携 `dropped`+`last_durable_seq`；回放分页按帧大小裁剪；**丢 live notification 不应触发全量 resync（只丢呈现），丢 durable event 才 replayRequired**。

- **3.7 Command 受理即占 durable seq：早失败也要能落终态**
  证据：wuu `userMsgSeq`=该 turn 用户消息的持久 seq（0=未持久），"**让 prelaunch 失败也能记一个 durable terminal state**" `turn_handlers.go:93-95`；`afterLease` 在**durable lease 取得且磁盘刷新后**才跑副作用、`beforeUserAppendLocked` 的 commit 回调"**仅在用户消息 durably appended 之后**"运行 `turn_handlers.go:106-115`。
  增量：02 §5/§4 补——Command 受理即分配 durable seq（无 provider 调用也能发 `run_failed`）；Event 严格是"状态已持久化之后"的产物（C5 的落地时序）。

- **3.8 历史重写(压缩)要有 baseline-seq 栅栏**
  证据：wuu `HistoryBaselineSeq`="本 turn 在受理时拥有的最后一条 durable 记录"，**整段重写保留其后追加的所有记录，并把并发追加排到模型结果之后** `turn_handlers.go:131-134`；DeepCode 压缩只动 resident 上下文、canonical log 恒 append-only 不受影响 `session.py:622-635`。
  增量：02 §3/§4 补——压缩/整段重写发一个以 baseline_seq 为界的事件；重写后的续传/回放以 baseline 为界，重写期间并发用户追加排序在模型结果之后，避免撕裂游标。

- **3.9 重连时"恢复不留痕" + 在途条目 upsert 单行**
  证据：wuu provider 重连——(re)connect 成功即 `itemRemoved` 撤掉 reconnect 行"**恢复不在消息流留痕**" `model.go:679-687`；重试"**更新同一行而非每次 attempt 叠一行；每次更新重发 item/started（渲染端在 started 与 completed 都 upsert）**" `model.go:945-948`。
  增量：02 §9 T2 细化——瞬态/reconnect 行按 `item_id` **upsert**（started 即更新），成功即 removed；客户端不得把每次重试叠成多条。

---

## 4. 版本兼容与协商

02 §1/§6/E4 有"`v` 只增不改 + data 内嵌同受管 + schema 快照 diff"。外部实现给出**续传处版本闸门、能力协商、Command 幂等**三块缺口。

- **4.1 续传/回放前做版本闸门，不符即拒（而非猜测）**
  证据：wuu 从 checkpoint 续跑时校验 `ContractVersion + DriverID + DriverVersion` **全等**，任一不符**直接拒绝 resume 并打印 required vs active** `stream_runner.go:261-271`。
  增量：02 §4/§6 加——`after_seq` 续传/回放前**校验持久事件流的 `v`**，不符回 `resync_required(reason=version_mismatch)`，**禁止用新版本解释旧事件**（正是 C11"后期大范围迁移历史断点/事件"要防的）。

- **4.2 `v` 拆成"契约版本"与"策略/产生者版本"两条线**
  证据：wuu `loopdriver.ContractVersion`(kernel 契约) 与 `descriptor.Version`(策略驱动) 是两条独立版本 `stream_runner.go:261-269,312-314`；LoopDriver 只管 turn policy，kernel 是"provider/tool-ledger/history/streaming 不变式的网关" `stream_runner.go:173-176`。
  增量：02 §1/§6 明确 **契约版本 ≠ 策略版本**——后者随 04 多策略变体演进；C11"跑通 2-3 策略"= 多策略版本共用一个稳定契约版本，事件里应能同时带二者。

- **4.3 加 initialize/capabilities 协商（运行期能力发现）**
  证据：DeepCode `initialize` 返回 `capabilities{methods, eventReplay:true, liveEvents:true, maxMessageBytes}` `dispatcher.py:379-383`。
  增量：02 §4/§6 补一次性握手——客户端据此知服务端是否支持续传/回放/心跳/最大帧，把"版本兼容"从静态 schema diff 升级为**运行期能力发现**。

- **4.4 Command 幂等键 + "默认不自动重放"（输入侧兼容缺口）**
  证据：DeepCode `retry.py` 文件级铁律"**未列出的操作绝不重放**，`default:"never"`"，只有 `READ_METHODS` 白名单可自动重放；`KEYED_METHODS` 给变更方法配幂等键 `turn/start→messageId`、`automation/run→requestId` `retry.py:1-61`；连"像读但昂贵"的 `dictation/transcribe` 也刻意不自动重放（须用户重发）`retry.py:20-21`；`native_client`"**无隐式变更重放或回退**" `native_client.py:66`；重连安全方法白名单 `initialize/shutdown/event-replay/thread-read` `websocket.py:108-112`。
  增量：02 §5——**每个 Command 携客户端幂等键，reduce 依它去重**（把 E3 局部规则升为通用铁律）；声明"仅标注为只读/幂等的操作可自动续传重放，变更类默认不重放"；昂贵/有副作用即使像读也不自动重放。

- **4.5 编码红线入协议：禁 NaN/Infinity + 尺寸/UTF-8 上限**
  证据：DeepCode codec 校验 `jsonrpc=="2.0"`、`allow_nan=False`（绝不产 NaN/Infinity 破坏 JSON.parse）、`DEFAULT_MAX_MESSAGE_BYTES=1MB`、UTF-8 解码守卫、`RecursionError`(整数长度守卫) `codec.py:12-56`；wuu `MaxStreamEventBytes=16MB` 防上游无限响应耗尽本地内存 `providers/stream_limits.go:6-8`。
  增量：02 §6/§8 编码规则补——**禁 NaN/Infinity、单事件与单帧字节上限、UTF-8 校验**。

- **4.6 投影期主动剥离旧 wire 的新字段（不只靠"未知忽略"）**
  证据：DeepCode `serialize_event` 对旧 CLI 消费者**pop 掉 `message_id`/`phase`**、保 `{"id","msg"}` 老形状，`submission_id`(内部相关字段)只有"版本化 caller 显式 opt-in"才发 `protocol.py:448-470`。
  增量：02 §6"只加"细则补一句——**投影层对声明为旧 wire 的消费面主动剥离未承诺字段**，而非一律依赖"未知 type 静默忽略"；把"内部相关字段"与"外部 wire 字段"分目录，兼容转换在投影层做（对齐 §2-2）。

---

## 5. OpenAI 兼容投影

02 X2 定"OpenAI 兼容=投影适配器，内核不为它简化"。CowAgent `openai_compat.py` 是唯一把这条落成完整可运行代码的样本，给出**扩展位命名空间、无原生续传、终态映射、工具/usage/会话口径**四类增量。

- **5.1 扩展位命名空间：标准形状不动，专有事件进 `cow_event`**
  证据：CowAgent 每块都是标准 `object:"chat.completion.chunk"`，非 OpenAI 语义的事件（reasoning/tool/error/subagent/artifact）统一塞进**独立字段 `cow_event`** `openai_compat.py:255-278`（L276-277）/`445`/`450`；生长事件原样透传并把 `chunk_type` 改名 `type` `_PASSTHROUGH_EVENTS=("subagent_step","artifact","peer_start","peer_end")` `openai_compat.py:36,336-339`。
  增量：02 X5/§5 定"映射表"——**标准字段走 OpenAI 语义，questor 专有事件收进一个扩展对象（如 `x_questor`）**，普通 OpenAI 客户端忽略扩展仍可消费；比"只映射子集"更完备（工具/审批/usage 明细可带而不破兼容）。

- **5.2 OpenAI 通道不保证续传：无 SSE `id:`、断连即取消、整段重发**
  证据：OpenAI 兼容流**不发 `id:` 行**、只 `data:`+尾 `data:[DONE]` `openai_compat.py:343-344,567`；`_encode_stream` 在客户端断开时 `close()` 源流→**取消该 completion** `openai_compat.py:650-658`——与 native web SSE"**断连保留事件日志供 Last-Event-ID 重连**" `channel.py:1385-1387`、`chat.py:45-63` **正好相反**。
  增量：02 §4/§5 **按通道声明 resync 能力**——OpenAI 兼容通道用 `[DONE]` 终结、无游标，断连=取消、客户端整段重发（呼应 4.4 default-never）；不得假设"所有表面都能 after_seq 续传"。

- **5.3 终态/错误映射：OpenAI 无独立错误事件，错误编进 finish_reason**
  证据：CowAgent 收尾发 `finish_reason:"stop"`(正常)或`"error"`(失败) 的尾块再 `[DONE]` `openai_compat.py:497,507,552,567`；**失败不发独立 error 事件，而是 `finish_reason:"error"` + `cow_event{type:"error",message}`** `openai_compat.py:508-519,528-543`；worker 异常也归一成一个 SSE error 帧 `openai_compat.py:465-467`。
  增量：02 §5 定终态映射表——`run_completed→finish_reason:stop+[DONE]`；`run_failed→finish_reason:error + 扩展 error 体`；`run_cancelled→OpenAI 无原生 cancelled，用约定值/扩展表达`。明确"OpenAI 没有独立错误事件"这一投影约束（且 §0-3"错误类不静默忽略"在 OpenAI 面靠 finish_reason 承载）。

- **5.4 delta/定稿在 OpenAI 形态的落点**
  证据：`content` delta→`choices[].delta.content` `openai_compat.py:434-437`；reasoning 同时落**非官方但生态约定的 `delta.reasoning_content`** + `cow_event` `openai_compat.py:438-447`；定稿 message_completed **不重发**（OpenAI 无此事件，靠累积 content 重建）；usage 走 `stream_options.include_usage` 才发的末帧 `choices:[],usage` `openai_compat.py:221,555-567`。
  增量：02 §5 映射补 `text_delta→delta.content`、`reasoning_delta→delta.reasoning_content`、`usage_delta→末帧 usage(仅 include_usage)`；定稿事件在 OpenAI 面无对应、由客户端累积重建。

- **5.5 工具/子 agent 事件投影 + 重复投递按 id 去重**
  证据：`_ToolEvents` 一次调用报 `tool_start` 与 `tool_result` 两报，**turn 收尾批次对已报 id 去重**（`_finished` 集）`openai_compat.py:281-340`（L319-335）；非流式路径同样只留 tool_result 聚合 `openai_compat.py:576-647`。
  增量：02 §5——工具事件要么归并进标准 `delta.tool_calls`、要么进扩展位；**重复投递按 tool_call_id 去重**（呼应 T2/E3）；subagent/artifact 透传进扩展命名空间，不污染标准 `choices`（给 §7 生长场景补 OpenAI 面投影）。

- **5.6 会话态映射 + usage 口径 + 兼容面仍需同会话串行**
  证据：`conversation_id`→服务器持历史，否则 `transcript` 自带 + `ephemeral`(不入库不驻留) `openai_compat.py:200-211,395-397`；`_openai_usage` 把 provider usage 归一为 `prompt/completion/total_tokens` + `prompt_tokens_details.cached_tokens` `openai_compat.py:234-252`；**sharded session lock 串行化同会话** `openai_compat.py:347,454`。
  增量：02 §5 说明 run/session 映射（`conversation_id≈session_id`、`completion_id≈run_id`），usage 走 OpenAI token 口径+cached 明细放 details，并强调**兼容面仍须同会话串行**（不因 OpenAI 简化破 C2 单写者）。

- **5.7 兼容面的活性/超时预算要显式**
  证据：CowAgent `_FIRST_EVENT_TIMEOUT_SECONDS=30`、`_STREAM_IDLE_TIMEOUT_SECONDS=600`（"匹配 web SSE 流…否则停滞的 run 永远占住消费者并持锁"）`openai_compat.py:30-33,483-489,522-544`；有界队列 `maxsize=256` + publish 重试做背压 `openai_compat.py:419-430`。
  增量：02 §5 补——OpenAI 兼容适配器须自带首事件/空闲超时与有界背压，停滞即产 error 帧并取消 run、释放会话锁。

---

## 附 · 采纳汇总（供并回 02）

| 增量 | 目标段 | 并入 02 的位置 | 强度 |
|---|---|---|---|
| 1.1 item_started/removed · 1.2 \*_replace · 1.3 message.phase+多条 · 1.4 reasoning.channel/source · 1.5 turn_queued/steered/held · 1.6 warning · 1.11 compact 事件族 | §1 | §3 外部事件表扩列 | 中（完备性） |
| 2.1 内部三层 · 2.2 hidden+深拷贝 · 2.3 raw/normalized 双轨 · 2.4 按 surface 二次投影 | §2 | §2 投影层细化 | 高（架构分层） |
| 3.1 resync 分因带边界 seq · 3.3 delta 不占 seq · 3.5 终态 vs stream_end+尾窗 · 3.6 溢出 replayRequired(分 notif/event) · 3.7 受理即占 durable seq · 3.8 重写 baseline 栅栏 | §3 | §4 传输 + §9 E1/E2/T2/X2 | 高（续传正确性） |
| 4.1 续传版本闸门 · 4.2 契约版本≠策略版本 · 4.4 Command 幂等键+default-never · 4.5 禁 NaN/尺寸上限 | §4 | §6 兼容 + §5 Command 集 | 高（C11/C6/C5） |
| 5.1 扩展位命名空间 · 5.2 OpenAI 面无续传·断连即取消 · 5.3 错误编进 finish_reason · 5.4-5.6 映射表 | §5 | X2/X5 + 新增"兼容映射表" | 中（投影适配） |

**不建议采纳（保持 questor 现有更严/更简的取舍）**：
- 不引入 wuu `turn/event` 这种"万能事件袋"（`protocol.go:167`）——questor 带类型总线要求每 type 显式，退化为泛型 event 会破 §6 兼容快照测试。
- 不照搬 DeepCode **per-session** `_seq`（`session.py:475,491-499`）——questor 定 `seq` 为 **per-run 单调**（02 §1），跨 run 续传另有 run_id 限定；采纳前需 ADR（触 C11 接缝类改动）。
- OpenAI 兼容面的 `finish_reason:"error"`（`openai_compat.py:507`）只作投影层映射，**内核仍用 run_failed/run_cancelled/run_completed 三终态**，不因兼容面把错误压成一个 finish_reason（守 X5"内核不为它简化"）。

**与红线挂点**：2.2/3.3/3.7→C2/C5；3.1/3.6/4.1→C6/C11；4.4→C5/E3；5.6→C2（兼容面串行）。均为**接缝细化**而非新增接缝，不触"信封/关联键/终止序"三根硬骨（02 §7）。
