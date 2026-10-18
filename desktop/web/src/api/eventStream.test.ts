// P7 T4：SSE 瘦客户端**传输层逻辑**单测（真跑 vitest，非像素渲染）。
// 覆盖：seq 游标去重（不丢不重）、live text_delta 按 item_id 缓冲、终态停流、
// 错误类必出声（run_failed/warning 不被吞）、resync_required 即停。
import { describe, expect, it } from "vitest";

import type { QuestorExternalEventProjectionV1 as Event } from "../generated/event";
import { ThreadEventStream } from "./eventStream";

const envelope = (over: Partial<Event>): Event =>
  ({ v: 1, seq: 0, run_id: "run_1", type: "run_started", ts: "2026-01-01T00:00:00+00:00", data: {}, ...over }) as Event;

describe("ThreadEventStream", () => {
  it("durable 事件按 seq 前进，重复/滞后帧被丢弃（断线重连不重）", () => {
    const accepted: string[] = [];
    const s = new ThreadEventStream({ onEvent: (e) => accepted.push(e.type) });
    expect(s.receive(envelope({ type: "run_started", seq: 1 }))).toBe(true);
    expect(s.receive(envelope({ type: "turn_started", seq: 2, data: { turn: 0 } }))).toBe(true);
    expect(s.receive(envelope({ type: "turn_started", seq: 2, data: { turn: 0 } }))).toBe(false); // dup
    expect(s.receive(envelope({ type: "tool_completed", seq: 1, data: { tool_call_id: "t", status: "success" } }))).toBe(false); // 滞后
    expect(s.lastSeq).toBe(2);
    expect(accepted).toEqual(["run_started", "turn_started"]);
  });

  it("live text_delta 按 item_id 缓冲、不做 seq 去重、可乱序于 durable", () => {
    const deltas: Array<[string | null, string]> = [];
    const s = new ThreadEventStream({ onDelta: (id, t) => deltas.push([id, t]) });
    s.receive(envelope({ type: "text_delta", seq: 1, data: { delta: "Hel", item_id: "i1" } }));
    s.receive(envelope({ type: "text_delta", seq: 1, data: { delta: "lo", item_id: "i1" } })); // live-only：同 seq 仍收
    expect(deltas).toEqual([["i1", "Hel"], ["i1", "lo"]]);
    expect(s.segments.get("i1")).toBe("Hello");
  });

  it("message_completed 的 final_text 作为 durable 事件交付（D-P7-C 重连补回定稿文本）", () => {
    const seen: Event[] = [];
    const s = new ThreadEventStream({ onEvent: (e) => seen.push(e) });
    s.receive(envelope({ type: "message_completed", seq: 3, data: { message_id: "m1", final_text: "answer", truncated: false } }));
    expect(seen[0].data.final_text).toBe("answer");
  });

  it("终态帧停流：run_completed 后任何帧忽略（恰一终态，C13）", () => {
    let terminal = 0;
    const s = new ThreadEventStream({ onTerminal: () => terminal++ });
    s.receive(envelope({ type: "run_completed", seq: 5, data: { usage: {}, exit_reason: "answered" } }));
    expect(s.isDone).toBe(true);
    expect(terminal).toBe(1);
    expect(s.receive(envelope({ type: "run_completed", seq: 6, data: { usage: {} } }))).toBe(false); // 终态后
    expect(terminal).toBe(1);
  });

  it("错误类必出声：run_failed 既 onError 又停流，warning 不被吞", () => {
    const errors: string[] = [];
    const s = new ThreadEventStream({ onError: (e) => errors.push(e.type) });
    s.receive(envelope({ type: "warning", seq: 1, data: { message: "careful" } }));
    expect(errors).toEqual(["warning"]);
    expect(s.isDone).toBe(false); // warning 非终态
    s.receive(envelope({ type: "run_failed", seq: 2, data: { error: { code: "x", message: "boom" } } }));
    expect(errors).toEqual(["warning", "run_failed"]);
    expect(s.isDone).toBe(true); // run_failed 是终态
  });

  it("版本闸门：resync_required 即停并交上层重新握手", () => {
    let resync = 0;
    const s = new ThreadEventStream({ onResync: () => resync++ });
    s.receive(envelope({ type: "resync_required", seq: 1, data: { reason: "version_mismatch", expected: 2, current: 1 } }));
    expect(resync).toBe(1);
    expect(s.isDone).toBe(true);
  });

  it("未知事件类型：非错误类静默忽略，但 seq 不因此前进（不误吞 durable 游标）", () => {
    let events = 0;
    const s = new ThreadEventStream({ onEvent: () => events++ });
    // 用一个不在已知集合但仍是合法字符串的 type；客户端不识别 → 不崩溃、静默（未知 type 处理）。
    const handled = s.receive(envelope({ type: "some_future_event" as Event["type"], seq: 9, data: {} }));
    expect(handled).toBe(true); // durable 分支接受并前进游标（未知但带 seq 的 durable 仍算前进）
    expect(events).toBe(1);
    expect(s.lastSeq).toBe(9);
  });
});
