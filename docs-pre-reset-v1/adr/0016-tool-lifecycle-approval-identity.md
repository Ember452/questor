# ADR-0016: 工具调用拥有完整生命周期与带 ID 的审批请求

- 状态：✅（2026-10-15）
- 背景：P1 的事件类型已有 `tool_started`/`approval_request`，状态却只有 `pending → result`，没有可恢复的 running/awaiting approval 记录；原 `ResolveApproval` 也只按 `tool_call_id` 决策，无法区分“重复投递”“超时后迟到”“同一调用多次请求”。
- 决策：
  - ToolCall 状态机固定为：
    `pending → validated → awaiting_approval | ready | denied → running → success | error | critical_error | timed_out | cancelled`。
  - 新增 `ToolCallStatus.AWAITING_APPROVAL` 与 `ToolCallStatus.TIMED_OUT`；`RunStatus.AWAITING_APPROVAL` 是串行 Run 的派生视图，不替代 per-call 状态。
  - 每次审批生成独立 `ApprovalRequest{request_id, tool_call_id, expires_at, status, decision, decided_by, ...}`；`ResolveApproval` 必须携带 `request_id`。
  - 幂等规则：同 request + 同 decision 为成功 no-op；同 request 不同 decision 被拒绝；resolved/expired/cancelled request 不可翻案；超时只能由带同一 request_id 的 ExpireApproval 生效。
  - `MarkToolRunning` 是产生 `tool_started` 的唯一路径；执行前必须先把 ledger 从 pending/ready 转为 running。
  - 取消、超时和进程异常都经 Command → reduce 闭合，禁止 out-of-band 更新 UI/Store。
- 后果：审批 UI、断点恢复、SSE 重放和重复提交有确定语义；代价是状态 schema 扩字段、checkpoint 与协议快照必须同步。
- 备选（被否）：
  1. 仅按 tool_call_id 保存最后决策：超时后迟到批准可复活已过期审批 → 否。
  2. 直接发 `tool_started` 但不改 Domain_State：事件与状态分叉，恢复时误判工具未运行 → 否。
  3. 审批期间把整个 Run 冻结为 awaiting 且不能接收 Cancel：取消只能等人工点击，无法 fail-closed → 否。
- 关联：ADR-0013、ADR-0014、HARD-CONSTRAINTS C5/C7/C9/C13；[`../design/01-state-model.md`](../design/01-state-model.md) §4/§6、[`../design/02-event-protocol.md`](../design/02-event-protocol.md) §3。
