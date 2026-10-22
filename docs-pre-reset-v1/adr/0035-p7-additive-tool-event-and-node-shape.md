# ADR-0035: 工具事件 additive `preview`/`artifact_ref`/`truncated` + `node_updated` 定形（T7/T11）

- 状态：✅（2026-10-17）
- 背景：桌面工具卡（T7）需展示**有界** preview + artifact 指针 + status，但当前对外 `TOOL_COMPLETED` 仅 `{tool_call_id, status}`（`kernel/events.py:51`、`protocol/event.schema.json:116-124`），无 preview/artifact_ref；且 `NODE_UPDATED` 对外是 `data=None` 透传、`$defs` 仅"permissive、形状留 P5"（`kernel/events.py:55`、`protocol/event.schema.json:161-164`）。补这两处属对 `protocol/contracts` 的**事件形状变更**，触及单一真源契约（C15/C6/C11），先记 ADR（plan/07 §3 前置门 / T0）。
- 决策：
  - **全部 additive-only（C6/C11）**：只给**已有 type** 的 `data` 加**可选**字段，**不新增事件 type、不改既有字段语义/关联键/信封**（`CORRELATION_KEYS` run_id/turn/tool_call_id/card_id/item_id 不动）。无需 bump `EVENT_SCHEMA_VERSION`（破坏性才 bump）。
  - **`tool_completed` additive 三字段**（均 optional）：`preview`（有界字符串，`maxLength` 定死，复用 ADR-0019 的 16 KiB result / 64 KiB display 预算口径，**远小于此值进事件**，如 ≤2–4 KiB）、`artifact_ref`（不透明指针字符串，**绝不含 abs path**）、`truncated`（bool）。全文**只经 artifact 指针按需读**（可选只读 `GET /artifacts/{id}`），**不整块进事件流**。
  - **写失败绝不回退原文（ADR-0019 铁律）**：artifact 落盘失败 → `status=error` + 有界 `preview`，**绝不把全文塞回 event/checkpoint/prompt**。
  - **`node_updated` additive 定形**：把 `data=None` 透传收敛为具 `$defs` 形（node 标识 + 状态枚举 + 有界摘要），仍只增不改；`EXTERNAL_EVENT_FIELDS[NODE_UPDATED]` 由 `None` 改为白名单 frozenset。
  - **三处 lockstep（`check_protocol_schema`）**：任何 additive 都须**同步** `contracts/events.py`（`EventType`/`EXTERNAL_EVENT_FIELDS`）+ `protocol/event.schema.json`（`enum`/`$defs`/`if-then`）；因只加字段不加 type，`enum` 集合不变、lockstep 计数不破，但每个改动类型的 `$defs` 须补可选属性（`additionalProperties:false` 仍拒未声明字段）。`--self-test` 的 valid/bad fixture 随之更新（新增带 preview 的 valid + 超 maxLength / 未知字段的 bad）。
  - **C20 投影白名单不破**：`preview`/`artifact_ref`/工具**原文**、远程输出、env 值**一律不进 `projection._DATA_KEYS`**（`check_projection_whitelist` 守）——工具卡走事件流给前端，日志第二载体不复制载荷。MCP stderr 仍走独立文件不变。
- 后果：
  - 正面：工具卡/任务树可渲染有界信息、全文按需读、事件流体积有上界；协议向后兼容（旧消费者忽略新 optional 字段，未知 type 仍静默、错误类仍出声）。
  - 代价：additive 扩 `EXTERNAL_EVENT_FIELDS` 后须同步扩 `protocol/event.schema.json` `$defs` + fixture；TS codegen（T3）需重生成保持新鲜。
  - 需持续守：`check_protocol_schema --check` 零破坏 + `--self-test` 能判红；`check_projection_whitelist` 白名单不含 preview/原文类键。
- 备选（被否）：
  1. 把工具全文塞进 `tool_completed.data` → 否：违 C18（无界载荷拖垮内存/SQLite/SSE/prompt）+ C20（事件成第二载体、原文进观测面）。
  2. 前端自己持 artifact store 句柄读全文 → 否：违 C4（不给 UI 裸句柄）/S6（业务下沉）；经只读端点投指针即可。
  3. 新增独立 `tool_artifact` 事件 type → 否：`tool_completed` 已具 `tool_call_id` 关联锚，加 type 徒增协议面与 lockstep 分支（C11 谨慎演进）。
- 关联：[`ADR-0016`](./0016-tool-lifecycle-approval-identity.md)、[`ADR-0019`](./0019-bounded-artifact-projection.md)、[`ADR-0028`](./0028-pairing-gate-and-provider-fault-normalization.md)、`HARD-CONSTRAINTS` C6/C11/C13/C15/C18/C20、`STRUCTURE` §9、`docs/plan/07-p7-desktop-shell.md` §0.2-③ / T7 / T11。
