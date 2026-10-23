"""Default port instances shared by the engine composition points."""

from __future__ import annotations

from questorharness.runtime.services.subagent_runtime import DefaultSubagentRuntime
from questorharness.runtime.services.task_runtime import DefaultTaskRuntime

default_task_runtime = DefaultTaskRuntime()
default_subagent_runtime = DefaultSubagentRuntime()

__all__ = ["DefaultSubagentRuntime", "DefaultTaskRuntime", "default_subagent_runtime", "default_task_runtime"]
