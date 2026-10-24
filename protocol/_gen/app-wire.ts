/**
 * AUTO-GENERATED from protocol/app-wire.schema.json. DO NOT EDIT.
 *
 * This file is the contract, not a convenience shape: every field here must be
 * carried by the Python side (serve/wire_types.py) or the mirror guard fails.
 */

/**
 * Single source of truth for the studio wire protocol. One schema, two generators (Python serve/wire_types.py and TypeScript protocol/_gen/app-wire.ts). Adding a kind is additive; renaming or removing one is a breaking change.
 */
export type QuestorAppWireProtocol = ServerFrame;
/**
 * Downstream SSE frame union.
 */
export type ServerFrame =
  | TurnStarted
  | Text
  | Message
  | ToolDispatch
  | ToolResult
  | ApprovalRequest
  | AskRequest
  | Notice
  | CompactionStarted
  | CompactionProgress
  | CompactionDone
  | TurnDone
  | StreamReset;
/**
 * Flattened ConversationMessage content block; input payloads stay on the engine side.
 */
export type ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock;

export interface TurnStarted {
  seq: number;
  kind: "turn_started";
  turnId: string;
  index: number;
  via: "cli" | "studio" | "api";
}
export interface Text {
  seq: number;
  kind: "text";
  text: string;
}
export interface Message {
  seq: number;
  kind: "message";
  blocks: ContentBlock[];
  usage?: Usage;
}
export interface TextBlock {
  type: "text";
  text: string;
}
export interface ImageBlock {
  type: "image";
  mediaType: string;
}
export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
}
export interface ToolResultBlock {
  type: "tool_result";
  toolUseId: string;
  content: string;
  isError: boolean;
}
/**
 * Mirror of contracts/usage.py UsageSnapshot.
 */
export interface Usage {
  inputTokens: number;
  outputTokens: number;
}
export interface ToolDispatch {
  seq: number;
  kind: "tool_dispatch";
  toolCallId: string;
  tool: string;
}
export interface ToolResult {
  seq: number;
  kind: "tool_result";
  toolCallId: string;
  tool: string;
  output: string;
  isError: boolean;
}
export interface ApprovalRequest {
  seq: number;
  kind: "approval_request";
  id: string;
  tool: string;
  subject: string;
}
export interface AskRequest {
  seq: number;
  kind: "ask_request";
  id: string;
  question: string;
}
export interface Notice {
  seq: number;
  kind: "notice";
  level: "info" | "warning" | "error";
  text: string;
}
export interface CompactionStarted {
  seq: number;
  kind: "compaction_started";
  trigger: "auto" | "manual" | "reactive";
}
export interface CompactionProgress {
  seq: number;
  kind: "compaction_progress";
  phase:
    | "hooks_start"
    | "context_collapse_start"
    | "context_collapse_end"
    | "session_memory_start"
    | "session_memory_end"
    | "compact_start"
    | "compact_retry"
    | "compact_end"
    | "compact_failed";
  attempt?: number;
  message?: string;
}
export interface CompactionDone {
  seq: number;
  kind: "compaction_done";
  trigger: "auto" | "manual" | "reactive";
  ok: boolean;
}
export interface TurnDone {
  seq: number;
  kind: "turn_done";
  turnId: string;
  cancelled: boolean;
  outcome: "completed" | "cancelled" | "failed";
  durationMs: number;
  checkpointTurn: boolean;
  usage?: Usage;
}
export interface StreamReset {
  seq: number;
  kind: "stream_reset";
  reason: "replay_gap" | "server_restart";
}
