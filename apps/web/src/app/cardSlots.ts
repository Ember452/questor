/** 卡槽：帧 kind → 渲染槽位。用 Record 保证 13 个 kind 穷尽（新增 kind = tsc 红）。 */

import type { ServerFrame } from "../shared/transport/wireTypes";

export type Slot = {
  /** 视图模型中的 item.kind；null = 时间线分隔/内部处理，不渲染成卡片。 */
  item: string | null;
  /** 卡片必须属于的 capability；absent 时不渲染。 */
  capability?: string;
  /** 仅允许“暂不展示”的 kind 走 allowlist。 */
  allowlist?: boolean;
};

export const CARD_SLOTS: Record<ServerFrame["kind"], Slot> = {
  turn_started: { item: "turn" },
  text: { item: "say", capability: "chat" },
  message: { item: "say", capability: "chat" },
  tool_dispatch: { item: "tool", capability: "chat" },
  tool_result: { item: "tool", capability: "chat" },
  approval_request: { item: "approval", capability: "chat" },
  ask_request: { item: "ask", capability: "chat" },
  notice: { item: "notice", allowlist: true },
  compaction_started: { item: "compaction", capability: "chat" },
  compaction_progress: { item: "compaction", capability: "chat" },
  compaction_done: { item: "compaction", capability: "chat" },
  turn_done: { item: "turn" },
  stream_reset: { item: null },
  todos: { item: "todos", capability: "chat" },
};

export const ALLOWLIST_KINDS = (Object.entries(CARD_SLOTS) as Array<[ServerFrame["kind"], Slot]>)
  .filter(([, slot]) => slot.allowlist)
  .map(([kind]) => kind);
