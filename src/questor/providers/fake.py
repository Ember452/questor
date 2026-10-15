"""测试与离线演示用的确定性 ``ProviderPort`` 替身。

回放一份脚本化的 “turn” 序列——每个 turn 就是模型本应产出的一串 ``StreamChunk``。
无网络、无需密钥，让循环的 DoD（happy path + cancel + deny + 非法意图）可重复验证。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import ClassVar

from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk


class ScriptedProvider(ProviderPort):
    """按预定脚本逐 turn 回放 chunk 的测试替身；脚本用尽后礼貌地发 finish 收尾。"""

    turns: list[list[StreamChunk]]
    _index: int

    def __init__(self, turns: list[list[StreamChunk]]) -> None:
        self.turns = turns
        self._index = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        if self._index >= len(self.turns):  # 脚本耗尽 -> 礼貌收尾，避免越界
            yield StreamChunk(kind="finish", finish_reason="stop")
            return
        for chunk in self.turns[self._index]:
            yield chunk
        self._index += 1


class EchoProvider(ProviderPort):
    """最小 provider：只流式一段写死的答复、不调用工具（离线冒烟演示用）。"""

    answer: ClassVar[str] = "echo: got your message."

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        for token in self.answer.split(" "):
            yield StreamChunk(kind="text", text=token + " ")
        yield StreamChunk(kind="finish", finish_reason="stop")
