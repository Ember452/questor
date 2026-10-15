# ADR-0007: 传输 — 统一 HTTP+SSE，Tauri 内嵌 webview（非私有协议）

- 状态：✅（2026-10-15）
- 背景：注定有多端消费者（桌面/Web/移动/IM/OpenAI 兼容），传输协议是"一次定、多端复用"的缝。
- 决策：**统一 HTTP + SSE 流** + 少量控制 API（`/run` `/cancel` `/resume`），带 `seq`/`after_seq` 续传；**Tauri 只内嵌 webview 指向本地服务**，不自造 Tauri 私有 event 协议。OpenAI 兼容 = 同一股流的另一投影。
- 后果：桌面/网页/移动共用一套客户端 SDK、断线可重连、易调试；代价=要处理 SSE 断连/续传（游标正好落进状态，与 ADR-0005 呼应）。
- 备选(被否)：Tauri 私有 IPC event（为桌面造一套、web/远程要重造）→ 否；纯 WebSocket（更重、和 OpenAI 兼容不天然契合）→ 备选。
- 关联：[`../design/01-state-model.md`](../design/01-state-model.md) §5、ADR-0002/0005。
