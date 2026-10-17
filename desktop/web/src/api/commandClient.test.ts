// P7 T5：命令提交客户端单测 —— 只投既有 HTTP 端点、绝不第二写入口；错误出声不静默。
// （真 webview + 真 sidecar HTTP 属 UNVERIFIED；此处用注入的假 fetch 验**调用形状**这一瘦客户端契约。）
import { describe, expect, it } from "vitest";

import { CommandClient, type Receipt } from "./commandClient";

interface Call {
  url: string;
  method?: string;
  body: unknown;
}

function fakeFetch(responder: (url: string) => { ok: boolean; status?: number; json: unknown }): { calls: Call[]; fetch: (u: string, i?: RequestInit) => Promise<Response> } {
  const calls: Call[] = [];
  const fetchImpl = async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const r = responder(url);
    return {
      ok: r.ok,
      status: r.status ?? (r.ok ? 200 : 500),
      json: async () => r.json,
    } as unknown as Response;
  };
  return { calls, fetch: fetchImpl };
}

const ok = () => ({ ok: true, json: { status: "accepted" } });

describe("CommandClient", () => {
  it("run → POST /run 带 text/run_id", async () => {
    const f = fakeFetch(ok);
    const c = new CommandClient("http://127.0.0.1:1", f.fetch);
    await c.run("hello", "run_9");
    expect(f.calls[0]).toEqual({ url: "http://127.0.0.1:1/run", method: "POST", body: { text: "hello", run_id: "run_9" } });
  });

  it("cancel/resolve/permissions/resume 各投对应端点（无旁路写）", async () => {
    const f = fakeFetch(ok);
    const c = new CommandClient("http://h", f.fetch);
    await c.cancel("r1");
    const receipt: Receipt = await c.resolveApproval("r1", "apr1", "deny");
    await c.setPermissionMode("r1", "plan");
    await c.resume("r1");
    expect(f.calls.map((x) => x.url)).toEqual([
      "http://h/runs/r1/cancel",
      "http://h/runs/r1/approvals/apr1/resolve",
      "http://h/runs/r1/permissions",
      "http://h/runs/r1/resume",
    ]);
    expect(f.calls[1].body).toEqual({ decision: "deny" });
    expect(f.calls[2].body).toEqual({ mode: "plan" });
    expect(receipt.status).toBe("accepted");
  });

  it("审批决策域锁死 allow|deny，越域即抛（不把非法意图投进 inbox）", async () => {
    const f = fakeFetch(ok);
    const c = new CommandClient("http://h", f.fetch);
    await expect(c.resolveApproval("r1", "apr1", "maybe")).rejects.toThrow(/decision/);
    expect(f.calls).toHaveLength(0); // 越域不发出任何请求
  });

  it("权限模式域锁死 default|plan|full_auto", async () => {
    const f = fakeFetch(ok);
    const c = new CommandClient("http://h", f.fetch);
    await expect(c.setPermissionMode("r1", "yolo")).rejects.toThrow(/mode/);
    expect(f.calls).toHaveLength(0);
  });

  it("非 2xx 出声（错误类不静默，C6）", async () => {
    const f = fakeFetch(() => ({ ok: false, status: 409, json: { status: "rejected", reason: "terminal" } }));
    const c = new CommandClient("http://h", f.fetch);
    await expect(c.cancel("r1")).rejects.toThrow(/HTTP 409/);
  });
});
