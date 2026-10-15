# ADR-0019: 大输出采用有界 artifact envelope，投影失败不得回退为原文

- 状态：✅（2026-10-15）
- 背景：工具全文输出可能进入 Domain_State、事件载荷、checkpoint 和下一轮 prompt，造成内存、SQLite、模型上下文与 UI 同时膨胀。原参考策略“artifact 写失败则返回原文”虽便于开发，却会打破“事件和状态有界”这一长期不变式。
- 决策：
  - 超过预算的输出必须走受控 `ArtifactStorePort`；工具只能请求写 artifact，不能自定任意落盘路径。
  - `ToolResult.result` 默认最多 16 KiB；`display` 默认最多 64 KiB；ProcessRunner stdout/stderr 各自最多 1 MiB，超出后全文进 artifact。阈值经配置，只增不改。
  - 模型侧只接收 `archived_tool_result` envelope：kind、artifact_ref、sha256、total_bytes、bounded preview、continuation。
  - artifact 写失败时返回 error ToolResult + 已捕获的有界 preview 与重试提示，绝不把全文重新塞回 prompt、event 或 checkpoint。
  - 事件投影采用 per-type field whitelist；完整 args、env scrub 明细、内部绝对路径、provider 专有状态默认不外发。
  - `hidden` 是 Kernel 内部投影控制位，不进入外部 Envelope；对外 schema 禁止未知 data 字段。
- 后果：长跑、SSE 重放和 checkpoint 体积有确定上界；代价是需要独立的 artifact GC/session cleanup，后续可归 P10。大输出丢失时用户会看到明确 error，而不是系统被撑爆后随机失败。
- 备选（被否）：
  1. artifact 写失败 fail-open 返回原文：把局部 IO 故障升级成内存/上下文故障 → 否。
  2. 只截断、不保留全文：用户无法审计或继续读取 → 否。
  3. 投影保持 identity：内部结构被 UI/远程消费者依赖，P7/P9 无法演进 → 否。
- 关联：ADR-0018；HARD-CONSTRAINTS C4/C6/C13/C15；[`../design/02-event-protocol.md`](../design/02-event-protocol.md) §2/§10、[`../design/03-tool-interface.md`](../design/03-tool-interface.md) §2/§11。
