/** 4a 可用闭环：wire 帧驱动的最小对话壳（throwaway，4b-6 删除）。 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import styles from "./App.module.css";
import { ErrorBoundary } from "../shared/ui-kit/ErrorBoundary";
import { createWireRuntime, WireError } from "../shared/transport/wireRuntime";
import type { HistoryResponse, ProfileResponse } from "../shared/transport/wireTypes";
import { applyFrame, historyItems, initialState, type ViewItem, type ViewState } from "./viewModel";

const runtime = createWireRuntime();

function itemRow(item: ViewItem, onApprove: (id: string, ok: boolean) => void, onAsk: (id: string, text: string) => void) {
  switch (item.kind) {
    case "user":
      return (
        <div className={styles.row}>
          <span className={styles.badge}>你</span>
          {item.text}
        </div>
      );
    case "say":
      return (
        <div className={styles.row}>
          <span className={styles.badge}>助手</span>
          <span style={{ whiteSpace: "pre-wrap" }}>{item.text}</span>
        </div>
      );
    case "tool":
      return (
        <div className={styles.row}>
          <span className={styles.badge}>工具</span>
          <span className={styles.tool}>
            {item.tool} · {item.status}
          </span>
          {item.output ? <pre style={{ whiteSpace: "pre-wrap", margin: "4px 0 0" }}>{item.output}</pre> : null}
        </div>
      );
    case "notice":
      return (
        <div className={`${styles.row} ${styles.notice}`}>
          <span className={styles.badge}>提示</span>
          {item.text}
        </div>
      );
    case "compaction":
      return (
        <div className={`${styles.row} ${styles.notice}`}>
          <span className={styles.badge}>压缩</span>
          {item.status} · {item.phase}
        </div>
      );
    case "turn":
      return (
        <div className={styles.row}>
          <span className={styles.badge}>回合</span>
          <span className={styles.tool}>{item.label}</span>
        </div>
      );
    case "approval":
      return (
        <div className={styles.prompt}>
          <div>
            需要审批：<strong>{item.tool}</strong> · {item.subject}
          </div>
          {item.detail ? <pre style={{ whiteSpace: "pre-wrap" }}>{item.detail}</pre> : null}
          <div className={styles.actions}>
            <button data-action="approve" onClick={() => onApprove(item.promptId, true)}>
              允许
            </button>
            <button className={styles.secondary} data-action="deny" onClick={() => onApprove(item.promptId, false)}>
              拒绝
            </button>
          </div>
        </div>
      );
    case "ask":
      return <AskRow item={item} onAsk={onAsk} />;
  }
}

function AskRow({ item, onAsk }: { item: Extract<ViewItem, { kind: "ask" }>; onAsk: (id: string, text: string) => void }) {
  const [answer, setAnswer] = useState("");
  return (
    <div className={styles.prompt}>
      <div>提问：{item.question}</div>
      <div className={styles.actions}>
        <input value={answer} onChange={(event) => setAnswer(event.target.value)} data-action="ask-input" />
        <button data-action="ask-submit" onClick={() => onAsk(item.promptId, answer)}>
          回答
        </button>
      </div>
    </div>
  );
}

export function App() {
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [state, setState] = useState<ViewState>(initialState);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState(false);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const reloadHistory = useCallback(async () => {
    const loaded = await runtime.history();
    setHistory(loaded);
    setState((current) => ({ ...current, items: historyItems(loaded.messages) }));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    void (async () => {
      try {
        setProfile(await runtime.profile());
        await reloadHistory();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
        return;
      }
      while (!disposed && !controller.signal.aborted) {
        try {
          let last = state.lastSeq;
          for await (const { seq, frame } of runtime.events(last, controller.signal)) {
            last = seq;
            if (frame.kind === "stream_reset") {
              await reloadHistory();
              break;
            }
            setState((current) => applyFrame(current, frame));
          }
        } catch (exc) {
          if (controller.signal.aborted) return;
          if (exc instanceof WireError && exc.code.startsWith("auth.")) {
            setError("会话凭据失效：请通过宿主重新打开访问链接");
            return;
          }
          setError(exc instanceof Error ? exc.message : String(exc));
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }
    })();
    return () => {
      disposed = true;
      controller.abort();
    };
    // 事件循环只启动一次；lastSeq 由闭包内的本地变量推进。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadHistory]);

  const rows = useMemo(() => [...(history ? [] : []), ...state.items], [history, state.items]);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 56,
    overscan: 8,
  });

  const submit = async () => {
    const line = draft.trim();
    if (!line || state.busy) return;
    setError(null);
    setQueued(false);
    setState((current) => ({ ...current, busy: true, items: [...current.items, { id: `user-${Date.now()}`, kind: "user", text: line }] }));
    setDraft("");
    try {
      const result = await runtime.submit(line, crypto.randomUUID());
      setQueued(result.state === "queued");
    } catch (exc) {
      setState((current) => ({ ...current, busy: false }));
      setError(exc instanceof WireError ? `${exc.code}: ${exc.message}` : String(exc));
    }
  };

  const stop = async () => {
    try {
      await runtime.cancel();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const onApprove = async (id: string, ok: boolean) => {
    try {
      await runtime.approve(id, ok ? "approve" : "deny");
    } catch (exc) {
      setError(exc instanceof WireError ? `${exc.code}: ${exc.message}` : String(exc));
    }
  };

  const onAsk = async (id: string, text: string) => {
    try {
      await runtime.ask(id, text);
    } catch (exc) {
      setError(exc instanceof WireError ? `${exc.code}: ${exc.message}` : String(exc));
    }
  };

  return (
    <div className={styles.root}>
      <header className={styles.header}>
        <span>Questor</span>
        <span>{profile ? `${profile.name} · ${Object.entries(profile.ui.capabilities).filter(([, v]) => v === "ready").map(([k]) => k).join(" / ")}` : "连接中"}</span>
        <span className={styles.status}>{state.busy ? "回合进行中" : "空闲"}</span>
      </header>
      {error ? <div className={styles.banner}>{error}</div> : null}
      {queued ? <div className={styles.banner}>已排队，当前回合结束后开始</div> : null}
      <div className={styles.transcript} ref={scrollRef}>
        {rows.length === 0 ? <div className={styles.empty}>输入一句话开始。</div> : null}
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const item = rows[virtualRow.index];
            return (
              <div
                key={item.id}
                ref={virtualizer.measureElement}
                data-index={virtualRow.index}
                style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${virtualRow.start}px)` }}
              >
                <ErrorBoundary label={item.kind}>{itemRow(item, onApprove, onAsk)}</ErrorBoundary>
              </div>
            );
          })}
        </div>
      </div>
      <div className={styles.composer}>
        <textarea
          value={draft}
          placeholder="Enter 发送，Shift+Enter 换行"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
          data-action="composer"
        />
        {state.busy ? (
          <button className={styles.secondary} data-action="stop" onClick={() => void stop()}>
            停止
          </button>
        ) : (
          <button data-action="send" onClick={() => void submit()} disabled={!draft.trim()}>
            发送
          </button>
        )}
      </div>
    </div>
  );
}
