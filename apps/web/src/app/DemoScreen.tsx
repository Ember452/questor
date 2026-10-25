/** 仅测试/截图用：用黄金帧回放一屏五卡（`/?demo=1`），不发任何网络请求。 */

import fixtures from "../generated/wire-fixtures.json";
import type { ServerFrame } from "../shared/transport/wireTypes";
import { ApprovalCard } from "../shared/ui-kit/cards/ApprovalCard";
import { AskCard } from "../shared/ui-kit/cards/AskCard";
import { CompactionCard } from "../shared/ui-kit/cards/CompactionCard";
import { SayCard } from "../shared/ui-kit/cards/SayCard";
import { ToolCard } from "../shared/ui-kit/cards/ToolCard";
import { applyFrame, initialState } from "./viewModel";
import styles from "./App.module.css";

const frames = (fixtures as unknown as ServerFrame[]).slice().sort((a, b) => a.seq - b.seq);
const view = frames.reduce(applyFrame, initialState);

export function DemoScreen() {
  return (
    <div className={styles.root}>
      <header className={styles.header}>
        <span>Questor</span>
        <span className={styles.status}>截图样本 · 13 帧黄金回放</span>
      </header>
      <div className={styles.transcript} data-page="demo">
        {view.items.map((item) => {
          switch (item.kind) {
            case "say":
              return <SayCard key={item.id} text={item.text} streaming={item.streaming} />;
            case "tool":
              return <ToolCard key={item.id} tool={item.tool} status={item.status} output={item.output} />;
            case "approval":
              return (
                <ApprovalCard
                  key={item.id}
                  tool={item.tool}
                  subject={item.subject}
                  detail={item.detail}
                  onDecide={() => {}}
                />
              );
            case "ask":
              return <AskCard key={item.id} question={item.question} onAnswer={() => {}} />;
            case "compaction":
              return <CompactionCard key={item.id} phase={item.phase} status={item.status} />;
            case "notice":
              return (
                <div key={item.id} className={`${styles.row} ${styles.notice}`}>
                  {item.text}
                </div>
              );
            case "turn":
              return (
                <div key={item.id} className={styles.row}>
                  <span className={styles.badge}>回合</span>
                  {item.label}
                </div>
              );
            case "user":
              return (
                <div key={item.id} className={styles.row}>
                  <span className={styles.badge}>你</span>
                  {item.text}
                </div>
              );
          }
        })}
      </div>
    </div>
  );
}
