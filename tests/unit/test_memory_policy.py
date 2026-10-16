"""记忆感知策略示例测（T15；DoD④ L4 接缝）。纯策略、无 kernel。"""

from __future__ import annotations

from questor.contracts.memory import MemoryScope, MemorySearchResult, MemorySource
from questor.contracts.policy import PolicyView, SuggestFinish
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.policy.memory_policy import MemoryAwareReActPolicy
from questor.policy.react_policy import ReActPolicy


def _view(with_memory: bool) -> PolicyView:
    assistant = Message(id="m1", role=Role.ASSISTANT, content=(ContentBlock(type="text", text="the answer"),), seq=1)
    mem: tuple[MemorySearchResult, ...] = ()
    if with_memory:
        mem = (MemorySearchResult(path="MEMORY.md", start_line=1, end_line=2, score=1.0, snippet="user likes orchids", source=MemorySource.CORE, scope=MemoryScope.USER),)
    return PolicyView(context=(assistant,), memory=mem)


def test_swappable_distinct_identity() -> None:
    # DoD④：替换策略有独立 id/fingerprint，可注册/AB，不改内核。
    assert MemoryAwareReActPolicy.id != ReActPolicy.id
    assert MemoryAwareReActPolicy.fingerprint != ReActPolicy.fingerprint


def test_memory_surfaces_in_finish() -> None:
    intent = MemoryAwareReActPolicy().propose_action(_view(True))
    assert isinstance(intent, SuggestFinish)
    assert "[recalled memory]" in intent.final_text
    assert "user likes orchids" in intent.final_text
    assert "the answer" in intent.final_text


def test_no_memory_behaves_like_plain_react() -> None:
    intent = MemoryAwareReActPolicy().propose_action(_view(False))
    assert isinstance(intent, SuggestFinish)
    assert intent.final_text == "the answer"


def test_recall_is_bounded() -> None:
    assistant = Message(id="m1", role=Role.ASSISTANT, content=(ContentBlock(type="text", text="a"),), seq=1)
    big = "x" * 5000
    mem = (MemorySearchResult(path="MEMORY.md", start_line=1, end_line=2, score=1.0, snippet=big, source=MemorySource.CORE),)
    intent = MemoryAwareReActPolicy().propose_action(PolicyView(context=(assistant,), memory=mem))
    assert "x" * 2000 in intent.final_text and "x" * 2001 not in intent.final_text  # 召回摘要夹到 2000 字符
