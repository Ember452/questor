/** 清单卡（plan03 W-D4）：路径 + 完成计数 + 逐项勾选态，对齐 Reasonix todos.go。 */

import { t } from "../../i18n";
import styles from "./cards.module.css";

export type TodoRow = { text: string; checked: boolean };

export function TodoCard({ path, rows }: { path: string; rows: TodoRow[] }) {
  const done = rows.filter((row) => row.checked).length;
  return (
    <article className={styles.card} data-card="todos">
      <div className={styles.header}>
        <span>{t("清单")}</span>
        <span className={styles.phase}>
          {path} · {done}/{rows.length}
        </span>
      </div>
      {rows.length === 0 ? (
        <p className={styles.empty}>{t("还没有清单项")}</p>
      ) : (
        <ul className={styles.list}>
          {rows.map((row, index) => (
            <li key={`${index}-${row.text}`} className={row.checked ? styles.done : undefined}>
              <span aria-hidden="true">{row.checked ? "✓" : "○"}</span> {row.text}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
