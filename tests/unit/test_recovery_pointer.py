"""RecoveryPointer typed 形状与 covered_hash 锚的 fail-closed 语义（ADR-0024）。

生产者（压缩时写指针）后置 P10；本测只钉"形状 + 读校验"这条正确性前置，证明锚缺失/区间非法
在构造期即拒，读取前可比对语义哈希、历史改写则判不一致（绝不返回旧内容）。"""

from __future__ import annotations

import pytest

from questor.contracts.memory import RecoveryPointer


def test_recovery_pointer_matches_only_on_equal_anchor() -> None:
    pointer = RecoveryPointer(seq_from=1, seq_to=3, covered_hash="abc123")
    assert pointer.matches("abc123") is True
    # 覆盖区原文被改写 → 重算哈希不同 → False（调用方据此 fail-closed，不返旧内容）。
    assert pointer.matches("abc124") is False


def test_recovery_pointer_rejects_empty_anchor() -> None:
    with pytest.raises(ValueError, match="covered_hash"):
        RecoveryPointer(seq_from=1, seq_to=3, covered_hash="")


def test_recovery_pointer_rejects_inverted_or_negative_range() -> None:
    with pytest.raises(ValueError, match="seq_from"):
        RecoveryPointer(seq_from=3, seq_to=1, covered_hash="abc")
    with pytest.raises(ValueError, match="seq_from"):
        RecoveryPointer(seq_from=-1, seq_to=3, covered_hash="abc")
