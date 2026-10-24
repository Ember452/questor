"""wire_types 生成物镜像测试：常量与映射表可用且稳定。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.serve import wire_types


def test_generated_kinds_match_schema_union() -> None:
    """13 帧常量齐全且不可变。"""
    assert isinstance(wire_types.SERVER_FRAME_KINDS, frozenset)
    assert len(wire_types.SERVER_FRAME_KINDS) == 13
    assert wire_types.KIND_TEXT == "text"
    assert wire_types.KIND_TURN_DONE == "turn_done"


def test_generated_kind_by_def_is_consistent() -> None:
    """def → kind 映射的值域与常量集合一致。"""
    assert set(wire_types.SERVER_FRAME_KIND_BY_DEF.values()) <= set(wire_types.SERVER_FRAME_KINDS)
