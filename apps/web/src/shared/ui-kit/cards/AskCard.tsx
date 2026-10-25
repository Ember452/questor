/** 提问卡：输入 + 提交（空输入即“未回答”）。 */

import { useState } from "react";

import { t } from "../../i18n";
import styles from "./cards.module.css";

export function AskCard({ question, onAnswer }: { question: string; onAnswer: (answer: string) => void }) {
  const [answer, setAnswer] = useState("");
  return (
    <article className={styles.card} data-card="ask">
      <div className={styles.header}>{t("提问")}</div>
      <div>{question}</div>
      <input
        className={styles.input}
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        data-action="ask-input"
        onKeyDown={(event) => {
          if (event.key === "Enter") onAnswer(answer);
        }}
      />
      <div className={styles.actions}>
        <button data-action="ask-submit" onClick={() => onAnswer(answer)}>
          {t("回答")}
        </button>
      </div>
    </article>
  );
}
