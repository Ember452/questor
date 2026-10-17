/* AUTO-GENERATED from protocol/event.schema.json. DO NOT EDIT. */

/**
 * Single source of truth for the external event envelope (HARD C6/C15; design/02). Additive-only: new `type` values and optional `data` fields are allowed; existing semantics must not change. Per-type `data` is a strict whitelist (additionalProperties:false, bounded strings). CI --check prevents drift against questor.contracts.events.EventType and requires a $defs branch for every type.
 */
export type QuestorExternalEventProjectionV1 = {
  [k: string]: unknown;
} & {
  /**
   * Wire-contract version; bump only on breaking change.
   */
  v: number;
  /**
   * Per-run monotonic logical cursor (after_seq resume).
   */
  seq: number;
  run_id: string;
  turn?: number | null;
  /**
   * UTC, timezone-aware.
   */
  ts: string;
  type:
    | "run_started"
    | "turn_started"
    | "text_delta"
    | "reasoning_delta"
    | "message_completed"
    | "tool_started"
    | "tool_progress"
    | "tool_completed"
    | "approval_request"
    | "approval_resolved"
    | "permission_mode_changed"
    | "node_updated"
    | "usage_delta"
    | "heartbeat"
    | "run_cancelled"
    | "run_failed"
    | "run_completed"
    | "resync_required"
    | "warning"
    | "memory_written";
  data: {
    [k: string]: unknown;
  };
};
