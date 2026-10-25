/** 审批卡：三档按钮 + detail（编辑类补丁摘要）。 */

import { t } from "../../i18n";
import styles from "./cards.module.css";

export function ApprovalCard({
  tool,
  subject,
  detail,
  onDecide,
}: {
  tool: string;
  subject: string;
  detail: string;
  onDecide: (approved: boolean) => void;
}) {
  return (
    <article className={styles.card} data-card="approval" role="alertdialog" aria-label="需要审批">
      <div className={styles.header}>
        <span>{t("需要审批")}</span>
        <span className={styles.tool}>{tool}</span>
        <span>{subject}</span>
      </div>
      {detail ? <pre className={styles.detail}>{detail}</pre> : null}
      <div className={styles.actions}>
        <button data-action="approve" onClick={() => onDecide(true)}>
          {t("允许")}
        </button>
        <button
          data-action="deny"
          style={{ background: "transparent", border: "1px solid var(--border-subtle, #334155)" }}
          onClick={() => onDecide(false)}
        >
          {t("拒绝")}
        </button>
      </div>
    </article>
  );
}
