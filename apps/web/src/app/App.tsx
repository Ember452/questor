/** 应用壳：导航来自 registry + capability 门控；数据来自 wire 帧。 */

import { useCallback, useEffect, useState } from "react";

import { isVisible } from "./capabilityGate";
import { DemoScreen } from "./DemoScreen";
import { PAGES } from "../pages/registry";
import { createWireRuntime, WireError } from "../shared/transport/wireRuntime";
import type { ProfileResponse } from "../shared/transport/wireTypes";
import { applyFrame, historyItems, initialState, type ViewState } from "./viewModel";
import styles from "./App.module.css";

const runtime = createWireRuntime();

export function App() {
  // 截图/回放样本：不进入 live 事件循环，也不违反 hooks 规则。
  if (new URLSearchParams(window.location.search).has("demo")) {
    return <DemoScreen />;
  }
  return <LiveApp />;
}

function LiveApp() {
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [view, setView] = useState<ViewState>(initialState);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState(false);
  const [activeId, setActiveId] = useState<string>("chat");

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme = media.matches ? "dark" : "light";
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  const reloadHistory = useCallback(async () => {
    const loaded = await runtime.history();
    setView((current) => ({ ...current, items: historyItems(loaded.messages) }));
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
      let last = 0;
      while (!disposed && !controller.signal.aborted) {
        try {
          for await (const { seq, frame } of runtime.events(last, controller.signal)) {
            last = seq;
            if (frame.kind === "stream_reset") {
              await reloadHistory();
              break;
            }
            setView((current) => applyFrame(current, frame));
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
  }, [reloadHistory]);

  const send = (line: string) => {
    setError(null);
    setQueued(false);
    setView((current) => ({
      ...current,
      busy: true,
      items: [...current.items, { id: `user-${Date.now()}`, kind: "user", text: line }],
    }));
    runtime
      .submit(line, crypto.randomUUID())
      .then((result) => setQueued(result.state === "queued"))
      .catch((exc: unknown) => {
        setView((current) => ({ ...current, busy: false }));
        setError(exc instanceof WireError ? `${exc.code}: ${exc.message}` : String(exc));
      });
  };

  const cancel = () => {
    runtime.cancel().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc)));
  };

  const approve = (id: string, approved: boolean) => {
    runtime
      .approve(id, approved ? "approve" : "deny")
      .catch((exc: unknown) => setError(exc instanceof WireError ? `${exc.code}: ${exc.message}` : String(exc)));
  };

  const ask = (id: string, answer: string) => {
    runtime
      .ask(id, answer)
      .catch((exc: unknown) => setError(exc instanceof WireError ? `${exc.code}: ${exc.message}` : String(exc)));
  };

  const capabilities = profile?.ui.capabilities ?? {};
  const visible = PAGES.filter((page) => isVisible(page, capabilities));
  const active = visible.find((page) => page.id === activeId) ?? visible[0];
  const Page = active?.component;

  return (
    <div className={styles.root}>
      <header className={styles.header}>
        <span>Questor</span>
        <nav className={styles.nav} aria-label="主导航">
          {visible.map((page) => (
            <button
              key={page.id}
              className={page.id === active?.id ? styles.tabActive : styles.tab}
              data-action={`nav-${page.id}`}
              onClick={() => setActiveId(page.id)}
            >
              {page.title}
            </button>
          ))}
        </nav>
        <span className={styles.status}>
          {profile ? profile.name : "连接中"} · {view.busy ? "回合进行中" : "空闲"}
        </span>
      </header>
      {error ? <div className={styles.banner}>{error}</div> : null}
      {queued ? <div className={styles.banner}>已排队，当前回合结束后开始</div> : null}
      {Page ? (
        <Page
          runtime={runtime}
          view={view}
          onSend={send}
          onCancel={cancel}
          onApprove={approve}
          onAsk={ask}
        />
      ) : (
        <div className={styles.empty}>当前形态没有可用页面（capability 均为 declared/absent）。</div>
      )}
    </div>
  );
}
