"""`unsupported.py` 的行为：徽标文本、展开原因、未登记 id 的拒绝。"""

from __future__ import annotations

import pytest

from questorharness.bootstrap.hosts.terminal import strings, unsupported


def test_registry_values_are_name_and_reason_pairs() -> None:
    """每个缺口都必须是 (名词, 原因) 两段非空文本，否则徽标会渲染成空壳。"""
    assert unsupported.UNSUPPORTED
    for gap_id, value in unsupported.UNSUPPORTED.items():
        name, reason = value
        assert isinstance(name, str) and name.strip(), gap_id
        assert isinstance(reason, str) and reason.strip(), gap_id


def test_badge_text_names_the_gap_and_its_id() -> None:
    """徽标文本形如 `⊘ 未实现 · A1 审批第三档`，用户看得见缺什么。"""
    text = unsupported.badge_text("A1")
    assert text == f"{strings.BADGE_MARK} 未实现 · A1 审批第三档"


def test_badge_reason_names_the_missing_contract() -> None:
    """展开说明要指出缺的是哪条后端契约，而不是“暂不支持”。"""
    reason = unsupported.badge_reason("A1")
    assert "PermissionPrompt" in reason


def test_badge_rejects_unknown_id() -> None:
    """未登记的 id 立即 KeyError，避免渲染出没有来源的“未实现”。"""
    with pytest.raises(KeyError):
        unsupported.badge_text("A99")
    with pytest.raises(KeyError):
        unsupported.badge_reason("A99")


def test_every_registered_gap_renders_a_badge() -> None:
    """登记了却渲染不出来，等于没登记。"""
    for gap_id in unsupported.UNSUPPORTED:
        assert unsupported.badge_text(gap_id).startswith(
            f"{strings.BADGE_MARK} 未实现 · {gap_id} "
        )
