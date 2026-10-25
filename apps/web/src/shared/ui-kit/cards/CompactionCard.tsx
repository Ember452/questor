/** 压缩卡：started/progress/done 三态折叠展示。 */

import styles from "./cards.module.css";

export function CompactionCard({ phase, status }: { phase: string; status: "started" | "progress" | "done" }) {
  return (
    <article className={styles.card} data-card="compaction">
      <div className={styles.header}>
        <span>上下文压缩</span>
        <span className={styles.phase}>
          {status} · {phase}
        </span>
      </div>
    </article>
  );
}
