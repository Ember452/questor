"""L4 Policy —— 可插拔的 Agent 策略，实现 ``PolicyPort``。

读只读视图 → 出单步意图。拥有提示词/算法，**不**拥有模型路由、审批/denylist、沙箱、
持久化写（design/05）。由内核经注入使用。"""
