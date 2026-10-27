# ADR 0009: 主动运行时与第二回合类型（proactive runtime）

- Status: Accepted (design; implementation in waves)
- Date: 2026-10-27
- Deciders: Questor maintainers

## Context

[ADR-0008](0008-profile-driven-modes.md) 已立"一种产品两种形态"，`personal.yaml` 的
`runtime` 段三个能力位（schedule / delivery / memory_consumption）**只立位、值全
off、无消费方**（0008 Decision 第 7 条、`src/questor/profiles/personal.yaml:29-33`、
`questorharness/profiles/loader.py:34`）。个人形态要成立，agent 必须能在无人输入时
正确地动一次：定时提醒、订阅推送、后台任务汇报。这些回合与"用户打字触发"的回合有
本质差异，但当前回合模型里**没有第二回合类型**——全仓 `turn_kind` 0 命中，
回合入口 `engine/query.py:45 run_query` 的请求侧无法区分"谁让这一回合发生"。

三件事因此无处安放：

1. **观测与归因**：工具调用台账与成本归因无法区分被动回合与主动回合；
2. **门控**：主动出话没有准入判定器——`capabilities/policy/checker.py:75 evaluate()`
   只判工具权限（输入仅 tool_name / is_read_only / file_path / command），没有
   "该不该开口"的语义；
3. **溯源**：主动消息没有强制证据字段，无法指回来源记忆或触发任务。

同时必须守住既有裁决：事件/帧只加不改（[ADR-0006](0006-serve-host-and-wire-protocol.md)
帧集口径）、`kernel/` 为 durable 保留不建（[ADR-0002](0002-target-structure.md)
Decision 第 3 条）、没有真实消费者的 Port 不建（ADR-0002 Decision 第 13/17 条）。

## Decision

1. **第二回合类型 `turn_kind`**：`user | scheduled | proactive | worker` 四值，
   载体 = 回合入口 `engine/query.py:45 run_query` 的请求侧（additive，缺省
   `user`，旧调用方零改动）。`scheduled` = 定时/cron 触发；`proactive` = 主动运行时
   自主发起；`worker` = swarm/子代理内部回合。台账、成本归因、触发层、守门器全部
   按此字段分流。

2. **主动事件族 additive 进 `contracts/domain/events.py`**（现为 7 类 StreamEvent
   联合，`events.py:82-90`），落在 ADR-0006"只加不改"窗口。本 ADR 只定事件族
   语义——**触发 → 门控判定 → 投递或跳过（跳过必须可观测）**；具体事件类名、wire
   帧编码与前端消费在计划 04 的 A6 刀与 thinking 帧同刀落地（模型可见面集中改，
   一刀对齐 prompt_surface 与 golden 基线）。现有消费面
   （`bootstrap/hosts/serve/wire.py:250`、`bootstrap/hosts/app.py:118`）按 additive
   惯例扩展。

3. **主动消息强制 evidence**：每条主动消息必须携带可指回的证据——来源记忆 id
   （[ADR-0004](0004-memory-provider-contract.md) 八方法 `search`/`get` 的返回）或
   触发任务 id；无 evidence 的主动消息不得通过守门器。此条与 ADR-0004 不变式
   （"召回失败不阻塞 turn；写入失败进 outbox"）正交：evidence 是出站侧约束，不改
   记忆读写契约。

4. **档位 = 参数组而非开关**：低/中/高各一组阈值（每日预算、安静时段、最小间隔、
   冷却、去重窗口）。**档位定义与数值是产品数据，落 `src/questor`**；准入求值器是
   引擎机制，落 `capabilities/policy`，注入照产品侧既有样板
   （`gateway/gateway_process.py:69` 的 `managed_group_checker` 注入模式），不新增
   依赖边。`personal.yaml` 三个 runtime 位即这些消费方的开关位，逐键给档。

5. **投递走既有通知链**：首个后端沿用 `gateway/notify.py:81 register_handlers`
   注册的 `feishu_dm`（`:103`；分片 `_chunk_text` 在 `:20`）。守门器判定在投递之前，
   投递晚于回合提交（行为时序归计划 04 的 A2 刀，不属本 ADR）。

6. **边界**：不建 `kernel/`、不改会话存储格式（journal/快照归
   [ADR-0010](0010-journal-write-order.md)）、不动 `runtime/swarm` 多 agent 拓扑、
   UI thinking 帧不在本 ADR 范围。

## Alternatives considered

- **全局一档开关（主动 开/关）**：拒绝。单参数档无法表达"预算/时段/冷却"的联动，
  且主动行为研究的一致结论是"最克制档并非最优"——正确形态是可调参数组，用户要的是
  分寸可控，不是不说话。
- **裸模型触发（把"要不要主动"交给模型自由发挥）**：拒绝。无门控触发的误报率过高；
  触发层必须过确定性判定，宁保守、跳过可观测，反馈可降档。
- **durable spine 一并立项**：拒绝。ADR-0002 Decision 第 3 条已冻结：要引入必须
  先单独 ADR + 预算 + 排期。存储格式走 ADR-0010（只起草，实施在 B0）。
- **主动运行时新开包**：拒绝。判定机制归既有 `capabilities/policy`，触发归既有
  `capabilities/schedule`，投递归既有 `gateway`/`notify` 链——没有哪块职责需要
  第五个包。

## Consequences

- 变容易了：台账、归因、门控、触发四条线共用同一个 `turn_kind` 分流字段，不必各自
  发明"这是不是主动回合"的判定；主动能力位的消费方有了唯一登记处。
- 变难了：每条主动路径必须带 evidence 且跳过可观测，主动行为的实现成本高于被动
  路径——这是有意为之的摩擦。
- 必须保留：`/profile` 帧不扩 runtime 键（ADR-0008 Decision 第 7 条）；事件与帧
  只加不改（ADR-0006）；`kernel/` 不建（ADR-0002）；产品持档位数据、引擎持求值器
  （ARCHITECTURE 反转点纪律）。

## Verification

- 本 ADR 无代码；实施判红挂 [计划 04](../plan/04-personal-readiness.md) 的三张
  对账表，各实施刀自带红用例。
- 文档守卫：可达性（docs 索引传递闭包）、死链、反引号代码路径由
  `scripts/guards/check_doc_cross_refs.py` 强制。
- 后续实施刀的锚点判红（登记在计划 04）：主动回合必带 `turn_kind`；无 evidence 的
  主动消息被守门器拒绝；配额耗尽静默跳过且跳过记录可查。
