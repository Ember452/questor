"""横切：配置/secrets 加载层（**预留**）。

规划中本层集中配置加载与 secrets 边界；当前阶段 env 读取按“组合根职责”落在
``composition.build_app`` / ``surfaces._assembly``，本包尚未落地实现（除本 docstring 外无模块）。
与 observability 相互独立（见 .importlinter）；不得被 L0/L1 import。
真建成本层实现时以 ADR 记入分层，避免“文档声称有、代码未接线”的名不副实。"""
