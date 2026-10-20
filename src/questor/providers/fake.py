"""测试与离线演示用的确定性 ``ProviderPort`` / ``EmbeddingPort`` 替身。

回放一份脚本化的 “turn” 序列——每个 turn 就是模型本应产出的一串 ``StreamChunk``。
无网络、无需密钥，让循环的 DoD（happy path + cancel + deny + 非法意图）可重复验证。

`FakeEmbedder` 同理：由 sha256 派生的确定性向量，**只证向量通道接得通**（同一文本永远
得到同一向量），真检索质量标 UNVERIFIED（§6.2：CI 无密钥时的合法替身）。
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from typing import ClassVar

from questor.contracts.memory import EmbeddingPort
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


class FakeEmbedder(EmbeddingPort):
    """确定性 embedding：sha256 字节 → 归一化向量（**只产向量，不碰存储**，§20 C-3）。

    同一个文本任何时候都得到同一个向量（可重放/可比），但"语义质量"不存在——
    它存在的意义只是让向量通道在 CI 里真实跑通（真 embedding 质量 = UNVERIFIED）。
    """

    dim: int = 16

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._vector(text) for text in texts)

    def _vector(self, text: str) -> tuple[float, ...]:
        digits = [b / 255 for chunk in range(self.dim) for b in hashlib.sha256(f"{self.dim}:{chunk}:{text}".encode()).digest()[:1]]
        magnitude = sum(value * value for value in digits) ** 0.5 or 1.0
        return tuple(round(value / magnitude, 6) for value in digits)


__all__ = ["EchoProvider", "FakeEmbedder", "ScriptedProvider"]
