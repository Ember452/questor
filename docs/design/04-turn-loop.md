# Questor Turn 循环骨架（L2 Kernel）

> 承接分层(00)、状态(01)、事件(02)、工具(03)、红线。设计文档，非实现。
> 设计要点：**阶段流水线 + 显式 `_LoopState` + verdict**，配**护栏**（续跑上限/空答分类/工具面冻结）。Harness 是引擎，**只调度不思考**。

---

## 0. 定位
- Harness 驱动循环；**每轮向 `PolicyPort` 要一个意图**（单步，见 ADR-0004/0008），拿到后校验/执行/记账。
- 循环**不碰模型细节、不碰 UI**：模型走 ProviderPort(LiteLLM)，产出走事件协议。

## 1. 一轮的阶段（phase pipeline）
```
begin_turn(state)                         # 记账 turn 号、预算
 └ build_request(view, tools_frozen)       # 拼 messages+system+tools（经 ProviderPort）
 └ perform_call(stream)                    # 流式；发 text_delta/reasoning_delta(不持久化)
 └ assemble_message()                      # 定稿完整 assistant 块 → reduce → message_completed
 └ propose_action(view)  ──▶ PolicyPort    # 拿回单步意图(ProposeAction / Finish / Cancel建议)
 └ route:
     ├ Finish → finalize_turn → run_completed
     ├ ProposeAction → permission_gate → validate → sandbox/exec → 记 ToolLedger
     │                 → 回填 tool_result → reduce 状态 → 发 tool_* 事件
     │                 → verdict = continue
     └ Cancel建议 / 全局终止 → Cancel Command → finalize(cancelled)
 └ maintenance（turn 边界）: compaction 检查 / checkpoint / loop-guard
 next turn (verdict)
```

## 2. `_LoopState`（阶段间唯一接口；只对 Domain_State 持只读视图，自身可内部可变）
> 不可变红线只针对 `Domain_State`（C2 评审 R01-G8）；`LoopState` 是 per-turn 临时态，**不持久、不进 checkpoint**，允许内部可变槽、以"每 phase 返回 verdict + 按名拷回"解耦。
```
LoopState {
  run_id, turn, seq,
  context_view,               # 只读视图（COW）
  pending_tool_calls[],       # 未闭合调用（配对/取消用）
  budget{max_turns,tokens,deadline},
  last_usage, retry_state,
  cancel_reason: null|user|timeout|budget_exhausted|no_progress|safety|owner,   # 与 02 §5 统一；归因从记录派生、不从调用点臆测
  verdict: continue|return|break
}
```
每阶段**返回新 LoopState + 事件[]**（禁原地改，呼应 C2）。

## 3. 终止权在 Harness（C7）
- 全局判定：`max_turns` / token 超预算 / wall-clock deadline / 用户 cancel / 安全告警 → **任一到即终止**，策略只能"建议"。
- 终止走 `Cancel` Command → reduce：置 `cancelled` + **回填所有 pending tool_call**（保配对）→ 发 `run_cancelled`。

## 4. 流式与瞬态（对齐事件 02 / 状态 01 I3）
- Provider 流 → 直接投 `*_delta`（**不落状态**）；`include_usage` 末块→ `usage_delta`。
- 定稿后才组装完整 `Message` 写入 `context.items`。

## 5. 工具轮
- `parallel_safe` 的多个调用可并发预取；否则按序执行。每个都过 权限→校验→沙箱→超时（工具 03）。
- 失败≠崩溃：分类可重试/致命，喂回策略下轮自纠；错误进 `error_stack`。
- **P2–P4 现状 + ADR-0028 修正**：串行执行不变（`parallel_safe` 仍是 schema 占位，真并发→P5），但
  **一条 assistant 里的 N 个 tool_use 必须在同一次回发前串行闭合**：循环不再“执行一条就回发”，而是由
  provider 调用点的配对关卡先把剩下 N-1 条补齐（含权限/floor、不绕过 ask）。否则 OpenAI/Anthropic 兼容网关
  直接 400（实测曾把 CLI 进程带 traceback 打崩）。关卡副作用：一个 turn 窗口可执行多个工具、`tool_started`
  变密、`repeat_tool_limit` 仅覆盖策略提议路径（关卡路径不经过策略，故不计入重复签名计数）。

## 6. 护栏（loop guards）
- **重复检测**：同工具同参连续 N 次→中断；空响应→有界重试/兜底文案。
- **续跑上限**：provider 要求的无工具续跑也封顶（防兼容端点造无限计费循环）。
- **工具面冻结**：一个 run 内 tools 集不随 MCP 热增中途变（发 `tools_changed` 留下一 run）。

## 7. 压缩与 checkpoint（Kernel 拥有，I2/I4）
- turn 边界按 token 压力触发**可恢复压缩**（改 context 区，产 summary + recovery_pointers）；策略只给 advisory hint。
- turn 边界打**轻量快照**；恢复=最近快照 + 重放其后事件（ADR-0005）。
- **P4 现状**：`disable_compaction=True`，压缩未启用；`recovery_pointers` typed 形状 + covered_hash 已定形（ADR-0024/快照 v3），压缩→L2' 蒸馏发 `MemoryWrite` 的活路与写锚生产者随压缩落地于 P10；记忆写入路径与 `memory/distill.py`（Deep Dream、run-完成 flush）已在 P4 就绪，daily 生产暂由显式 `WriteMemory` + run-完成 flush 承接（ADR-0025）。

## 8. 错误 / fallback
Provider 错误→ProviderPort/LiteLLM 重试/fallback；耗尽则 `run_failed`（带 `retryable`）。全走 Command/reduce，状态不被撕裂。

- **已接线（ADR-0028，2026-10-16）**：provider 异常在 `kernel/loop.py::_stream_turn` 边界被接住，交
  `contracts/errors.py::classify_provider_error`（ADR-0010 的“分类=纯函数进 contracts”首次真接线）归一为
  `ErrorEntry(layer=provider, kind, retryable/should_compress)`，再经 `FinalizeRun(failed)` 落唯一终态。
  BaseException（取消/中断）不在此拦。配对关卡也在此：不可调和的悬空历史→`run_failed(format_error)` 且**一次都不发**。
- **仍后置（不用 fake 冒充）**：退避重试/fallback 链/凭据池/全量 hint 优先级表→P10（plan/01 §1.2）；本轮
  **不自动重试**，`retryable` 目前只经 `run_failed.error.retryable` 给客户端决策。400 配对违规已钉死为
  **不可重试**：否则 P10 接上重试会把同一个确定性错误原样打满预算。

## 9. 与"可插拔策略"的关系
策略=注册进循环的一个 `PolicyPort` 实现（默认进程内）。**新增/灰度/换 ReAct→ToT 不动本循环**（这是"变更域隔离"的兑现点，00 §3.2）。

## 10. 待定（v0 后锁）
- 阶段粒度是否够（先照上面，P1 跑通后再切细）；turn 内是否允许"一次多工具"批量（默认允许 parallel-safe）。
- 压缩/护栏的具体阈值——留 P10 加固期调。

> 五道接缝（00/01/02/03/04）到此齐全 → **达到 ROADMAP §0 的"可开发"门槛**。下一步：写 `docs/plan/01-*.md`（P1 详细计划）即可开工 P1。

## 11. 落地补充（评审采纳）
- **L1 策略输出=不可信意图**：非法工具名/参数→包成被拒 Command + error 事件，verdict=continue、错误回填上下文让下轮自纠，**绝不崩循环**。
- **L2 两个状态别混**：`Domain_State`=权威持久可断点；`LoopState`=循环内部临时态，**不持久化、不进 checkpoint**。
- **L3 只在 turn 边界压缩**：严禁 turn 中途（流式/工具运行中）触发压缩。
- **L4 护栏阈值全配置化**：重复次数/空答重试/max_turns 进 `run.budget`，别硬编码。
- **L5 部分失败语义（v1）**：并行部分工具失败→记 ledger + error_stack、任务继续；**仅全部致命才终止 run**。
- **X1 检查点 × 并行（v1 取巧）**：**v1 直接关并行工具**，避开"多 pending 恢复"复杂度；启用并行时再补 `pending_tool_calls[]` 多条目回填。
- **X4 策略异常隔离**：PolicyPort panic→捕获、回滚到 turn 前一致态、发 error 事件；**已发 delta/外部事件不撤回**（客户端须处理"半流后回滚"）。
- **X3 COW 是语言级坑**：reduce 永远产新 `Domain_State`、禁原地 mutate；文档拦不住，**必须代码强制**（Python 尤险）。

## 13. 评审增补（R01/R06/R08 落地细化；接缝不变，均为"填肉"）
**终止与护栏**
- **终止双向 + 梯度**（改 §3）：补第二半——可**拒绝过早 Finish**（仍有 pending tool_use 未闭合 / verify-on-stop / stall“说继续却没工具” / degenerate-final 碎片收尾 → 不 finalize，注入**有界 nudge** 续跑，候选答案留作耗尽兜底）；硬终止前插三级：预算 0.9→一次性 checkpoint 提示、wall-clock 80%→wrap-up 提示、耗尽→一次无工具 **grace call**→仍不收则**强制无工具总结**（注入临时 prompt→取总结→pop）。
- **护栏拆/补**：重复检测拆"工具入参重复"vs"输出内容 runaway"（后者**流式途中**倍增间隔判停 + 完成分支加字符下限放行"用户要的重复"）；空答按 finish_reason 正常/异常 + usage 0输出 + 单次成本 + 是否有人等 分类；**补 idle/进度看门狗**（与绝对 deadline 正交、消费 `heartbeat` 作进展、休眠不计入）+ 会话级 turn 租约 TTL 兜底（加固期）。
- **退款型重启封顶**：凡 refund 迭代预算的重启(redirect/fallback/压缩重建)按"距上次产出的重启数"封顶、收到响应即归零；另设外层逸出异常计数。
**错误/流式（R08）**
- **分类产结构化 verdict**：`retryable:bool` 升为 `{retryable, should_compress, should_fallback, should_rotate_credential}` + 稳定 `kind` 枚举；分类=**有序阶段优先级表**（先 memory-ceiling 于 overflow/usage-limit；oversized≠overflow；format_error 与 overflow 分栏；cause 链有界5层）；分类器可插拔 hook、失败 fail-to-builtin（**分类纯函数进 contracts、重试/fallback 编排归 Kernel → ADR-0010**）。
- **fallback 边界**：primary 满预算、链每环一次；退避封顶=f(传输空闲超时)；**run 内粘、跨 run 复位、subagent 继承**；即时换链 vs 退避后换链两档；终态携**整链失败摘要** + `resumable:bool`。
- **流式看门狗**：双超时(首 token / chunk 间)；连接池下**代际栅栏+退役即失效**；拿到 finish_reason 后卡住=teardown 不升级 run_failed；mid-stream 取消只留文本不留半 tool_use。
- **Cancel 归因/传播**：reason 从记录派生、落 exit 标签与事件文案；扇出工具 worker + 递归子 agent、隔离到本执行线程；高并发用代际/claim 栅栏防误吞 abort；错误恢复不擦已接受 steer。
**压缩（R06）**：§7 由单档升为**四档梯度**（L0 裁剪 / L1 摘要 / **L2 整体归档留指针=默认** / L2' 蒸馏进长期记忆）；recovery_pointer 形态见 01；**压缩时可选发 `MemoryWrite` Command → 06**；只在 turn 边界、策略仅 advisory。
**契约（R07）**：§9 PolicyPort 具体化为 LoopPolicy/Gateway/Create-Resume + **版本门控 checkpoint**，细化见 05。
**X1 取齐**：v1 串行、`parallel_safe` 占位→P5；启用并行时须 gate(reader/writer/饥饿/orchestrator 绕开) + 取消 poll 感知 + ledger 回填 pending（03 §8/02 §10）。

## 14. P2 Command Inbox / HITL / Process 生命周期（ADR-0013-0018）
```text
RunController(inbox, current Run)
 ├ 安全点：drain Cancel / SetPermissionMode / ResolveApproval / ExpireApproval
 ├ SubmitMessage → provider stream → assistant 定稿
 ├ ProposeAction
 │   └ raw args → JSON → schema → arg-key/shell analysis
 │       → PermissionCtx + capability floor
 │       ├ deny: MarkToolDenied
 │       ├ ask: RequestApproval → durable approval_request
 │       │      wait(inbox: Resolve/Expire/Cancel, timer)
 │       └ allow/ready: MarkToolRunning → durable tool_started
 │           → ToolContext.run_process(...) → settle Command → tool_completed
 └ turn 边界 checkpoint（完整 Domain_State）
```
- **只有一个消费者**：loop/RunController 按 inbox FIFO 串行执行 reduce；provider 流式期间到达的 Command 排队到下一安全点，审批等待期间才即时消费相关 request。
- **审批不是阻塞回调旁路**：CLI、HTTP、桌面最终都提交同一 Command；Approver 只能把 human 决策转成 Inbox submission，不能直接改 state。
- **取消优先级**：pending ResolveApproval 与 Cancel 同 request 到达时，以 reduce 串行顺序判首个有效 transition；后续 stale command 幂等拒绝。
- **Provider 取消也是安全点**：流式期间 Cancel 到达必须关闭 async iterator；尚未定稿的半 tool_use 不登记为可执行 ToolCall，已定稿则必须由 Cancel 回填，禁止“模型已产生 tool_use、账本无 result”。
- **ProcessRunner 在工具执行边界内**：loop 等待工具，工具只通过 ctx.run_process 请求进程；timeout/cancel/kill-tree/env/artifact 全由同一 adapter 保证。
- **settle 脱离取消链**：Cancel 到达不能吞掉已经发起的工具最终结果；先以 shield/finally 完成 settle，再让 Cancel 收尾，终态仍唯一。
