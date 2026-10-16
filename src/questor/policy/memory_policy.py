"""L4 记忆感知策略示例（design/05 §1/§5；ADR-0023/0026；T15）。

演示"**记忆作为可插拔策略、不耦合 Kernel**"：只读 ``PolicyView.memory``（有界检索命中投影），在
无未闭合工具、准备收尾时，把已召回记忆摘要附到最终答复前——全程只出意图，不碰执行/权限/存储句柄。

诚实边界（与 DoD④ 一致）：当前 ``DefaultTurnLoop._ask_policy`` 构造 ``PolicyView`` 时**不**自动填充
``view.memory``——若把"检索记忆并塞进视图"写进 L2 内核，就正正违反了"换记忆策略不动 loop"。因此：

- 操作化的 P4 记忆路径 = ``memory_search`` 工具（agent 驱动，T12）+ 可插拔 ``MemoryStrategyConfig``
  （T10，换权重/半衰期即换检索行为，loop 零 diff）——这两处才是 DoD④ 的主证据。
- 本策略是 **L4 消费 ``view.memory`` 的接缝示例**：一旦某个 harness 变体把有界命中填入 ``PolicyView.memory``
  （例如经只读分支快照重放，design/05 §5），此策略立即生效，**无需改内核**。
"""

from __future__ import annotations

from questor.contracts.policy import PolicyIntent, PolicyView, SuggestFinish
from questor.policy.react_policy import ReActPolicy

#: 注入最终答复的召回摘要字节上限（有界，防 prompt 膨胀，HARD C18/ADR-0019）。
_RECALL_MAX_CHARS = 2000


class MemoryAwareReActPolicy(ReActPolicy):
    """ReAct + 记忆消费：收尾时把有界召回记忆前置到最终答复；其余行为与 ReAct 一致。"""

    id = "react-memory"
    fingerprint = "react-memory:1"

    def propose_action(self, view: PolicyView) -> PolicyIntent:
        intent = super().propose_action(view)
        if isinstance(intent, SuggestFinish) and view.memory:
            # 去重保序地取有界片段（snippet 已在检索侧被 size-capped），前置召回标记。
            seen: list[str] = []
            for hit in view.memory:
                snippet = hit.snippet.strip()
                if snippet and snippet not in seen:
                    seen.append(snippet)
            recalled = "; ".join(seen)[:_RECALL_MAX_CHARS]
            base = intent.final_text or ""
            merged = f"[recalled memory] {recalled}\n{base}".strip()
            return SuggestFinish(final_text=merged or None)
        return intent


__all__ = ["MemoryAwareReActPolicy"]
