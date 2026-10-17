// P7 T5/T6：命令提交客户端 —— 桌面**只**经既有 HTTP 端点投 Command（C16 Command Inbox 唯一外部写入口）。
// 绝不在前端造第二写入口、绝不直连 store/reduce（S6/C16/C17）；权限/审批的**判定**全在 Harness，
// 这里只把用户选择（decision/mode，取自协议枚举）投进对应 run 的 inbox。
// 端点形状对齐 surfaces/http_sse.py：/run · /runs/{id}/cancel · /runs/{id}/approvals/{request_id}/resolve
// · /runs/{id}/permissions · /runs/{id}/resume。

export type Decision = "allow" | "deny"; // 协议 approval_resolved.decision 域
export type PermissionMode = "default" | "plan" | "full_auto"; // 协议 permission_mode_changed.mode 域

const DECISIONS: ReadonlySet<string> = new Set<Decision>(["allow", "deny"]);
const MODES: ReadonlySet<string> = new Set<PermissionMode>(["default", "plan", "full_auto"]);

export interface Receipt {
  status: string;
  reason?: string;
}

export interface RunAck {
  run_id: string;
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** 只对允许的命令域做**协议形状**校验（越域即抛，防把非法意图投进 inbox）；不做任何业务/权限判定。 */
function assertDomain<T extends string>(value: string, allowed: ReadonlySet<string>, name: string): asserts value is T {
  if (!allowed.has(value)) {
    throw new Error(`${name} must be one of ${[...allowed].join("|")}, got ${JSON.stringify(value)}`);
  }
}

/**
 * 命令提交客户端。`fetchImpl` 可注入以便单测；生产用浏览器 fetch。
 * 依赖：HTTP（loopback sidecar 基址）；失败语义：非 2xx 由调用方按 receipt/异常处理（错误类不静默）。
 */
export class CommandClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: FetchLike = (...a) => fetch(...a),
  ) {}

  private async postJson<T>(path: string, body: unknown): Promise<T> {
    const resp = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    // >=400 时后端已抛 HTTPException（映射 receipt 码），这里把非 2xx 显式出声、绝不吞。
    if (!resp.ok) {
      throw new Error(`command ${path} failed: HTTP ${resp.status}`);
    }
    return (await resp.json()) as T;
  }

  run(text: string, runId?: string): Promise<RunAck> {
    return this.postJson<RunAck>("/run", { text, run_id: runId });
  }

  cancel(runId: string): Promise<Receipt> {
    return this.postJson<Receipt>(`/runs/${runId}/cancel`, {});
  }

  /** HITL 审批回执：带 request_id 幂等（同 request 同决策 no-op、异决策被后端拒）——幂等由服务端裁决。 */
  async resolveApproval(runId: string, requestId: string, decision: string): Promise<Receipt> {
    assertDomain<Decision>(decision, DECISIONS, "decision");
    return this.postJson<Receipt>(`/runs/${runId}/approvals/${requestId}/resolve`, { decision });
  }

  async setPermissionMode(runId: string, mode: string): Promise<Receipt> {
    assertDomain<PermissionMode>(mode, MODES, "mode");
    return this.postJson<Receipt>(`/runs/${runId}/permissions`, { mode });
  }

  resume(runId: string): Promise<RunAck> {
    return this.postJson<RunAck>(`/runs/${runId}/resume`, {});
  }
}
