"""B11/E 环最小调度器：ownership / quota_hold / bot_loop_guard / occurrences（v3 §9）。

铁律：调度器**只经 ``submissions`` 入队**（``source='scheduler'``），绝不直接建 Run、绝不
append ``event_log``。tick 自身用 ``run_leases`` 的 ``sched:main`` 行做多进程所有权；
每个 occurrence 有 ``execution_identity``（ContextVar）串起因果。
"""

from __future__ import annotations

from questor.schedule.scheduler import Scheduler, ScheduleSpec, current_execution_identity

__all__ = ["ScheduleSpec", "Scheduler", "current_execution_identity"]
