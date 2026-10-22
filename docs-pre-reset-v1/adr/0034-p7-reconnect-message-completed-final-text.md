# ADR-0034: 断线重连在途文本恢复 = `message_completed` additive 有界 `final_text`（D-P7-C 选型①）

- 状态：✅（2026-10-17）
- 背景：`text_delta`/`reasoning_delta` 属 `LIVE_ONLY`（`kernel/events.py:31-33`），**只转发、永不入库**；`subscribe(after_seq)` 仅重放 durable（`kernel/events.py:147-153`）。而 `state/reduce.py:105-107` 发 `MESSAGE_COMPLETED` 时 data **仅 `{message_id}`**——定稿消息的**文本只进了 `run.context.items`（Domain_State → checkpoint），没进 durable 事件帧**。故 SSE 断线重连后，客户端**无法只靠事件流补回已定稿消息的可见文本**（参考仓 DeepCode `threadEventStream.ts` 注释亦自证"Streamed text is not in that log"）。plan/07 §0.3 D-P7-C 要求开工前二选一定案：① 对 `message_completed` additive 加有界 `final_text`（+ `item_id`），令 durable 重放即可恢复文本；② 新增只读 `GET /runs/{id}/transcript`（`rebuild_run` 从 checkpoint 重建）。
- 定案取向（用户明确：面向"超大型项目 + 长远最优"，不计工作量）：选 **①**。
- 决策：
  - **`message_completed` additive 扩**（只增不改，C6/C11）：在既有 `{message_id}` 上加**可选** `final_text`（**有界**内联正文）、`item_id`（归属，命中 `CORRELATION_KEYS`）；正文超预算时 `final_text` 截断 + `truncated=true` + `artifact_ref` 指针（**复用 ADR-0019/ADR-0035 的工具卡同一"有界 preview + artifact 指针"纪律**，全文按需只读 `GET /artifacts/{id}`），事件帧本身**恒有界**（守 C18）。
  - **reduce 侧**：`state/reduce.py:107` 在 append `command.message` 进 context 的同一处，把该消息的可见文本（`command.message` 的 text 块拼接、过有界预算）写入 `MESSAGE_COMPLETED.data`。文本此刻在手里，不新增第二来源。
  - **三处 lockstep（`check_protocol_schema`）**：`contracts/events.py` 的 `EXTERNAL_EVENT_FIELDS[MESSAGE_COMPLETED]` 由 `{message_id}` 扩为含 `final_text`/`item_id`/`truncated`/`artifact_ref`；`protocol/event.schema.json` 的 `$defs.message_completed` 补这些**可选、有界**属性（`additionalProperties:false` 仍拒未声明字段）+ `--self-test` 加"带 final_text 的 valid / 超 maxLength 的 bad"fixture。`enum` 集合不变、lockstep 计数不破。
  - **C20 观测面不破**：`final_text` 是**协议字段（给前端事件流）**，**不进 `projection._DATA_KEYS`**（`check_projection_whitelist` 守）——日志第二载体不复制正文；带外投影仍只投白名单标量。
  - **不引入 `/transcript` 第二读面**：既①已让 `after_seq` 重放自足恢复定稿文本，**不再单独开 `GET /transcript` 这个游离于 `protocol/event.schema.json` 之外的 bespoke 读契约**（避免 C15"单一真源"被第二个非 schema 化的读面稀释；多端各接一处 = 漂移温床）。若未来需要"跨 run 聚合读"另开 ADR。
  - **诚实边界（写死）**：`message_completed` 只在消息**定稿边界**产生，携带的是**整条定稿文本**；连接中断时**尚未定稿的"半条"在途 delta** 仍无 durable 表示、补不回——与参考仓同一限制，不假装 `after_seq` 能补齐 streamed 半成品。"在途半条文本恢复"标 **UNVERIFIED**；DoD② 保证 **durable 事件（含扩后的 message_completed）不丢不重**。
- 理由（为何 ① 优于 ②，长远视角）：
  - **单一真源**：事件协议（`protocol/event.schema.json`）成为**所有 surface/客户端**重建 transcript 的**唯一** durable 来源，`after_seq` 重放即可、无需旁路读端点；②的 `/transcript` 是一条**不被协议 schema 覆盖的第二个读契约**，对"多端（桌面/Web/移动/IM/OpenAI 兼容）超大型项目"恰是 C15 最怕的漂移面。
  - **一致性**：resume / reconnect / transcript 三处都读同一批 durable 事件；②会让"文本"与"其余状态"来自两套机制。
  - **代价可控**：正文本就随消息定稿而存在，写进它自己的 `message_completed` 帧是**该事件的天然载荷**（非派生聚合态回写，不违 C13）；有界 + artifact 溢出（C18/ADR-0019）确保不拖垮 SSE/SQLite/prompt。
- 后果（正面 / 代价 / 需持续守）：正面——事件流自足、零第二契约、多端统一；代价——additive 扩 message_completed 触协议/白名单/fixture 三点同步（T7 已为工具卡建立同类 lockstep 流程，本条同构复用）；需守——`final_text` 恒有界、超限走 `artifact_ref` 不回退全文、绝不进投影白名单（C20）。
- 备选（被否）：② 只读 `GET /transcript`（本 ADR 前一版取向）→ **否**：对超大型多端项目引入游离于事件协议外的第二读契约，稀释 C15 单一真源、放大漂移面，虽"协议零 diff"但长远劣于①；③ 客户端自缓存 delta 不重连补 → 否：真断线即丢、不可靠。
- 关联：`state/reduce.py:105-107`、`kernel/events.py:31-33/48/147-153`、`contracts/events.py:48`、[`ADR-0019`](./0019-bounded-artifact-projection.md)（有界/溢出指针）、[`ADR-0035`](./0035-p7-additive-tool-event-and-node-shape.md)（同族 additive/lockstep 纪律）、[`ADR-0020`](./0020-durable-write-gate-and-log-authority.md)（log/snapshot 双权威）、`HARD-CONSTRAINTS` C6/C11/C13/C15/C18/C20、`docs/plan/07-p7-desktop-shell.md` §0.3 D-P7-C / §1.2 DoD② / §4.3。
