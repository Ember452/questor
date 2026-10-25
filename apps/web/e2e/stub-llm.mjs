/**
 * Stub LLM（OpenAI 兼容 SSE）：驱动 Playwright 真回合 e2e，不碰真模型。
 *
 * 行为按请求体自适应（无状态、按内容判断，天然支持多回合重试）：
 * - 消息里含 role=tool（工具已执行）→ 流式回一段固定文本收尾；
 * - 否则（首轮）→ 流式回一个 Bash tool_call（echo questor-stub-ok），
 *   让引擎走完整的 审批 → 执行 → 二次调用 → turn_done 链路。
 *
 * 握手：stdout 首行 {"port":N}。teardown 由 global-teardown 统一回收。
 */
import http from "node:http";

const FINAL_TEXT = "工具结果已收到，测试通过。";

function sse(res, payload) {
  res.write(`data: ${JSON.stringify(payload)}\n\n`);
}

const server = http.createServer((req, res) => {
  if (req.method !== "POST" || !req.url.includes("/chat/completions")) {
    res.writeHead(404).end();
    return;
  }
  let body = "";
  req.on("data", (chunk) => {
    body += chunk;
  });
  req.on("end", () => {
    let hasToolResult = false;
    try {
      const parsed = JSON.parse(body);
      hasToolResult = (parsed.messages ?? []).some((m) => m.role === "tool");
    } catch {
      /* 坏体按首轮处理 */
    }
    res.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      connection: "keep-alive",
    });
    const base = { id: "stub", object: "chat.completion.chunk", created: 0, model: "stub" };
    sse(res, { ...base, choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }] });
    if (hasToolResult) {
      for (const part of [FINAL_TEXT.slice(0, 5), FINAL_TEXT.slice(5)]) {
        sse(res, { ...base, choices: [{ index: 0, delta: { content: part }, finish_reason: null }] });
      }
      sse(res, {
        ...base,
        choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
      });
    } else {
      sse(res, {
        ...base,
        choices: [
          {
            index: 0,
            delta: {
              tool_calls: [
                {
                  index: 0,
                  id: "call_stub_1",
                  type: "function",
                  function: { name: "bash", arguments: JSON.stringify({ command: "echo questor-stub-ok" }) },
                },
              ],
            },
            finish_reason: null,
          },
        ],
      });
      sse(res, {
        ...base,
        choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }],
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
      });
    }
    res.write("data: [DONE]\n\n");
    res.end();
  });
});

server.listen(0, "127.0.0.1", () => {
  const { port } = server.address();
  process.stdout.write(`${JSON.stringify({ port })}\n`);
});
