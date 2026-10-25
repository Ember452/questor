/** 对话页：虚拟化 transcript + 五卡分发 + 精简 Composer。 */

import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import { CARD_SLOTS } from "../app/cardSlots";
import type { ViewItem } from "../app/viewModel";
import { t } from "../shared/i18n";
import { ErrorBoundary } from "../shared/ui-kit/ErrorBoundary";
import { ApprovalCard } from "../shared/ui-kit/cards/ApprovalCard";
import { AskCard } from "../shared/ui-kit/cards/AskCard";
import { CompactionCard } from "../shared/ui-kit/cards/CompactionCard";
import { SayCard } from "../shared/ui-kit/cards/SayCard";
import { ToolCard } from "../shared/ui-kit/cards/ToolCard";
import styles from "../app/App.module.css";
import type { PageProps } from "./types";

function renderItem(item: ViewItem, props: PageProps) {
  switch (item.kind) {
    case "user":
      return (
        <div className={styles.row}>
          <span className={styles.badge}>{t("你")}</span>
          {item.text}
        </div>
      );
    case "say":
      return <SayCard text={item.text} streaming={item.streaming} />;
    case "tool":
      return <ToolCard tool={item.tool} status={item.status} output={item.output} />;
    case "approval":
      return (
        <ApprovalCard
          tool={item.tool}
          subject={item.subject}
          detail={item.detail}
          onDecide={(approved) => props.onApprove(item.promptId, approved)}
        />
      );
    case "ask":
      return <AskCard question={item.question} onAnswer={(answer) => props.onAsk(item.promptId, answer)} />;
    case "compaction":
      return <CompactionCard phase={item.phase} status={item.status} />;
    case "notice":
      return (
        <div className={`${styles.row} ${styles.notice}`}>
          <span className={styles.badge}>{t("提示")}</span>
          {item.text}
        </div>
      );
    case "turn":
      return (
        <div className={styles.row}>
          <span className={styles.badge}>{t("回合")}</span>
          <span className={styles.tool}>{item.label}</span>
        </div>
      );
    default: {
      // 穷尽守卫：viewModel 新增 item kind 而这里漏写 = tsc 编译红（不再静默落空）。
      const exhaustive: never = item;
      return <div className={styles.row}>{String(exhaustive)}</div>;
    }
  }
}

/** 槽位存在性守卫：item.kind 必须在 CARD_SLOTS 里出现（cardSlots 是唯一映射源）。 */
const SLOT_ITEMS = new Set(Object.values(CARD_SLOTS).map((slot) => slot.item));

export function ChatPage(props: PageProps) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const rows = useMemo(
    () => props.view.items.filter((item) => SLOT_ITEMS.has(item.kind)),
    [props.view.items],
  );
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 64,
    overscan: 8,
  });

  const send = () => {
    const line = draft.trim();
    if (!line || props.view.busy) return;
    setDraft("");
    props.onSend(line);
  };

  return (
    <>
      <div className={styles.transcript} ref={scrollRef} data-page="chat">
        {rows.length === 0 ? <div className={styles.empty}>{t("输入一句话开始。")}</div> : null}
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
                <ErrorBoundary label={item.kind}>{renderItem(item, props)}</ErrorBoundary>
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
              send();
            }
          }}
          data-action="composer"
        />
        {props.view.busy ? (
          <button className={styles.secondary} data-action="stop" onClick={props.onCancel}>
            {t("停止")}
          </button>
        ) : (
          <button data-action="send" onClick={send} disabled={!draft.trim()}>
            {t("发送")}
          </button>
        )}
      </div>
    </>
  );
}
