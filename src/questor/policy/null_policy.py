"""L4 策略占位实现——最小可用的 ``PolicyPort`` 桩（design/05）。

P1 T11 会用它换上的 ReAct 取代。``propose_action`` 返回一个不可信单步意图，内核执行前
再校验（design/04 L1）。注册/发现/AB 归 P9；这里只保留 ``id``/``fingerprint``。
"""

from __future__ import annotations

from questor.contracts.policy import PolicyIntent, PolicyPort, PolicyView


class NullPolicy(PolicyPort):
    """什么都不做的策略占位；用于演示接口，实际策略见 ReActPolicy。"""

    id = "null"
    fingerprint = "null:0"

    def propose_action(self, view: PolicyView) -> PolicyIntent:
        raise NotImplementedError("ReAct strategy lands in P1 (T11)")


__all__ = ["NullPolicy"]
