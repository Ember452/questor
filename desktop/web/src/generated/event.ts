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
    | "memory_written"
    | "peer_started"
    | "peer_ended"
    | "tools_changed"
    | "compact_started"
    | "compact_applied"
    | "user_message";
  data: {
    [k: string]: unknown;
  };
};

// ── per-type event data payloads (field-level; a schema field change not reflected here fails --check) ──
/**
 * Run accepted. policy_ref is an additive snapshot identity (P9/ADR-0045): resolved once at run creation and frozen for the whole run; A/B routes by fingerprint. Optional keeps v1 additive (no bump).
 */
export interface RunStartedData {
  run_id: string;
  policy_ref?: {
    id: string;
    fingerprint: string;
  };
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
/**
 * Parent spawned a child agent run (P8; ADR-0042). Correlation keys only, never payload.
 */
export interface PeerStartedData {
  parent_run_id: string;
  child_run_id: string;
  node_id: string;
}
/**
 * Child agent run reached a terminal state, reported to parent (P8; ADR-0042). result_ref is an opaque artifact pointer, never the body (C18/C20).
 */
export interface PeerEndedData {
  parent_run_id: string;
  child_run_id: string;
  node_id: string;
  terminal_status: "completed" | "failed" | "cancelled";
  result_ref?: string | null;
  resumable_hint?: boolean;
}
/**
 * Capability roster changed (P9/ADR-0046): live-only advisory, no payload; consumers re-fetch the roster for future runs. Not persisted, never logged (C20).
 */
export interface ToolsChangedData {
  domain: "tools" | "skills" | "mcp" | "plugins" | "settings";
}
/**
 * Kernel began recoverable context compaction at a turn boundary (P10/ADR-0048, design/02 §10). reason is a short kernel label; no payload, never the summary text (C18/C20).
 */
export interface CompactStartedData {
  reason: string;
}
/**
 * Compaction applied; baseline_seq is the durable seq that rewrote context so renderers re-fold their view (design/02 §10). covered_from/covered_to are the evicted durable event seq range (originals read back from append-only event_log); summary_bytes is the summary size only, never its text (C20).
 */
export interface CompactAppliedData {
  baseline_seq: number;
  covered_from: number;
  covered_to: number;
  summary_bytes: number;
}
/**
 * User-originated message body persisted into the fact stream (B1; design §4.2). text is the bounded user-originated text (maxLength = OutputBudget.model_result_bytes; injected scaffolding stripped before persisting); truncated=true when the stored body was cut. Full body stays authoritative in the checkpoint. Not logged (C20).
 */
export interface UserMessageData {
  text: string;
  truncated?: boolean;
}
