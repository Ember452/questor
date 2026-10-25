"""kind 覆盖守卫：schema 的帧集合必须等于"引擎映射 ∪ 宿主直出"。

差额即意味着某一类帧没有任何生产者（死契约），或引擎产出了契约里没有的帧
（前端会拿到无法解释的数据）。
"""

from __future__ import annotations

from questorharness.bootstrap.hosts.serve import wire
from questorharness.bootstrap.hosts.serve.wire_types import SERVER_FRAME_KINDS

# 由宿主而非 StreamEvent 映射直接产出的帧；每条都必须写明来源。
HOST_PRODUCED: dict[str, str] = {
    "turn_started": "host._run_turn 在回合开始时发布",
    "turn_done": "host._run_turn 在回合结束时发布",
    "approval_request": "authority 打开审批时经 notifier 发布",
    "ask_request": "authority 打开提问时经 notifier 发布",
    "stream_reset": "eventstream/route 在重放窗口越界时发布",
}


def _mapped_kinds() -> set[str]:
    """引擎事件映射出的帧集合。"""
    return {kind for kinds in wire.STREAM_EVENT_TO_KINDS.values() for kind in kinds}


def test_schema_kinds_equal_producers() -> None:
    """schema 里的每个帧都必须有生产者，反之亦然。"""
    assert set(SERVER_FRAME_KINDS) == _mapped_kinds() | set(HOST_PRODUCED)


def test_host_produced_entries_exist_in_schema() -> None:
    """白名单不得包含 schema 里不存在的帧（防陈旧登记）。"""
    assert set(HOST_PRODUCED) <= set(SERVER_FRAME_KINDS)


def test_every_stream_event_type_is_mapped() -> None:
    """7 个 StreamEvent 类型必须全部有映射。"""
    assert len(wire.STREAM_EVENT_TO_KINDS) == 7
    assert all(kinds for kinds in wire.STREAM_EVENT_TO_KINDS.values())


def test_selftest_removing_a_mapping_turns_guard_red() -> None:
    """自证：删掉一条映射后本守卫必然不成立。"""
    original = dict(wire.STREAM_EVENT_TO_KINDS)
    try:
        victim = next(iter(original))
        wire.STREAM_EVENT_TO_KINDS.pop(victim)
        assert set(SERVER_FRAME_KINDS) != _mapped_kinds() | set(HOST_PRODUCED)
    finally:
        wire.STREAM_EVENT_TO_KINDS.clear()
        wire.STREAM_EVENT_TO_KINDS.update(original)


def _card_slot_kinds(text: str) -> set[str]:
    """从 `CARD_SLOTS` 对象字面量里取出帧 kind 键名。"""
    import re

    match = re.search(r"CARD_SLOTS[^{]*\{(?P<body>.*?)\n\};", text, re.S)
    assert match, "CARD_SLOTS not found in cardSlots.ts"
    return set(re.findall(r"^\s{2}([a-z_]+):", match.group("body"), re.M))


def test_card_slots_cover_every_schema_kind() -> None:
    """前端卡槽集合必须等于 schema 帧集合（新增 kind 不补槽位 = 红）。"""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    text = (repo / "apps/web/src/app/cardSlots.ts").read_text(encoding="utf-8")
    assert _card_slot_kinds(text) == set(SERVER_FRAME_KINDS)


def test_card_slot_parser_self_test() -> None:
    """自证：少写一个 kind，解析结果就必须不等。"""
    sample = "export const CARD_SLOTS: Record<X, Slot> = {\n  text: { item: 'say' },\n};\n"
    assert _card_slot_kinds(sample) == {"text"}
    assert _card_slot_kinds(sample) != set(SERVER_FRAME_KINDS)
