import { describe, expect, it } from "vitest";

import fixtures from "../generated/wire-fixtures.json";
import type { ServerFrame } from "../shared/transport/wireTypes";
import { applyFrame, historyItems, initialState, mergeHistoryItems, type ViewState } from "./viewModel";

const frames = fixtures as unknown as ServerFrame[];

function byKind(kind: ServerFrame["kind"]): ServerFrame {
  const frame = frames.find((item) => item.kind === kind);
  if (!frame) throw new Error(`missing fixture for ${kind}`);
  return frame;
}

function fold(list: ServerFrame[], state: ViewState = initialState): ViewState {
  return list.reduce(applyFrame, state);
}

describe("viewModel：13 帧都有字段落点", () => {
  it("text 累积为流式 say", () => {
    const state = fold([{ seq: 1, kind: "text", text: "a" }, { seq: 2, kind: "text", text: "b" }]);
    expect(state.items.at(-1)).toMatchObject({ kind: "say", text: "ab", streaming: true });
  });

  it("message 携带 blocks 与 usage", () => {
    const frame = byKind("message");
    const state = fold([frame]);
    expect(state.items.at(-1)).toMatchObject({ kind: "say", streaming: false });
    expect(state.usage).toEqual((frame as { usage?: unknown }).usage ?? null);
  });

  it("tool_dispatch / tool_result 用 callId 配对", () => {
    const dispatch = byKind("tool_dispatch") as Extract<ServerFrame, { kind: "tool_dispatch" }>;
    const result = byKind("tool_result") as Extract<ServerFrame, { kind: "tool_result" }>;
    const state = fold([dispatch, result]);
    const tool = state.items.find((item) => item.kind === "tool");
    expect(tool).toMatchObject({ callId: dispatch.toolCallId, status: result.isError ? "error" : "done" });
  });

  it("approval_request 带 detail", () => {
    const frame = byKind("approval_request") as Extract<ServerFrame, { kind: "approval_request" }>;
    const state = fold([frame]);
    expect(state.items.at(-1)).toMatchObject({ kind: "approval", subject: frame.subject, detail: frame.detail ?? "" });
  });

  it("ask_request 带 question", () => {
    const frame = byKind("ask_request") as Extract<ServerFrame, { kind: "ask_request" }>;
    expect(fold([frame]).items.at(-1)).toMatchObject({ kind: "ask", question: frame.question });
  });

  it("compaction 三帧各自落点", () => {
    const state = fold([byKind("compaction_started"), byKind("compaction_progress"), byKind("compaction_done")]);
    expect(state.items.filter((item) => item.kind === "compaction")).toHaveLength(3);
  });

  it("turn_started 置忙，turn_done 收尾并带时长", () => {
    const done = byKind("turn_done") as Extract<ServerFrame, { kind: "turn_done" }>;
    const busy = fold([byKind("turn_started")]);
    expect(busy.busy).toBe(true);
    const finished = fold([done], busy);
    expect(finished.busy).toBe(false);
    expect(finished.items.at(-1)).toMatchObject({ kind: "turn", label: `${done.outcome} · ${done.durationMs}ms` });
  });

  it("notice 与 stream_reset", () => {
    const state = fold([byKind("notice"), byKind("stream_reset")]);
    expect(state.items.at(-1)).toMatchObject({ kind: "notice" });
    expect(state.lastSeq).toBeGreaterThan(0);
  });

  it("历史消息转成 user/say", () => {
    const items = historyItems([
      { role: "user", blocks: [{ type: "text", text: "hi" }] },
      { role: "assistant", blocks: [{ type: "text", text: "hello" }] },
    ]);
    expect(items.map((item) => item.kind)).toEqual(["user", "say"]);
  });
});

describe("mergeHistoryItems：历史重载不吃掉本地未落盘的用户消息", () => {
  const history = [
    { role: "user", blocks: [{ type: "text", text: "已落盘的问题" }] },
    { role: "assistant", blocks: [{ type: "text", text: "已落盘的回答" }] },
  ] as Parameters<typeof mergeHistoryItems>[1];
  const current: ViewState = {
    items: [
      { id: "u1", kind: "user", text: "已落盘的问题" },
      { id: "u2", kind: "user", text: "回合失败后新发的消息" },
      { id: "u3", kind: "user", text: "  回合失败后新发的消息  " },
    ],
    busy: false,
    usage: null,
    lastSeq: 0,
  };

  it("已落盘的用户消息以历史为准（不重复），未落盘的保留", () => {
    const merged = mergeHistoryItems(current.items, history);
    const texts = merged.filter((item) => item.kind === "user").map((item) => item.text);
    expect(texts.filter((t) => t.includes("已落盘"))).toHaveLength(1);
    expect(texts.filter((t) => t.trim() === "回合失败后新发的消息")).toHaveLength(2);
  });

  it("历史为空（新引擎/新会话）时本地用户消息全保留", () => {
    const merged = mergeHistoryItems(current.items, []);
    expect(merged.filter((item) => item.kind === "user")).toHaveLength(3);
  });
});
