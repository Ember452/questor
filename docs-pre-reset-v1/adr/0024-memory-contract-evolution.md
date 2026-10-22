# ADR-0024: 记忆契约演进（typed WriteMemory + memory_written 事件 + recovery_pointers covered_hash + 快照 v3）

- 状态：✅（2026-10-16，决策定；实现见 [`../plan-archive/04-memory-soul.md`](../plan-archive/04-memory-soul.md) T5–T7、T11）
- 背景：`WriteMemory` 命令已在 [`../../src/questor/contracts/events.py`](../../src/questor/contracts/events.py) 定义但 `payload: JsonObject`（裸 JSON、且 `state/reduce.py` 无处理分支=死 stub）；`recovery_pointers` 现为 `tuple[tuple[int,int], ...]` 且源码注记"NOT filled until P4/P10（压缩）"、**缺 CoveredHash 锚**——P3 对抗审计（[`../audit/P3-review-2026-10-16.md`](../audit/P3-review-2026-10-16.md)）A2/E1 明确警告：若在 P4 不定形、待 P10 压缩落地再补，将**破坏性修改已落库的快照 schema**（违 HARD C11"接缝早锁、字段 v0 后锁"）。快照已有 P3 的 `contract_version` fail-closed 闸门（commits `e4f81dc`）。[`../design/06-memory.md`](../design/06-memory.md) I3 要求"只写浓缩文本、绝不写 delta"。
- 决策：
  - **`WriteMemory.payload` 从裸 `JsonObject` 收敛为 typed `MemoryWrite`**：`kind ∈ {core, daily, distill}`、`scope ∈ {shared, user, session}`、`text`（有界浓缩文本）、可选覆盖区引用；`Command` 联合类型与 `type="write_memory"` 名保持不变（不破信封）。字段 v0 锁（HARD C11）。
  - **新增内部事件 `memory_written`（kernel 私有、可演进）+ 外部可选投影 `memory_written`**：外部 payload 仅 `bounded`（`kind`/`chunk_count`/`artifact_ref`），**记忆原文不进外部事件**；属 HARD C6 允许的"只增可选 type"，协议 19→20；外部 payload 沿用 `additionalProperties:false` + 字段级 `$defs`（复用 `check_protocol_schema`，实现先落 schema、再代码、再 TS codegen）。
  - **`recovery_pointers` 定为 typed `RecoveryPointer(seq_from, seq_to, covered_hash)`**：指向 events/messages append-only 序号区间（非字节偏移/非 UUID）；**读取前校验 `covered_hash`、历史被改写/分叉即 fail-closed**（绝不返回旧内容），锚哈希算法剔除线程局部 seq/调用 id（仿 wuu `internal/agent/compaction_note.go:20-21,88-92,211-212`）。
  - **快照 schema v2→v3**：加入 `RecoveryPointer.covered_hash`；未知版本 **fail-closed**（复用 P3 `contract_version` 闸门）；提供 v2→v3 幂等迁移（`migrated.setdefault`，沿用 [`../../src/questor/state/snapshot.py`](../../src/questor/state/snapshot.py) v1→v2 迁移风格）；序列化继续 `allow_nan=False`、时间 `require_aware`（HARD C18 卫生）。
  - **诚实边界**：`covered_hash` 的**生产者**（压缩时写指针+锚哈希）随 `disable_compaction=True`（[`../../src/questor/contracts/policy.py`](../../src/questor/contracts/policy.py) §86）后置 P10；**P4 仅定形 schema + 建 fail-closed 读校验路径**（用测试直接构造"覆盖区间原文被改写→读回拒绝"，不依赖压缩真跑）。
- 后果：正面——P4 定型后 P10 落地压缩不必再改快照协议（直接消除 P3 审计 E1 预警的破坏性返工）；typed `WriteMemory` 让有界/幂等/权限判定可在 `reduce` 内强制（HARD I1/C18）。代价——多一次快照版本 bump + 迁移；外部事件集多一个可选 type（消费者须按 C6 忽略未知）；`covered_hash` 定形但无生产者，须以清晰注释防误读为死字段。
- 备选（被否）：
  1. 留裸 `JsonObject`、P10 再改：届时破坏已落库快照历史，是"长期维护最痛的返工"（HARD C11 原述）→ 否。
  2. 现在即接活压缩产 `covered_hash`：与 `disable_compaction=True` 冲突、超 P4 范围 → 否。
  3. 记忆写入不设字段级 schema：违 HARD C6/C15"单一真源、防三处漂移"→ 否。
  4. 不 bump、直接改 v2 语义：违"只增不改"+ 制造半升级表形/ABA（R03 E-P1）→ 否。
- 关联：[`../design/06-memory.md`](../design/06-memory.md) §0/§6；[`../design/01-state-model.md`](../design/01-state-model.md) §2/§5/§13；[`../design/02-event-protocol.md`](../design/02-event-protocol.md) §5/§6/§10；HARD-CONSTRAINTS C6/C11/C13/C15/C18；ADR-0005/0011/0019/0020/0022/0023/0025；R03 E-P1、R06 §4.2。
