/** 工具卡：Running/Done/Error 三态 + 原位展开输出。 */

import { useState } from "react";

import { t } from "../../i18n";
import styles from "./cards.module.css";

const STATUS: Record<string, string> = { running: t("执行中"), done: t("完成"), error: t("错误") };

export function ToolCard({
  tool,
  status,
  output,
}: {
  tool: string;
  status: "running" | "done" | "error";
  output: string;
}) {
  const [open, setOpen] = useState(status !== "done");
  return (
    <article className={styles.card} data-card="tool">
      <div className={styles.header}>
        <span className={styles.tool}>{tool}</span>
        <span className={status === "error" ? styles.error : styles.ok}>{STATUS[status] ?? status}</span>
        {output ? (
          <button
            style={{ marginLeft: "auto", background: "transparent", border: 0, cursor: "pointer", color: "inherit" }}
            data-action="toggle-tool"
            onClick={() => setOpen((value) => !value)}
          >
            {open ? t("收起") : t("展开")}
          </button>
        ) : null}
      </div>
      {open && output ? <pre className={styles.output}>{output}</pre> : null}
    </article>
  );
}
