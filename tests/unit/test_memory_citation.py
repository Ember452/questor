"""B8/c1：MemoryCitation / EmbeddingPort / flags 的契约形状（additive，不碰行为）。

引用面是 §6.3 的归因依据，形状判据必须先立住：

- **条目级**（`path:start-end`）才算引用，文件级不算；
- 非法/越界的条目**丢弃不猜**（宁可不计数，也不给一个假归因）；
- 上限 10 条与 wire `maxItems` 同源（超上限只留前 10 条，不报错也不静默全收）；
- `SubmitMessage.flags` 深冻结且默认为 None 时与旧行为逐字等价；
- `EmbeddingPort` 只产向量——它没有任何写入方法（§20 C-3 单库约束的形状面）。
"""

from __future__ import annotations

import dataclasses

import pytest

from questor.contracts.common import thaw
from questor.contracts.events import AppendAssistantMessage, SubmitMessage
from questor.contracts.memory import (
    CitationEntry,
    EmbeddingPort,
    MemoryCitation,
    citation_from_payload,
)
from questor.contracts.state_schema import ContentBlock, Message, Role


def _user(run_id: str, text: str = "hi") -> Message:
    return Message(id=f"msg-{run_id}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


def test_citation_entry_id_is_entry_granular() -> None:
    entry = CitationEntry(path="memory/2026-10-01.md", line_start=3, line_end=7, note="why")
    assert entry.entry_id == "memory/2026-10-01.md:3-7"
    with pytest.raises(ValueError, match="line_start <= line_end"):
        CitationEntry(path="MEMORY.md", line_start=5, line_end=4)
    with pytest.raises(ValueError, match="must not be empty"):
        CitationEntry(path="", line_start=0, line_end=1)


def test_citation_payload_round_trips_and_drops_junk_without_guessing() -> None:
    citation = MemoryCitation(
        entries=(CitationEntry(path="MEMORY.md", line_start=1, line_end=2),),
        rollout_ids=("roll-1",),
    )
    payload = thaw(citation.to_payload())
    assert payload["rollout_ids"] == ["roll-1"]
    restored = citation_from_payload(payload)
    assert restored == citation
    mixed = {
        "entries": [
            {"path": "MEMORY.md", "line_start": 1, "line_end": 2},
            {"path": "MEMORY.md", "line_start": 9, "line_end": 3},  # 反向区间 → 丢弃
            "not-a-dict",  # 形状错 → 丢弃
            {"line_start": 1, "line_end": 2},  # 缺 path → 丢弃
        ]
    }
    cleaned = citation_from_payload(mixed)
    assert cleaned is not None and len(cleaned.entries) == 1
    assert citation_from_payload({"entries": []}) is None
    assert citation_from_payload(None) is None
    assert citation_from_payload({"entries": "no"}) is None


def test_citation_is_capped_like_the_wire() -> None:
    many = {"entries": [{"path": f"p{i}.md", "line_start": 0, "line_end": 1} for i in range(30)]}
    capped = citation_from_payload(many)
    assert capped is not None and len(capped.entries) == 10  # 与 schema maxItems=10 同源


def test_new_command_fields_are_additive_and_frozen() -> None:
    # 旧调用点零改动：不传新字段 == 与历史逐字等价的命令。
    plain = AppendAssistantMessage(run_id="r", turn=1, message=_user("r"))
    assert plain.citations is None
    submitted = SubmitMessage(run_id="r", content=_user("r"), flags={"skip_recall": True})
    assert submitted.flags["skip_recall"] is True
    with pytest.raises(TypeError):
        submitted.flags["skip_recall"] = False  # type: ignore[index]
    assert SubmitMessage(run_id="r", content=_user("r")).flags is None
    assert {field.name for field in dataclasses.fields(SubmitMessage)} == {"run_id", "content", "flags"}


def test_embedding_port_shape_produces_vectors_and_writes_nothing() -> None:
    class _Fake:
        async def embed(self, texts):  # noqa: ANN001, ANN201
            return tuple((float(len(text)),) for text in texts)

    assert isinstance(_Fake(), EmbeddingPort)
    # 单库约束的形状面：端口只有 embed，没有任何 write/upsert/sync。
    names = {name for name in dir(EmbeddingPort) if not name.startswith("_")}
    assert names == {"embed"}
    assert not {name for name in names if name.startswith(("write", "upsert", "sync", "delete"))}
