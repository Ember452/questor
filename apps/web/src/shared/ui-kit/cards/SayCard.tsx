/** 对话卡：Reasonix SayCard 的语义移植（结构/交互，不引入其 state 层）。 */

import { useEffect, useState } from "react";

import { t } from "../../i18n";
import styles from "./cards.module.css";

export function SayCard({ text, streaming }: { text: string; streaming: boolean }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1200);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <article className={styles.card} data-card="say">
      <div className={styles.header}>
        <span>{t("助手")}</span>
        {text ? (
          <button
            className={styles.header}
            style={{ marginLeft: "auto", background: "transparent", border: 0, cursor: "pointer" }}
            data-action="copy-say"
            onClick={() => {
              void navigator.clipboard?.writeText(text);
              setCopied(true);
            }}
          >
            {copied ? t("已复制") : t("复制")}
          </button>
        ) : null}
      </div>
      <div className={`${styles.say} ${streaming ? styles.streaming : ""}`}>{text}</div>
    </article>
  );
}
