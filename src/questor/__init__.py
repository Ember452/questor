"""Questor —— 从零自研的桌面通用个人 Agent Harness。

分层地图（L0 最内 → L6 最外；依赖只能指向更内层）：

- :mod:`questor.contracts`   L0 共享词汇（schema、事件、ToolSpec、各 Port 接口）
- :mod:`questor.state`       L1 Domain_State + reduce
- :mod:`questor.kernel`      L2 Harness 运行时（循环、事件总线、权限）
- :mod:`questor.capabilities` L3 工具 / skills / mcp
- :mod:`questor.policy`      L4 可插拔 Agent 策略（PolicyPort）
- :mod:`questor.providers`   L5 端口适配器（LiteLLM、SQLite、时钟、id）
- :mod:`questor.surfaces`    L6 传输（CLI、HTTP+SSE）——零业务逻辑

P0 交付可编译接口骨架（stub 签名 + 分层守卫）；行为自 P1 起。详见
``docs/plan/00-design-skeleton.md``。
"""

from questor.version import __version__

__all__ = ["__version__"]
