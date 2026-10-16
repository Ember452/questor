"""L5 Port 协议（design/00 §3.1；HARD C1/C4/C9/C12）。

Port 是最内层的抽象接口；具体适配器（LiteLLM、SQLite、沙箱后端）住在
:mod:`questor.providers`，以**注入**方式交给内核。内核只 import 这些协议、绝不
import 实现（C1/C14）。P0 固定签名，实现体自 P1 起。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from questor.contracts.common import JsonObject
from questor.contracts.sandbox import SandboxDescriptor, SandboxPort
from questor.contracts.state_schema import Message
from questor.contracts.tool import ToolSpec


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """一次模型调用的请求描述（消息 + 工具 + 采样设置）。"""

    model: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    system: str | None = None
    stream: bool = True
    settings: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """一段归一化的流式增量；内核据此映射为 ``*_delta`` / tool_use / usage。"""

    kind: str  # text | reasoning | tool_call | usage | finish
    text: str | None = None
    tool_call: JsonObject | None = None
    usage: JsonObject | None = None
    finish_reason: str | None = None
    raw: Any | None = None


@runtime_checkable
class ProviderPort(Protocol):
    """模型访问端口。错误分类是纯函数（进 contracts），此处只产出归一化增量。"""

    async def stream(self, request: ProviderRequest):  # -> AsyncIterator[StreamChunk]
        """产出归一化 chunk；调用方负责按 ADR-0010 分类处置错误。"""
        ...


@runtime_checkable
class StorePort(Protocol):
    """append-only 事件日志 + 快照读写（design/01 §9；ADR-0005/0011/0020/0022）。

    唯一持久化路径；策略不持裸句柄（C4）。P3 起承载两类游标：per-run 逻辑 ``seq``
    （SSE ``after_seq`` 续传）与全局单调物理 ``gseq``（跨 run catch-up watermark，ADR-0011）。
    新方法是 **纯增量**（不改既有签名/信封/关联键，C6）；仅在 resume/发现路径被调用。
    """

    async def append(self, run_id: str, events: tuple[JsonObject, ...]) -> int: ...

    async def replay(
        self, run_id: str, after_seq: int, limit: int | None = None
    ) -> list[JsonObject]: ...

    async def sequence_head(self, run_id: str) -> int: ...

    async def save_checkpoint(self, checkpoint: JsonObject) -> None: ...

    async def latest_checkpoint(self, run_id: str) -> JsonObject | None: ...

    async def watermark(self) -> int:
        """当前全局物理序头部（无事件则 0）；跨 run catch-up 的水位基线。"""
        ...

    async def replay_global(
        self, after_watermark: int, limit: int | None = None
    ) -> list[JsonObject]:
        """跨 run 重放全局 ``gseq > after_watermark`` 的事件，按全局序返回（携 run_id/seq）。"""
        ...

    async def checkpoint_seq(self, run_id: str) -> int | None:
        """该 run 最近快照的 ``seq``（尾重放起点）；无快照返回 ``None``。"""
        ...

    async def list_unfinished_runs(self) -> tuple[str, ...]:
        """从 log 派生非终态 run id（有事件但无终态事件）；供 ``--resume`` 枚举。"""
        ...


@runtime_checkable
class Clock(Protocol):
    """时间端口：墙上时间 + 单调时钟（退避/超时须同基准，R08 B-P2）。"""

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class IdGenerator(Protocol):
    """id 生成端口（默认实现见 ``common.new_id``；测试可注入定序实现）。"""

    def new(self, prefix: str) -> str: ...


__all__ = [
    "ProviderRequest",
    "StreamChunk",
    "ProviderPort",
    "StorePort",
    "Clock",
    "IdGenerator",
    "SandboxDescriptor",
    "SandboxPort",
]
