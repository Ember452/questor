"""refusals 模块镜像测试：白名单与异常携带。"""

from __future__ import annotations

import pytest

from questorharness.bootstrap.hosts.serve import refusals


def test_whitelist_covers_every_constant() -> None:
    """常量与白名单必须一致（防新增码忘了登记）。"""
    for name in dir(refusals):
        value = getattr(refusals, name)
        if name.isupper() and isinstance(value, str):
            assert value in refusals.ALL or name == "ALL"


def test_unknown_code_is_rejected_at_construction() -> None:
    """未登记的码构造即失败，避免客户端拿到自由文本。"""
    with pytest.raises(ValueError):
        refusals.Refusal("not.a.code", "boom")


def test_status_defaults_to_conflict() -> None:
    """拒绝默认 409；协议层错误显式传 400。"""
    assert refusals.Refusal(refusals.TURN_BUSY, "x").status == 409
    assert refusals.Refusal(refusals.TURN_BUSY, "x", status=400).status == 400
