# ADR-0011: seq 语义 = per-run 逻辑序 + 全局物理序（两游标）

- 状态：✅（2026-10-15）
- 背景：续传要 per-run 稳定游标；跨 run 的 catch-up/changelog watermark 又要全局单调序。单一 `seq` 两头不讨好（DeepCode 用 per-thread 逻辑 sequence + 物理 rowid 两条、wuu 有全局 HeadSeq）。
- 决策：`events` 存**两类游标**——
  - **per-run 逻辑 `seq`**：`SSE after_seq` 续传/回放游标（对应 02 信封 `seq`）；
  - **全局单调物理序**：跨 run catch-up / watermark（"补齐我错过的所有 run"）。
  delta/heartbeat 属 live-only、**不占 durable seq**（走 item offset）。
- 后果：续传与全局同步都成立；代价=两条游标要在 §9 索引/§4 传输都写清，别混用。
- 关联：`design/01-state-model.md §13`、`design/02-event-protocol.md §10`、C13。
