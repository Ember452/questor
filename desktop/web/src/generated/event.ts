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

// ── per-type event data payloads (field-level; a schema field change not reflected here fails --check) ──
export interface RunStartedData {
  run_id: string;
}
export interface TurnStartedData {
  turn: number;
}
export interface TextDeltaData {
  delta: string;
  item_id?: string | null;
}
export interface ReasoningDeltaData {
  delta: string;
}
/**
 * A finalized message (D-P7-C option (1); ADR-0034). final_text is the bounded committed body so after_seq replay alone recovers text for every surface; oversized bodies set truncated (full text stays authoritative in checkpoint). Not logged (C20).
 */
export interface MessageCompletedData {
  message_id: string;
  item_id?: string | null;
  final_text?: string;
  truncated?: boolean;
}
export interface ToolStartedData {
  tool_call_id: string;
  name: string;
  capability: "readonly" | "write" | "exec" | "network" | "memory";
  risk: "low" | "medium" | "high";
  args_summary: string;
}
export interface ToolProgressData {
  message: string;
}
export interface ToolCompletedData {
  tool_call_id: string;
  status: "success" | "error" | "critical_error" | "timed_out" | "cancelled" | "denied";
  /**
   * Bounded tool-output preview for the card (C18/ADR-0019). Never the full text; read full body via artifact_ref. Not logged (C20).
   */
  preview?: string;
  /**
   * Opaque artifact:// pointer for the full output when archived. Never an absolute path.
   */
  artifact_ref?: string | null;
  /**
   * True when preview was cut or the full body lives behind artifact_ref.
   */
  truncated?: boolean;
}
export interface ApprovalRequestData {
  request_id: string;
  tool_call_id: string;
  name: string;
  args_summary: string;
  risk: "low" | "medium" | "high";
  reason: string;
  expires_at: string;
}
export interface ApprovalResolvedData {
  request_id: string;
  tool_call_id: string;
  decision: "allow" | "deny";
  decided_by: string;
  resolved_at: string;
}
export interface PermissionModeChangedData {
  mode: "default" | "plan" | "full_auto";
  changed_by: string;
  effective_from_turn: number;
}
/**
 * Task-tree node projection (DAG belongs to P8; no producer yet). P7 T11 additive-shaped to a bounded whitelist (C18/C13): node identity/status only, never payload.
 */
export interface NodeUpdatedData {
  node_id: string;
  status: string;
  title?: string | null;
  parent_id?: string | null;
}
export interface UsageDeltaData {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
}
export interface HeartbeatData {}
export interface RunCancelledData {
  reason: string;
}
export interface RunFailedData {
  error: {
    code?: string;
    message?: string;
    retryable?: boolean;
  };
}
export interface RunCompletedData {
  usage: {
    [k: string]: unknown;
  };
  exit_reason?: string | null;
}
export interface ResyncRequiredData {
  reason: string;
  expected: number;
  current: number;
}
export interface WarningData {
  message: string;
}
/**
 * Bounded memory-write acknowledgement (ADR-0024/0026): condensed facts only, never raw text; oversized content is referenced via artifact_ref.
 */
export interface MemoryWrittenData {
  kind: "core" | "daily" | "distill";
  chunk_count: number;
  source?: string | null;
  artifact_ref?: string | null;
}
