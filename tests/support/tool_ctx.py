"""测试用受控 ToolContext（不经生产 loop，直接驱动工具 execute）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from questor.contracts.common import JsonObject


class FakeToolContext:
    """实现 contracts.tool.ToolContext 协议的最小可控对象。"""

    def __init__(self, workspace_root: Path, *, cancelled: bool = False, tool_call_id: str = "tc") -> None:
        self.workspace_root = workspace_root
        self.cwd = workspace_root
        self.tool_call_id = tool_call_id
        self._cancelled = cancelled
        self.declared: list[str] = []
        self.run_process_calls: list[object] = []
        self.artifact_calls: list[bytes] = []

    def is_cancelled(self) -> bool:
        return self._cancelled

    def report_progress(self, message: str) -> None:
        pass

    def emit_progress(self, payload: JsonObject) -> None:
        pass

    def declare_env_passthrough(self, name: str) -> None:
        self.declared.append(name)

    async def run_process(self, request: object) -> object:
        self.run_process_calls.append(request)
        raise NotImplementedError("set a real runner in the loop for process tools")

    async def put_artifact(self, content: bytes, *, kind: str, media_type: str = "text/plain") -> object:
        self.artifact_calls.append(content)
        raise NotImplementedError("set a real artifact store in the loop")


def run(coroutine: object) -> object:
    return asyncio.run(coroutine)  # type: ignore[arg-type]
