/** wire-native 传输：7 个端点 + SSE 帧流。唯一允许发请求的模块。 */

import type {
  HistoryResponse,
  ProfileResponse,
  ServerFrame,
  SubmitResponse,
} from "./wireTypes";

const PREFIX = "/rt/r1";

export class WireError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "WireError";
  }
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(PREFIX + path, {
    credentials: "same-origin",
    ...init,
  });
  if (!response.ok) {
    let code = `http.${response.status}`;
    let message = response.statusText;
    try {
      const payload = (await response.json()) as { code?: string; message?: string };
      code = payload.code ?? code;
      message = payload.message ?? message;
    } catch {
      /* 非 JSON 错误体：保留状态码 */
    }
    throw new WireError(code, message, response.status);
  }
  return (await response.json()) as T;
}

function post(path: string, body?: unknown): RequestInit {
  return {
    method: "POST",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

/** 增量解析 SSE 字节：只认带 `id:` 的帧块（心跳不带 id，跳过——见 wireRuntime.test.ts）。 */
export async function* readFrames(
  response: Response,
): AsyncGenerator<{ seq: number; frame: ServerFrame }> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      let index = buffer.indexOf("\n\n");
      while (index >= 0) {
        const block = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        let seq = 0;
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("id: ")) seq = Number(line.slice(4));
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        // 无 id 的块是心跳：watermark 只作活性信号，不是帧，也不得回卷游标。
        if (seq > 0 && data) yield { seq, frame: JSON.parse(data) as ServerFrame };
        index = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export interface WireRuntime {
  profile(id?: string): Promise<ProfileResponse>;
  history(): Promise<HistoryResponse>;
  submit(line: string, clientRequestId: string): Promise<SubmitResponse>;
  cancel(): Promise<void>;
  approve(id: string, decision: "approve" | "deny"): Promise<void>;
  ask(id: string, answer: string): Promise<void>;
  events(lastEventId: number, signal: AbortSignal): AsyncGenerator<{
    seq: number;
    frame: ServerFrame;
  }>;
}

export function createWireRuntime(): WireRuntime {
  return {
    profile(id) {
      return jsonRequest<ProfileResponse>(`/profile${id ? `?id=${encodeURIComponent(id)}` : ""}`);
    },
    history() {
      return jsonRequest<HistoryResponse>("/history");
    },
    submit(line, clientRequestId) {
      return jsonRequest<SubmitResponse>("/submit", post("/submit", { line, clientRequestId }));
    },
    async cancel() {
      await jsonRequest<{ ok: boolean }>("/cancel", post("/cancel"));
    },
    async approve(id, decision) {
      await jsonRequest<{ ok: boolean }>("/approve", post("/approve", { id, decision }));
    },
    async ask(id, answer) {
      await jsonRequest<{ ok: boolean }>("/ask", post("/ask", { id, answer }));
    },
    async *events(lastEventId, signal) {
      const response = await fetch(`${PREFIX}/events`, {
        credentials: "same-origin",
        signal,
        headers: {
          Accept: "text/event-stream",
          ...(lastEventId > 0 ? { "Last-Event-ID": String(lastEventId) } : {}),
        },
      });
      if (!response.ok) {
        throw new WireError(`http.${response.status}`, response.statusText, response.status);
      }
      yield* readFrames(response);
    },
  };
}
