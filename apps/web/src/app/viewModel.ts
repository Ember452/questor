/** 帧 → 视图模型的纯函数。14 个 kind 全部覆盖；不认识的 kind 由 tsc 穷尽拦截。 */

import type { ServerFrame } from "../shared/transport/wireTypes";
import type { HistoryMessage, UsageTotals } from "../shared/transport/wireTypes";

export type ViewItem =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "say"; text: string; streaming: boolean }
  | {
      id: string;
      kind: "tool";
      callId: string;
      tool: string;
      status: "running" | "done" | "error";
      output: string;
    }
  | { id: string; kind: "notice"; level: string; text: string }
  | { id: string; kind: "compaction"; phase: string; status: "started" | "progress" | "done" }
  | { id: string; kind: "approval"; promptId: string; tool: string; subject: string; detail: string }
  | { id: string; kind: "ask"; promptId: string; question: string }
  | { id: string; kind: "todos"; path: string; rows: { text: string; checked: boolean }[] }
  | { id: string; kind: "turn"; turnId: string; label: string };

export interface ViewState {
  items: ViewItem[];
  busy: boolean;
  usage: UsageTotals | null;
  lastSeq: number;
}

export const initialState: ViewState = { items: [], busy: false, usage: null, lastSeq: 0 };

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

/** 历史消息 → 初始视图（只取文本块；工具块在历史里仅占位）。 */
export function historyItems(messages: HistoryMessage[]): ViewItem[] {
  return messages.flatMap((message) => {
    const text = message.blocks
      .map((block) => {
        switch (block.type) {
          case "text":
            return block.text;
          case "tool_use":
            return `▸ ${block.name}`;
          case "tool_result":
            return "[工具结果]";
          case "image":
            return "[图片]";
        }
      })
      .join(" ")
      .trim();
    if (!text) return [];
    return [
      {
        id: nextId("history"),
        kind: message.role === "user" ? "user" : "say",
        text,
        ...(message.role === "user" ? {} : { streaming: false }),
      } as ViewItem,
    ];
  });
}

/** 历史重载与本地视图合并：已落快照的用户消息以历史为准，
 *  尚未落快照的本地用户消息（回合失败/引擎重启期间发出的）必须保留。 */
export function mergeHistoryItems(currentItems: ViewItem[], messages: HistoryMessage[]): ViewItem[] {
  const restored = historyItems(messages);
  const restoredUserTexts = new Set(
    messages
      .filter((message) => message.role === "user")
      .map((message) =>
        message.blocks
          .filter((block) => block.type === "text")
          .map((block) => block.text)
          .join(" ")
          .trim(),
      ),
  );
  const pending = currentItems.filter(
    (item) => item.kind === "user" && !restoredUserTexts.has(item.text.trim()),
  );
  return [...restored, ...pending];
}

function replaceTool(state: ViewState, callId: string, update: Partial<Extract<ViewItem, { kind: "tool" }>>): ViewState {
  const index = state.items.findIndex((item) => item.kind === "tool" && item.callId === callId);
  if (index < 0) return state;
  const items = state.items.slice();
  items[index] = { ...(items[index] as Extract<ViewItem, { kind: "tool" }>), ...update };
  return { ...state, items };
}

export function applyFrame(state: ViewState, frame: ServerFrame): ViewState {
  const lastSeq = Math.max(state.lastSeq, frame.seq);
  switch (frame.kind) {
    case "turn_started":
      return {
        ...state,
        busy: true,
        lastSeq,
        items: [...state.items, { id: nextId("turn"), kind: "turn", turnId: frame.turnId, label: "开始" }],
      };
    case "text": {
      const last = state.items.at(-1);
      if (last?.kind === "say" && last.streaming) {
        const items = state.items.slice();
        items[items.length - 1] = { ...last, text: last.text + frame.text };
        return { ...state, items, lastSeq };
      }
      return {
        ...state,
        lastSeq,
        items: [...state.items, { id: nextId("say"), kind: "say", text: frame.text, streaming: true }],
      };
    }
    case "message": {
      const text = frame.blocks
        .map((block) => (block.type === "text" ? block.text : `[${block.type}]`))
        .join("");
      const usage = frame.usage ?? state.usage;
      const last = state.items.at(-1);
      const items = state.items.slice();
      if (last?.kind === "say" && last.streaming) items[items.length - 1] = { ...last, text, streaming: false };
      else if (text) items.push({ id: nextId("say"), kind: "say", text, streaming: false });
      return { ...state, items, usage, lastSeq };
    }
    case "tool_dispatch":
      return {
        ...state,
        lastSeq,
        items: [
          ...state.items,
          {
            id: nextId("tool"),
            kind: "tool",
            callId: frame.toolCallId,
            tool: frame.tool,
            status: "running",
            output: "",
          },
        ],
      };
    case "tool_result":
      return {
        ...replaceTool(state, frame.toolCallId, {
          status: frame.isError ? "error" : "done",
          output: frame.output,
        }),
        lastSeq,
      };
    case "approval_request":
      return {
        ...state,
        lastSeq,
        items: [
          ...state.items,
          {
            id: nextId("approval"),
            kind: "approval",
            promptId: frame.id,
            tool: frame.tool,
            subject: frame.subject,
            detail: frame.detail ?? "",
          },
        ],
      };
    case "ask_request":
      return {
        ...state,
        lastSeq,
        items: [
          ...state.items,
          { id: nextId("ask"), kind: "ask", promptId: frame.id, question: frame.question },
        ],
      };
    case "notice":
      return {
        ...state,
        lastSeq,
        items: [...state.items, { id: nextId("notice"), kind: "notice", level: frame.level, text: frame.text }],
      };
    case "compaction_started":
      return {
        ...state,
        lastSeq,
        items: [...state.items, { id: nextId("compact"), kind: "compaction", phase: frame.trigger, status: "started" }],
      };
    case "compaction_progress":
      return {
        ...state,
        lastSeq,
        items: [
          ...state.items,
          { id: nextId("compact"), kind: "compaction", phase: frame.phase, status: "progress" },
        ],
      };
    case "compaction_done":
      return {
        ...state,
        lastSeq,
        items: [
          ...state.items,
          {
            id: nextId("compact"),
            kind: "compaction",
            phase: frame.ok ? "ok" : "failed",
            status: "done",
          },
        ],
      };
    case "turn_done":
      return {
        ...state,
        busy: false,
        lastSeq,
        usage: frame.usage ?? state.usage,
        items: [
          ...state.items,
          { id: nextId("turn"), kind: "turn", turnId: frame.turnId, label: `${frame.outcome} · ${frame.durationMs}ms` },
        ],
      };
    case "stream_reset":
      return { ...state, lastSeq: Math.max(lastSeq, frame.seq) };
    case "todos":
      // 清单快照（W-D4）：同一回合重复写入时以后一次为准，不在时间线上堆一叠旧清单。
      return {
        ...state,
        lastSeq,
        items: [
          ...state.items.filter((item) => item.kind !== "todos"),
          { id: nextId("todos"), kind: "todos", path: frame.path, rows: frame.items },
        ],
      };
    default: {
      const exhaustive: never = frame;
      return { ...state, lastSeq, items: [...state.items, { id: nextId("unknown"), kind: "notice", level: "error", text: String(exhaustive) }] };
    }
  }
}
