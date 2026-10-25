/** HTTP 响应的本地类型（不是 wire 帧；帧类型只来自 generated/app-wire）。 */

import type { ContentBlock, Usage } from "../../generated/app-wire";

export type { ServerFrame } from "../../generated/app-wire";

export interface ProfileResponse {
  id: string;
  name: string;
  description: string;
  ui: { capabilities: Record<string, "ready" | "declared" | "absent"> };
}

export interface HistoryMessage {
  role: string;
  blocks: ContentBlock[];
}

export interface HistoryResponse {
  sessionId: string;
  messages: HistoryMessage[];
}

export interface SubmitResponse {
  turnId: string;
  state: "started" | "queued";
  position?: number;
}

export interface UsageTotals {
  inputTokens: number;
  outputTokens: number;
}

export type { Usage };
