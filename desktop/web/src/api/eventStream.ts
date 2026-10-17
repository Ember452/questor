// P7 T4：SSE 瘦客户端 —— 只消费事件协议，绝不下沉业务/状态/校验/权限（STRUCTURE S6 / HARD C14/C17）。
// 这里只做**传输层**该做的事：按 `seq` 游标去重、live delta 按 `item_id` 缓冲、终态帧停流、
// 错误类事件（run_failed/warning/resync_required）绝不静默（C6 例外款）。
// 事件 `type` 一律取自 codegen 产物 `generated/event.ts`（T9 瘦客户端守卫要求"仅从 generated/ 导入"）。
import type { QuestorExternalEventProjectionV1 as Event } from "../generated/event";

/** 外部协议里的 live-only 类型：只转发、不做 durable seq 去重（design/02 / kernel LIVE_ONLY 对齐）。 */
const LIVE_ONLY: ReadonlySet<string> = new Set([
  "text_delta",
  "reasoning_delta",
  "tool_progress",
  "heartbeat",
  "usage_delta",
]);

/** 终态帧：一轮恰一个（C13），收到即停流、终止渲染。 */
const TERMINAL: ReadonlySet<string> = new Set(["run_completed", "run_cancelled", "run_failed"]);

/** 错误类事件：未知也必须出声，绝不静默丢弃（HARD C6 例外款；protocol/README §错误类必出声）。 */
const ERROR_CLASS: ReadonlySet<string> = new Set(["run_failed", "warning", "resync_required"]);

export interface StreamHandlers {
  /** 一条 durable 事件被接受（seq 前进后）；用于渲染消息/工具卡/审批等协议对象。 */
  onEvent?: (env: Event) => void;
  /** live 文本增量到达（按 item_id 归属，前端 upsert 到对应消息）。 */
  onDelta?: (itemId: string | null, text: string) => void;
  /** 终态帧（completed/cancelled）；此后 done=true、不再处理后续帧。 */
  onTerminal?: (env: Event) => void;
  /** 错误类：run_failed / warning 出声（不得被节流吞掉）。 */
  onError?: (env: Event) => void;
  /** 版本闸门：收到 resync_required 即停，交上层重新握手（不跨版本解码，ADR-0007/design/02 §10）。 */
  onResync?: (env: Event) => void;
}

/**
 * 单条 run 的事件流游标消费者。纯逻辑（不持有网络句柄），便于单测；
 * 实际 `EventSource` 的接线（重连、`after_seq`/`Last-Event-ID` 头）在 connect 侧，真渲染属 UNVERIFIED。
 */
export class ThreadEventStream {
  private cursor = 0;
  private done = false;
  readonly segments = new Map<string, string>(); // item_id -> 累积文本（live delta 缓冲，非状态）

  constructor(private readonly handlers: StreamHandlers) {}

  get isDone(): boolean {
    return this.done;
  }

  get lastSeq(): number {
    return this.cursor;
  }

  /**
   * 处理一条已解码信封。返回 true 表示该帧被接受（durable 前进或 live/错误类出声），false 表示丢弃（重复/滞后/终态后）。
   */
  receive(env: Event): boolean {
    if (this.done) {
      return false; // 终态后停流：任何后续帧一律忽略（避免把回滚/迟到误当作新状态，C10）
    }
    const type = env.type as string;

    if (LIVE_ONLY.has(type)) {
      if (type === "text_delta") {
        const delta = typeof env.data.delta === "string" ? env.data.delta : "";
        const itemId = typeof env.data.item_id === "string" ? env.data.item_id : null;
        const key = itemId ?? env.run_id;
        this.segments.set(key, (this.segments.get(key) ?? "") + delta);
        this.handlers.onDelta?.(itemId, delta);
      }
      // 其余 live-only（reasoning/progress/heartbeat/usage）：转发但不入 durable 游标。
      this.handlers.onEvent?.(env);
      return true;
    }

    // durable：按 seq 游标去重（断线重连不重；乱序滞后帧丢弃）。
    if (env.seq <= this.cursor) {
      return false;
    }
    this.cursor = env.seq;

    if (ERROR_CLASS.has(type)) {
      // 错误类绝不静默：run_failed/warning → onError；resync_required → onResync 且停流。
      if (type === "resync_required") {
        this.done = true;
        this.handlers.onResync?.(env);
      } else {
        if (type === "run_failed") {
          this.done = true;
        }
        this.handlers.onError?.(env);
      }
      return true;
    }

    this.handlers.onEvent?.(env);
    if (TERMINAL.has(type)) {
      this.done = true;
      this.handlers.onTerminal?.(env);
    }
    return true;
  }
}
