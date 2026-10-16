"""L? 记忆子系统（design/06；ADR-0023）。

与运行态 ``state/`` 分离的独立子系统，持有记忆的**算法**（切块 / 混合检索融合 / 时间衰减 /
Deep Dream 蒸馏），只依赖 ``contracts``（数据 + Port 抽象），**绝不 import 外层**
（kernel/policy/surfaces/providers，HARD C1/C14）。存储由 ``providers/store_memory_sqlite.py``
实现 ``MemoryStorePort``，本子系统被 kernel/composition-root 编排调用。

分库纪律：记忆落独立 ``memory.db`` + md 文件真源，与 event-log 分家（ADR-0023/R03 D-P1）。
"""
