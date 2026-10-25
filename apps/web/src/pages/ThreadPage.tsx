/** 会话快照页：`/history` 的只读视图（当前会话）。 */

import { useEffect, useState } from "react";

import styles from "../app/App.module.css";
import type { HistoryResponse } from "../shared/transport/wireTypes";
import type { PageProps } from "./types";

export function ThreadPage({ runtime }: PageProps) {
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    runtime
      .history()
      .then((value) => {
        if (alive) setHistory(value);
      })
      .catch((exc: unknown) => {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      });
    return () => {
      alive = false;
    };
  }, [runtime]);

  return (
    <div className={styles.transcript} data-page="thread">
      {error ? <div className={styles.banner}>{error}</div> : null}
      {history ? (
        <>
          <div className={styles.row}>
            <span className={styles.badge}>会话</span>
            <span className={styles.tool}>{history.sessionId}</span> · {history.messages.length} 条消息
          </div>
          {history.messages.map((message, index) => (
            <div className={styles.row} key={`${message.role}-${index}`}>
              <span className={styles.badge}>{message.role === "user" ? "你" : "助手"}</span>
              <span style={{ whiteSpace: "pre-wrap" }}>
                {message.blocks.map((block) => (block.type === "text" ? block.text : `[${block.type}]`)).join("")}
              </span>
            </div>
          ))}
        </>
      ) : (
        <div className={styles.empty}>加载中…</div>
      )}
    </div>
  );
}
