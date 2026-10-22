# R01 · Turn 循环外部参考扫描（→ docs/design/04-turn-loop.md）

> 只读扫描，不改代码。目标：为 `04-turn-loop.md` 找**可采纳的阶段划分 / 终止权 / 护栏 / 续跑与死循环防护**。
> 证据项目：`hermes-agent-main`（Python，最完整）、`wuu-main`（Go，Kernel↔Policy 边界清晰）、`CowAgent-master`（Python，最简可抄）。
> 纪律：**只提"我们缺的/更优的"**，不复述 04 已有内容；每条带 `文件:行号`。全部读全实现（非抽样）。
> 状态：待评审采纳；采纳项回写 04 时按 04 现有 §编号对齐。

---

## ① 结论（增量总览）

04 现状已覆盖：阶段流水线 + 不可变 `_LoopState` + verdict、终止权在 Harness（C7）、流式瞬态、工具轮失败喂回、三条护栏（重复/续跑/工具面冻结）、turn 边界压缩+checkpoint、可插拔 PolicyPort、L1–X4 落地补充。**骨架方向对**，但相对三家实装，04 在**五个维度上偏薄或缺失**：

1. **终止权只建模了"强制停"，没建模"拒绝过早停"**——策略 `Finish` 被无条件接受；三家都把"过早收尾"当一类失败来防（stop-gates / 续跑护栏 / 耗尽兜底总结）。
2. **只有硬终止，没有"梯度软预警 + grace call + 耗尽强制总结"**——到点直接死，用户拿不到收尾物。
3. **护栏清单不全且口径粗**——"重复检测"只覆盖工具入参重复，缺**输出内容 runaway 重复**；"空响应"缺**分类轴**；缺**idle/进度看门狗**（与绝对 deadline 正交）；缺**会话级 turn 租约 + TTL**。
4. **死循环防护缺"退款型重启的封顶"**——凡 refund 迭代预算的重启（redirect/fallback/压缩）都必须"距上次产出的重启计数封顶、产出即归零"。
5. **§9 的 PolicyPort 太抽象**——wuu `loopdriver` 已给出可抄的 Kernel↔Policy 契约（LoopPolicy / Gateway / Create-Resume / 版本门控 checkpoint），直接对上 C11/ADR-0005/ADR-0008。

**取舍**：hermes 的体量来自极端健壮性（数十个 counter），v1 **不必全抄**；本文件把每条标注 `[P1]`（进 v1 骨架）/`[加固]`（P10 后补），只强推 `[P1]`。

---

## ② 各项目做法（证据）

### hermes-agent-main（阶段流水线 + 双向终止 + 护栏家族）

**阶段划分 / verdict**
- `_LoopState` 是一个**可变** dataclass，~50 字段，作为所有 phase helper 的入/出参容器（`agent/conversation_loop.py:1380-1461`）——不是"每阶段返回新实例"。
- `_run_phase(fn, agent, state, **extra)`：用 `inspect.signature` 按**形参名**从 state 取值喂给 phase，phase 返回一个 verdict dataclass，再把除 `action/result` 外的字段**按名拷回** state；个别字段"只 latch True 不回写"（`agent/conversation_loop.py:1476-1494`）。
- 主循环体是一串 phase 调用，每个按 `verdict.action ∈ {return, break, continue, fallthrough}` 分派（`agent/conversation_loop.py:1648-1706`）；重试子循环同构（`agent/conversation_loop.py:1497-1526`）。**verdict 是"每 phase 一个"，不是"每 turn 一个"。**

**终止权（多道闸 + 梯度预警 + grace）**
- 循环条件 = `api_call_count < max_iterations` **且** `iteration_budget.remaining > 0` **或** `_budget_grace_call`（`agent/conversation_loop.py:1648-1650`）。
- `begin_iteration` 出口顺序：pending redirect → interrupt(break) → review-input-budget(break) → 计数自增 → **grace call 消费一次**否则 `iteration_budget.consume()` 失败即 break（`agent/turn_iteration_prep.py:352-417`）。
- **迭代预算 checkpoint**：用到 `budget_warning_ratio`（如 0.9）时注入一次性提示"现在落盘进度，然后继续；**不要因为这条提示就停**"（`agent/turn_iteration_prep.py:41-99`）。
- **wall-clock 80% wrap-up 提示**：预算过 80% 注入"停止新探索，用已有状态产出交付物"（`agent/conversation_loop.py:124-156`）。
- **聚合输入 token 预算**（针对后台 fork）：在**下一迭代顶部**触发，让越界那次请求先跑完（`agent/conversation_loop.py:112-121`）。
- `_turn_exit_reason`：每次 break 都记录**退出原因**（diagnostic，`agent/conversation_loop.py:1432`；如 `agent/turn_iteration_prep.py:413,473,531,557`）。

**拒绝过早停（续跑/stop-gates 家族）**
- `apply_stop_gates`：verify-on-stop / `pre_verify` hook / kanban 终止工具守卫——模型想停时**追加一条合成 user nudge 继续**，并把候选答案留作"预算耗尽兜底"（`agent/turn_stop_gates.py:24-33,105-177`）。
- 无工具文本分支的守卫序（`agent/turn_final_response.py:162-342`）：stall（说要继续却没工具）/ degenerate-final（工具做完却以碎片收尾）/ intent-ack，**共用一个有界计数 `codex_ack_continuations < 2`**；dropped-toolcall（`finish_reason=tool_calls` 却空）重问**最多 3 次"连续"**、正常收尾即清零（`:289-321`）。
- incomplete-scratchpad（推理块开了没关=输出耗尽）重试 ≤2 后存为 partial 并回滚（`agent/turn_response_intake.py:160-177`）。

**护栏家族**
- **续跑**：`IterationBudget` 线程安全 consume/**refund**；parent(500)/subagent(50) 独立；`execute_code` 轮次 refund 回预算（`agent/iteration_budget.py:25-56`）。
- **输出重复 runaway**（非工具入参重复）：内容级 degenerate 检测 + `RunawayStreamWatch` 以**倍增间隔在流式途中**判停，completed 分支用 `STOP_PATH_MIN_CHARS=16000` 门槛放行"用户确实要的重复"（`agent/repetition_guard.py:53-70,141-194`）。
- **空答分类**：deterministic-empty（连续 2 次同 (model,provider,finish_reason) 且 usage 证 0 输出）→ **跳过剩余重试直奔 fallback 链**；cost-aware budget（单次成本超阈值 → 重试预算 3→1）（`agent/empty_response_guard.py:1-43,207-237`）。
- **idle/进度看门狗**：turn 静默卡死（lease 还在续期）→ 采样 idle 超 `timeout_s` → 带 `(generation, ts)` **重校验后再强制 abort** 并停 lease 续期；**休眠主机不计入 idle**（`agent/turn_liveness.py:1-8,90-148`）。
- **会话级 turn 租约**：跨进程独占会话租约 + refresher 线程；卡死时 `lease.stop_refresher()` → TTL 到期自然释放会话（`agent/turn_facade.py:3,83-97,144-204`；租约实现 `agent/turn_facade_lease.py`）。
- **deadline 原语**：`run_bounded_async/sync` 用 **daemon `threading.Timer`** 驱动墙钟，**事件循环被阻塞也拦得住**；超时**放弃**任务并 `mark_suspect` 让属主回收后端；`clamp_timeout` 修 macOS/Windows `time_t`/DWORD-ms 溢出（`agent/deadline.py:6-8,56-59,235-359`）。

**死循环防护（退款型重启封顶）**
- `apply_retry_restarts` 消费 4 个 restart flag；其中 **redirect 与 rebuilt-for-fallback 两条 refund 预算的重启**由 `restart_count > max_retries` 封顶，**一收到响应就 `restart_count = 0`**（"距上次产出的重启数"）；压缩重启计入 `retry_count`；length-continuation 走独立 output-cap 阶梯（`agent/turn_iteration_prep.py:437-567`；字段说明 `agent/conversation_loop.py:1415-1420`）。
- 外层逃逸异常计数 `_MAX_OUTER_LOOP_ERRORS = 8`（只有突破内层重试/兜底的异常才计）（`agent/conversation_loop.py:235-237,1421`）。

### wuu-main（Kernel↔Policy 边界 + 三条护栏的"精确定义"）

- **续跑上限**（04 §6 的直接出处）：`maxConsecutiveContinuations = 8`，注释即"坏掉兼容端点不得造无限计费循环"（`internal/agent/loop.go:20-22`）；判据只认**显式归一化的 `FinishReasonContinue`**，**空文本/旁白不算续跑信号**，非续跑即 `consecutiveContinuations = 0`（`internal/agent/loop.go:1013-1023`）。
- **空答分类**：`EmptyAnswerError{StopReason}` 携带 provider 结束信号（`internal/agent/loop.go:24-47`）；无工具且空内容时——正常 `Stop/Length` **视为合法收尾**（空文本但正常停，且不证明任务完成），否则返回 `EmptyAnswerError`（`internal/agent/loop.go:1026-1054`）。
- **工具面冻结**：`ToolSurfaceFreezer{Freeze,Unfreeze}` 在 run 起点 Freeze、defer Unfreeze，冻结 provider-facing tools 使 `req.Tools` 跨轮字节稳定不被 MCP 事件重塑；**模型主动的延迟加载不受冻结**（`internal/agent/loop.go:49-56,163-171`）。
- **压缩反抖**：proactive 压缩失败/空转一次即 `proactiveSuppressed`，本 run 不再自动 proactive（"不在无用的压缩器上空转"）；overflow reactive 每两个成功步之间至多一次（`internal/agent/loop.go:175-189,283-290`）；`resetTranscript` 是**任何历史重写后把 live history 与 provider transcript 强制对齐的唯一闸口**（`internal/agent/loop.go:261-278`）。
- **低预算一次性提醒**：`lowBudgetReminderSent` 用尽前提示"存进度→在安全边界 new_context"（`internal/agent/loop.go:216,592-598`）。
- **Kernel↔Policy 契约（可抄）**：`LoopPolicy{ModelRoundLimit,DisableTools,DisableCompaction}`；`KernelGateway.ExecuteModelLoop(input, LoopPolicy)→Receipt` + `WriteCheckpoint`；`Driver{Descriptor, Create, Resume}` / `Instance{Run, Checkpoint, Cancel(reason), Shutdown}`；`Descriptor.Capabilities`（`internal/loopdriver/contract.go:14-76`）。
- **版本门控 checkpoint/resume**：`Checkpoint{ContractVersion, DriverID, DriverVersion, State}`；`Resume` 先 `validateCheckpoint(descriptor, cp)`——**不同 driver/版本/契约不能静默错接旧断点**；phase 态 `ready→running→terminal`，每次跃迁都 `WriteCheckpoint`（`internal/loopdriver/contract.go:47-58`、`internal/loopdriver/default.go:33-37,50-92`）。
- **恢复挂账工具**：`StreamRunner` 里 LoopDriver 只拥 turn policy，runner 是 provider/tool-ledger/history/streaming 不变式的 kernel gateway（`internal/agent/stream_runner.go:172-176`）；从 `ToolLedger` 取 `PendingProjection`/`MarkProjected` 回填未完成工具结果（`internal/agent/stream_runner.go:709-724`）。
- `RunToolLoop` 顶格 doc 注释把循环行为写成一段规格、且声明**history 切片按不可变对待**（`internal/agent/loop.go:58-94`）。

### CowAgent-master（最简可抄的循环与取消）

- **单一 `while turn < max_turns`**，每轮顶部 `_check_cancelled()`（`agent/protocol/agent_stream.py:991-1004`）。
- **取消=安全点探针**：`cancel_event` 在 **turn 边界 / 工具调用之间 / LLM 流式途中** 三处检查，命中抛 `AgentCancelledError`；`_check_cancelled` 只是 `Event.is_set()`，廉价（`agent/protocol/agent_stream.py:369-377,1135-1141,1685-1697`）。**取消错误一律原样上抛、绝不当可重试**（`agent/protocol/agent_stream.py:1838-1840`）。
- **并行 × 取消**：并行预取用 `PARALLEL_POLL_SECONDS = 0.5` 周期醒来感知 cancel（`agent/protocol/agent_stream.py:47-48,1135`）。
- **耗尽兜底总结**：`turn >= max_turns 且非正常答完` → 临时注入"别再调工具、直接文字总结"的 prompt、以 `retry_on_empty=False` 再调一次（**避免总结也空转成环**），拿到总结后**把注入的 prompt 从持久历史里 pop 掉**，拿不到就回固定文案（`agent/protocol/agent_stream.py:1291-1335`；`finished_with_answer` 区分"答完"与"耗尽"见 `:988-989`）。
- **空答策略随"是否有人等"变**：`allow_empty_response`（无人等的 run）**允许静默**——nudge/fallback 文案不同（`agent/protocol/agent_stream.py:285-287,387-406`）。
- **pending 工具回填**：用户 redirect 时，未决 tool_call 全部回填 `is_error:True` + "Skipped because the user redirected the active task."（`agent/protocol/agent_stream.py:435-440`）；`_MESSAGE_FORMAT_MARKERS` 识别 provider 报的 tool 配对结构错（`:79-83`）。
- **退避封顶**：429 退避基础曲线 `30 + retry*15` **每次封顶 60s**，使累计睡眠在第 8 次重试前不超过 web 通道 600s SSE idle（`agent/protocol/agent_stream.py:154-157`）。

---

## ③ 对 04 的具体改法（仅增量/更优，标 `[P1]`/`[加固]`）

**G-1 终止权改为"双向 + 有出口标签" `[P1]`（改 §3、§2）**
- §3 现只写"任一到即终止、策略只能建议"。补第二半：**Harness 也可拒绝过早 `Finish`**——`Finish` 若满足"仍有 pending tool_call 未闭合 / 命中验证门（verify-on-stop）/ 尾部宣告了下一步却没工具（stall）/ 碎片收尾（degenerate-final）"之一，**不 finalize，改注入一条有界 nudge 续跑**，候选答案留作耗尽兜底（证 `hermes agent/turn_stop_gates.py:105-177`、`agent/turn_final_response.py:162-249`）。
- §2 `LoopState.verdict` 之外加 **`turn_exit_reason`**（diagnostic，每次退出置值）；并明确"answered / budget_exhausted / no_progress / interrupted / all_retries_exhausted"是不同退出（证 `conversation_loop.py:1432`、`turn_iteration_prep.py:413`、`CowAgent :988-989`）。此字段进 `run_failed/run_completed` 投影（呼应 02 §3）。

**G-2 补"梯度软预警 → grace → 耗尽强制总结"链 `[P1]`（改 §3）**
在硬终止前插三级：①预算到 `ratio`（如 0.9）注入一次性 checkpoint 提示"落盘后继续、别因此停"；②wall-clock 80% 注入 wrap-up 提示；③预算耗尽时给 **一次无工具 grace call**（`budget.grace_call` 置位、消费即退出）；④仍不收尾则**强制无工具总结**（注入临时 prompt→取总结→pop 掉，且该次调用**禁用空答重试**）。（证 `turn_iteration_prep.py:41-99`、`conversation_loop.py:124-156,1648-1650`、`CowAgent :1291-1335`）§2 `budget{}` 补 `grace_call` 标志与 `warning_ratio`。

**G-3 §6 护栏清单扩容 + 拆分 `[P1 拆重复/补看门狗，加固 其余]`**
- **拆"重复检测"为两条**：①工具入参重复（04 已有）；②**输出内容 runaway 重复**（模型回声）——且要**在流式途中**用倍增间隔 watcher 判停、completed 分支加字符下限放行"用户要的重复"（证 `repetition_guard.py:53-70,141-194`）。
- **空响应升级分类轴**：按 `finish_reason 正常/异常`（wuu 分合法收尾 vs `EmptyAnswerError`）、`usage.output==0` 连续同签名→跳过重试转 fallback 链（hermes deterministic-empty）、**单次成本超阈→重试预算 3→1**（cost-aware）、以及**"无人等则静默合法"**（CowAgent `allow_empty_response`）。（证 `wuu loop.go:1026-1054`、`hermes empty_response_guard.py:207-237`、`CowAgent :387-406`）
- **补 idle/进度看门狗**：与绝对 deadline 正交——"无进展 N 秒即 abort"，采样-重校验防竞态，**休眠/挂起主机不计入 idle**；复用 02 已有的 `heartbeat` 事件作进展信号。（证 `turn_liveness.py:1-8,90-148`）
- **续跑上限口径收紧**：明确"只认显式归一化的 continue 信号，空文本/旁白不算；非续跑即计数归零"（证 `wuu loop.go:1013-1023`）。

**G-4 新增"会话级 turn 租约 + TTL 兜底释放" `[加固]`（新增小节，接 §3）**
run 对 session 持**独占跨进程租约 + refresher**；卡死（看门狗判无进展）时**停止续租 → TTL 到期自然回收**，避免"半个 turn 永远占着会话"。归入并发/恢复里程碑。（证 `turn_facade.py:83-97,144-204`）

**G-5 §7/§8 补"退款型重启的封顶 + 压缩反抖" `[P1]`**
- 任何**返还迭代预算的重启**（redirect/fallback/压缩重建请求）必须有"距上次产出的重启计数"封顶、**一旦收到响应即归零**；另设"外层逃逸异常计数"上限。（证 `turn_iteration_prep.py:437-567`、`conversation_loop.py:235-237,1415-1420`）
- 压缩侧：**proactive 失败/空转一次即抑制本 run 后续 proactive**；overflow reactive 每两成功步至多一次；**任何历史重写走单一 `resetTranscript` 闸口**保证 live/provider 视图对齐（呼应 C2/配对）。（证 `wuu loop.go:175-189,261-278,283-290`）

**G-6 §9 用 wuu `loopdriver` 契约把 PolicyPort 具体化 `[P1]`（改写 §9）**
把"PolicyPort=注册进循环的一个实现"升级为一组可抄接口：`LoopPolicy{max_turns/model_round_limit, disable_tools, disable_compact}`、`KernelGateway.execute_model_loop(input, policy)→receipt` + `write_checkpoint`、`Driver{create, resume}`、`Instance{run, checkpoint, cancel(reason), shutdown}`、`Descriptor.capabilities`。**关键增量：checkpoint 记录 policy 的 (contract_version, driver_id, driver_version)，`resume` 先校验再放行**——把 C11/ADR-0005/ADR-0008 的"策略演进不炸旧断点"落到接缝。（证 `wuu loopdriver/contract.go:29-76`、`default.go:33-37,50-92`）

**G-7 §11 落地补充对齐参考证据（细化已有条，非新增维） `[P1]`**
- **L5 部分失败/回填**：明确 **cancel/redirect/failed 三类早退都要把 pending/running 的 tool_call 回填为 `is_error` + 原因**，保配对（呼应 C7 reduce 不变式；证 `CowAgent :435-440`、`wuu stream_runner.go:709-724`）。
- **X1 并行 × 取消**：v1 关并行仍应在文档里写清"启用并行时：并行预取要**轮询感知 cancel**（poll 周期）、恢复要**从 ledger 回填 pending 工具结果**"，别留白（证 `CowAgent :47-48,1135`、`wuu stream_runner.go:709-724`）。
- **X4 策略异常隔离**：补一句"**取消错误必须与可重试错误分流、绝不进 fallback/重试**"（证 `CowAgent :1838-1840`）。

**G-8 `_LoopState` 不可变性目标重述（现实校正） `[P1]`（微调 §2、§11-X3）**
参考实现里**循环内部态是可变的**（hermes `_LoopState` 是 ~50 字段可变 dataclass，`conversation_loop.py:1380-1461`）。建议 04 明确：**C2/COW 的不可变性只强加于 `Domain_State`（权威、可持久、回放）**；`LoopState` 是 per-turn 临时态、**不持久**（§11-L2 已这么分），可允许内部可变槽位，**但每 phase 用"返回 verdict + 按名拷回"解耦**（学 `_run_phase`，`conversation_loop.py:1476-1494`）。对"LoopState 整体 frozen"降级为**目标而非红线**，否则字段一多即不可维护（X3 的机器强制也应只针对 `Domain_State`）。

---

## ④ 失败模式（参考实现踩过的坑，04 应显式防）

- **F1 过早停被当成功**：reasoning-only 干净停 / 说继续却没工具 / 碎片收尾 → 循环报"完成"但任务卡死。无 stop-gate 即静默欠交付（`hermes turn_final_response.py:117-124,217-249`）。
- **F2 退款预算成死循环**：redirect/fallback 重启若 refund 迭代预算又无封顶，会**无限 refund 并一直占着 turn 租约**（hermes 为此补 `restart_count`，`turn_iteration_prep.py:437-547`）。
- **F3 输出 runaway 烧光预算**：退化回声把一个 60k 字符 turn 投成 31 条消息；无输出上限的端点能让模型**流到 turn 结束**（`repetition_guard.py:1-8,163-194`）——只在完成时检查不够，得**流式中判停**。
- **F4 重放回声自我再触发**：把 looped 字节当 api_content/占位行重放会**重新播下循环种子且跨重启存活**（`repetition_guard.py:25-29`）；早退的 assistant 占位行须用中性标记、不能塞脚手架文本（`conversation_loop.py:322-352`）。
- **F5 静默卡死死锁会话**：turn 中途无错卡住而**durable lease 仍在续期 → 会话永不释放**；且**笔记本休眠被误判为卡死**（`turn_liveness.py:1-8,113-114`）——需 idle 看门狗 + 休眠不计入 + 停续租 TTL 兜底。
- **F6 空答风暴重复计费**：portal 代理的隐性拒绝返回"成功/0 输出/泛 finish_reason"，naive 重试**每次重算整段输入**；cost-aware + deterministic-empty 才止损（`empty_response_guard.py:1-43`）。
- **F7 配对/角色交替破损→空转**：中断/redirect 留下 `assistant→assistant` 或孤儿 `tool_result`，多数 provider 返回空 → 空重试**转圈**（`conversation_loop.py:342-352`、`turn_iteration_prep.py:219-254`；wuu `repairLiveToolCallHistory` `loop.go:430-441`）；失败 turn 早退也要补一条 assistant 边界行保交替（`conversation_loop.py:1813-1854`）。
- **F8 取消被误重试**：`AgentCancelledError` 若被当可重试进 fallback/退避，会**违背用户停止**（`CowAgent :1838-1840`；C7 要求 reduce 区分取消来源）。
- **F9 压缩空转/撕裂**：反复 proactive 压缩但不缩 → 自旋；强制 trim 只在**确实变小**才再试（`wuu loop.go:175-189`）；压缩超时仍超限应**以带类型的恢复契约收尾、不再重发**（`conversation_loop.py:199-206,1135-1149`）。
- **F10 断点被不兼容策略错接**：旧 policy 产的 checkpoint 被新版本静默 resume → 状态错乱；**版本门控 `validateCheckpoint` 是唯一防线**（`wuu loopdriver/default.go:33-37`）。

---

## ⑤ 文档缺口（04 及关联文档需补/需对齐处）

- **D1 §2 `LoopState` 字段不足**：缺 `grace_call`、`warning_ratio`、`turn_exit_reason`、续跑计数器族（`consecutive_continuations / stall_counter / dropped_toolcall_retries / length_continue_retries / empty_retries`）、`restart_count`、`outer_error_count`、idle-progress 戳。这些是参考实现的**死循环防护工作面**（证 `conversation_loop.py:1410-1437`）。
- **D2 无"会话级 turn 租约" anywhere**：04 只讲 run，未讲"同会话两 turn 互斥 + 卡死 TTL 释放"；需在 ROADMAP 明确归属里程碑（证 `turn_facade.py:83-204`）。
- **D3 §3 无 idle/进度看门狗**：只有绝对 deadline；`heartbeat`（02 §3）已发但**无人当作 stall 信号消费**。
- **D4 §6 "重复检测"口径混**：工具入参重复 vs 输出内容 runaway 是两个不同检测器/阈值，应拆开各给判据。
- **D5 §6 空响应缺分类轴**：stop_reason/usage.zero_output/单次成本/是否有人等——四维都未提（现只"有界重试/兜底"）。
- **D6 §3 终止权单向**：无"拒绝过早 Finish / 保持运行"半部；无 grace/耗尽强制总结路径。
- **D7 §9 PolicyPort 太抽象**：无 `LoopPolicy` 字段、无 `Create/Resume`、无**版本门控 checkpoint**（须与 ADR-0005/ADR-0008、C11 交叉引用落地）。
- **D8 `cancel_reason` 枚举三处不一致**：04 §2 `null|user|timeout|resource|safety` vs 02 §5 `user|timeout|safety` vs C7"用户/超时/安全告警"；且都**缺 `no_progress`（看门狗）/ `budget_exhausted` / `no_response`**。需统一成一张 reason 表并被 `turn_exit_reason` 引用。
- **D9 §7 压缩/checkpoint 缺**：反抖抑制位、`resetTranscript` 对齐闸口、"reactive 每两成功步至多一次"。
- **D10 §11-X1 与 §5 有张力**：§5 说"parallel_safe 可并发预取"、X1 说"v1 关并行"——需写清 v1 到底放不放 parallel_safe，以及并行取消（poll）/恢复（ledger 回填）的补齐点。
- **D11 verdict 粒度未定**：§2 是"每 turn 一个 verdict(continue|return|break)"，参考实现是"**每 phase 一个 verdict**（含 fallthrough/continue/break/return）驱动 restart"。04 需明确取哪种（建议保留 per-turn 权威 verdict，但承认 phase 级有 fallthrough/continue/restart 语义）。

---

### 采纳优先级建议
- **进 v1（04 收口前就改）**：G-1、G-2、G-3（拆重复+补看门狗两项）、G-5、G-6、G-7、G-8 + D1/D8 字段与枚举对齐。
- **加固期（P10 后）**：G-4 租约 TTL、G-3 的 deterministic-empty/cost-aware 细节、runaway 流式 watcher 的完整判据。
- 上述均可回写 04 对应 §；触及 §9/checkpoint 的两条（G-6/D7）建议同步在 `docs/adr/0005`、`docs/adr/0008` 各加一行接缝约束。
