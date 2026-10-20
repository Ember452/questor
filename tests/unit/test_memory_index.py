"""B7/c1：档1 记忆索引的四道准入约束 + live-only 事件契约（v3 §6.1）。"""

from __future__ import annotations

from questor.contracts.events import Envelope, EventType
from questor.kernel.events import EXTERNAL_EVENT_FIELDS
from questor.memory.index import (
    LEAD_IN,
    MAX_INDEX_BYTES,
    MAX_INDEX_LINES,
    MemoryIndexBlock,
    admitted,
    build_index_block,
    entry_id,
    pointer_lines,
)
from questor.observability.projection import project as project_log
from questor.state.persist_form import LIVE_ONLY, durable_form

_CORE = """# MEMORY
- user prefers short answers
- launch code is DELTA-9
- pitfalls: never rm -rf without confirmation
"""


def test_pointer_lines_keep_order_drop_dupes_and_ignore_prose() -> None:
    text = _CORE + "\n- user prefers short answers\nsome prose line\n"
    lines = pointer_lines(text)
    assert lines == (
        "user prefers short answers",
        "launch code is DELTA-9",
        "pitfalls: never rm -rf without confirmation",
    )


def test_block_is_bounded_sanitized_and_delimited() -> None:
    block = build_index_block(_CORE)
    assert block is not None and admitted(block)
    assert block.lines <= MAX_INDEX_LINES and block.bytes <= MAX_INDEX_BYTES
    assert block.text.startswith(LEAD_IN)  # ③ 定界前导语
    assert block.entry_ids[0] == entry_id("MEMORY.md", 1, 1)
    assert all("- " in line for line in block.text.splitlines()[1:])


def test_line_budget_is_enforced_and_marked_truncated() -> None:
    many = "\n".join(f"- fact number {index}" for index in range(200))
    block = build_index_block(many, max_lines=5, max_bytes=MAX_INDEX_BYTES)
    assert block is not None
    assert block.lines == 5 and block.truncated is True


def test_byte_budget_drops_tail_lines_without_splitting_multibyte() -> None:
    cjk = "\n".join(f"- 中文记忆条目编号 {index}，用于验证字节预算不劈多字节字符" for index in range(50))
    block = build_index_block(cjk, max_lines=50, max_bytes=220)
    assert block is not None
    assert block.bytes <= 220
    assert block.truncated is True
    block.text.encode("utf-8").decode("utf-8")  # 不劈字符即不抛


def test_empty_index_produces_no_block() -> None:
    assert build_index_block("# MEMORY\nno bullets here\n") is None
    assert admitted(None) is False


def test_admitted_is_false_when_any_constraint_is_missing() -> None:
    unbounded = MemoryIndexBlock(text="no lead-in", entry_ids=(), lines=99, bytes=10, truncated=False)
    assert admitted(unbounded) is False


def test_event_data_is_auditable_but_carries_no_body() -> None:
    block = build_index_block(_CORE)
    assert block is not None
    data = block.event_data()
    assert data["kind"] == "index" and data["lines"] == 3
    assert set(data) == {"kind", "entry_ids", "lines", "bytes", "truncated"}
    assert "short answers" not in repr(data)  # 正文永不进观测条目（C18/C20）


def test_new_types_are_live_only_and_whitelisted_in_lockstep() -> None:
    assert EventType.MEMORY_INJECTED in LIVE_ONLY
    assert EventType.CACHE_BREAK in LIVE_ONLY
    assert durable_form(Envelope(v=1, seq=1, run_id="r", type=EventType.MEMORY_INJECTED, data={})) is None
    assert set(EXTERNAL_EVENT_FIELDS[EventType.MEMORY_INJECTED]) == {"kind", "entry_ids", "lines", "bytes", "truncated"}
    assert set(EXTERNAL_EVENT_FIELDS[EventType.CACHE_BREAK]) == {
        "system_hash",
        "tools_hash",
        "history_hash",
        "reason",
        "breakpoints",
    }


def test_memory_injected_projection_carries_no_payload_keys() -> None:
    # 带外投影只读自静态白名单 `_DATA_KEYS`（不含 kind/entry_ids/lines）：日志行只剩事件名与 seq，
    # 零明文（C20；与 tools_changed 同口径）。不入库则由 LIVE_ONLY 保证（上方已断）。
    env = Envelope(v=1, seq=3, run_id="r", type=EventType.MEMORY_INJECTED, data={"kind": "index", "lines": 3, "entry_ids": ["MEMORY.md:1-1"]})
    entry = project_log(env)
    assert entry is not None
    assert set(entry.fields) == {"seq"}
    assert "index" not in entry.msg and "MEMORY.md" not in entry.msg
