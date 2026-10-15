# Questor Turn 循环骨架（L2 Kernel）

> 承接分层(00)、状态(01)、事件(02)、工具(03)、红线。设计文档，非实现。
> 参照：**hermes 的阶段流水线 + `_LoopState` 显式状态 + verdict**，配 **wuu 的护栏**（续跑上限/空答分类/工具面冻结）。Harness 是引擎，**只调度不思考**。

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

## 2. `_LoopState`（阶段间唯一接口，不可变）
```
LoopState {
  run_id, turn, seq,
  context_view,               # 只读视图（COW）
  pending_tool_calls[],       # 未闭合调用（配对/取消用）
  budget{max_turns,tokens,deadline},
  last_usage, retry_state,
  cancel_reason: null|user|timeout|resource|safety,
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

## 6. 护栏（loop guards，wuu/Cow 经验）
- **重复检测**：同工具同参连续 N 次→中断；空响应→有界重试/兜底文案。
- **续跑上限**：provider 要求的无工具续跑也封顶（防兼容端点造无限计费循环）。
- **工具面冻结**：一个 run 内 tools 集不随 MCP 热增中途变（发 `tools_changed` 留下一 run）。

## 7. 压缩与 checkpoint（Kernel 拥有，I2/I4）
- turn 边界按 token 压力触发**可恢复压缩**（改 context 区，产 summary + recovery_pointers）；策略只给 advisory hint。
- turn 边界打**轻量快照**；恢复=最近快照 + 重放其后事件（ADR-0005）。

## 8. 错误 / fallback
Provider 错误→ProviderPort/LiteLLM 重试/fallback；耗尽则 `run_failed`（带 `retryable`）。全走 Command/reduce，状态不被撕裂。

## 9. 与"可插拔策略"的关系
策略=注册进循环的一个 `PolicyPort` 实现（默认进程内）。**新增/灰度/换 ReAct→ToT 不动本循环**（这是"变更域隔离"的兑现点，00 §3.2）。

## 10. 待定（v0 后锁）
- 阶段粒度是否够（先照上面，P1 跑通后再切细）；turn 内是否允许"一次多工具"批量（默认允许 parallel-safe）。
- 压缩/护栏的具体阈值——留 P10 加固期调。

> 五道接缝（00/01/02/03/04）到此齐全 → **达到 ROADMAP §0 的"可开发"门槛**。下一步：写 `docs/plan/01-*.md`（P1 详细计划）即可开工 P1。
