// P7 T4/T5/T6/T7：桌面薄客户端 UI。仅消费事件协议 + 投 Command，绝不做业务/权限/状态计算（S6/C14/C17）。
// 连接 same-origin 的 sidecar（webview 指向本服务，ADR-0007）；EventSource 原生带 Last-Event-ID 重连。
import { CommandClient } from "./api/commandClient";
import { formatCitations } from "./api/citations";
import { ThreadEventStream } from "./api/eventStream";
import { statusBanner } from "./api/status";
import { EVENT_TYPE_NAMES } from "./generated/event";
import type { QuestorExternalEventProjectionV1 as Event } from "./generated/event";
import type { SidecarStatus } from "./generated/sidecarStatus";

// 订阅 UI 关心的事件类型（均来自协议）。EventSource 只对命名事件分发，故逐类型 addEventListener。
const EVENT_TYPES: readonly string[] = EVENT_TYPE_NAMES;

// 会话 token：壳把 bootstrap 里的 token 经 URL 查询注入（http://127.0.0.1:port/?token=…）；前端读取后
// 随写命令头/事件流查询带上。无 token 的本地其它进程会被服务端 401 拒（HITL 不被本机旁路）。
const bootToken = new URLSearchParams(window.location.search).get("token") ?? undefined;
const client = new CommandClient(window.location.origin, (...a) => fetch(...a), bootToken);
const log = document.getElementById("log") as HTMLDivElement;
const input = document.getElementById("input") as HTMLInputElement;
const composer = document.getElementById("composer") as HTMLFormElement;
const cancelBtn = document.getElementById("cancel") as HTMLButtonElement;

let currentRunId: string | null = null;
let source: EventSource | null = null;
let stream: ThreadEventStream | null = null;
let assistantBubble: HTMLElement | null = null;
let liveDeltaSeen = false;

function el(tag: string, cls: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function appendText(target: HTMLElement, text: string): void {
  target.appendChild(document.createTextNode(text));
}

// B14：把“你为什么知道这个”的条目级归因挂在定稿消息下方。**只读事件 data**，
// 不反查记忆库、不推断引用（那会变成前端的第二份业务逻辑，S6）。
function renderCitations(data: unknown): void {
  const line = formatCitations(data);
  if (!line) return; // 无引用就不画节点（不画“来源：（无）”）
  log.appendChild(el("div", "citations", line));
}

// live 文本增量：起/续一个 assistant 气泡并追加（流式上屏）。
function renderDelta(_itemId: string | null, text: string): void {
  if (!assistantBubble) assistantBubble = el("div", "msg assistant");
  liveDeltaSeen = true;
  appendText(assistantBubble, text);
  log.appendChild(assistantBubble);
}

// durable 事件渲染：只把协议字段画出来，不解释语义。
function renderEvent(env: Event): void {
  switch (env.type) {
    case "message_completed": {
      // 断线重连/晚订阅时，live delta 可能错过；message_completed 的有界 final_text（D-P7-C①）补回定稿文本。
      if (!liveDeltaSeen) {
        const finalText = (env.data as { final_text?: unknown }).final_text;
        if (typeof finalText === "string" && finalText) {
          if (!assistantBubble) assistantBubble = el("div", "msg assistant");
          assistantBubble.textContent = finalText;
          log.appendChild(assistantBubble);
        }
      }
      assistantBubble = null; // 下一条消息另起气泡
      liveDeltaSeen = false;
      renderCitations(env.data); // 定稿消息之后：条目级来源
      break;
    }
    case "tool_started": {
      const d = env.data as { name?: unknown };
      const card = el("div", "tool-card");
      card.appendChild(el("span", "tool-name", `🔧 ${typeof d.name === "string" ? d.name : "tool"}`));
      log.appendChild(card);
      break;
    }
    case "tool_completed": {
      const d = env.data as { status?: unknown; preview?: unknown; truncated?: unknown };
      const card = el("div", "tool-card");
      card.appendChild(el("span", "tool-status", `[${typeof d.status === "string" ? d.status : "?"}]`));
      if (typeof d.preview === "string" && d.preview) {
        card.appendChild(el("pre", "tool-preview", d.preview + (d.truncated ? " …" : "")));
      }
      log.appendChild(card);
      break;
    }
    case "approval_request": {
      renderApproval(env);
      break;
    }
    default:
      break; // 其它 durable 事件：本极简面板不呈现（但已消费、不崩）。
  }
}

function renderApproval(env: Event): void {
  const d = env.data as { request_id?: unknown; name?: unknown; args_summary?: unknown };
  const requestId = typeof d.request_id === "string" ? d.request_id : "";
  const panel = el("div", "approval");
  panel.appendChild(el("div", "approval-body", `批准 ${String(d.name ?? "?")}：${String(d.args_summary ?? "")}？`));
  const respond = (decision: "allow" | "deny") => {
    panel.querySelectorAll("button").forEach((b) => ((b as HTMLButtonElement).disabled = true));
    void client.resolveApproval(currentRunId ?? "", requestId, decision).catch(() => {
      panel.appendChild(el("div", "approval-error", "审批提交失败（fail-closed）"));
    });
  };
  const allow = el("button", "allow", "Allow");
  const deny = el("button", "deny", "Deny");
  allow.addEventListener("click", () => respond("allow"));
  deny.addEventListener("click", () => respond("deny"));
  panel.append(allow, deny);
  log.appendChild(panel);
}

function renderError(env: Event): void {
  const d = env.data as { error?: { message?: unknown }; message?: unknown; reason?: unknown };
  const msg = String(d.error?.message ?? d.message ?? d.reason ?? "error");
  log.appendChild(el("div", "error", `⚠ ${msg}`)); // 错误类必出声（C6）
}

function stopStream(): void {
  source?.close();
  source = null;
}

function openStream(runId: string): void {
  currentRunId = runId;
  assistantBubble = null;
  liveDeltaSeen = false;
  stream = new ThreadEventStream({
    onDelta: renderDelta,
    onEvent: renderEvent,
    onTerminal: stopStream,
    onError: renderError,
    onResync: () => {
      log.appendChild(el("div", "warn", "协议版本变更，需重新握手"));
      stopStream();
    },
  });
  const query = bootToken ? `?token=${encodeURIComponent(bootToken)}` : "";
  const es = new EventSource(`/events/${runId}${query}`);
  source = es;
  const handle = (ev: MessageEvent): void => {
    try {
      stream?.receive(JSON.parse(ev.data) as Event);
    } catch {
      // 单帧解码失败不崩宿主；错误类事件必出声由各自处理器负责，未知帧静默（C6）。
    }
  };
  for (const type of EVENT_TYPES) es.addEventListener(type, handle as EventListener);
  // 传输级收尾帧（§6-8）：非领域事件，不送 ThreadEventStream.receive，直接干净停流、不再重连。
  es.addEventListener("stream_end", () => stopStream());
  // 不自己实现重连：交给浏览器 EventSource 的自动重连 + 服务端 Last-Event-ID 续传（不重不丢）。
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  log.appendChild(el("div", "msg user", text));
  void client
    .run(text)
    .then((ack) => openStream(ack.run_id))
    .catch((err: unknown) => {
      // 错误类必出声（C6）：带上 CommandClient 抛出的真实 HTTP 状态，便于定位 401/5xx/断连。
      const msg = err instanceof Error ? err.message : String(err);
      log.appendChild(el("div", "error", `启动 run 失败：${msg}`));
    });
});

cancelBtn.addEventListener("click", () => {
  if (!currentRunId) return;
  void client.cancel(currentRunId).catch(() => {
    /* 取消是投 Command；终态由事件流反映 */
  });
});

// §6-5：订阅壳（Rust）发的进程级 sidecar_status——Tauri event，非 per-run SSE（sidecar 崩了 SSE 也断了）。
// __TAURI__ 缺失（非桌面环境/未注入全局）时静默跳过，绝不在浏览器 dev 里抛错。
const tauriEvents = (window as unknown as {
  __TAURI__?: { event?: { listen: <T>(name: string, handler: (e: { payload: T }) => void) => Promise<unknown> } };
}).__TAURI__;
if (tauriEvents?.event?.listen) {
  void tauriEvents.event
    .listen<SidecarStatus>("sidecar_status", (e) => {
      const banner = statusBanner(e.payload);
      if (banner) log.appendChild(el("div", banner.level === "warn" ? "error" : "warn", banner.text));
    })
    // capability 未对当前 origin 授权时静默降级（横幅不显示，不冲击命令/事件流主链路），不刷未捕获拒绝。
    .catch(() => undefined);
}
