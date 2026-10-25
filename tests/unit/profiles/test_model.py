"""profiles.model 镜像测试：默认值与不可变性。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from questorharness.profiles.model import ProfileInfo


def test_defaults_are_empty() -> None:
    """未声明字段保持空值，不做隐式推断。"""
    profile = ProfileInfo(name="coding", path=Path("coding.yaml"))
    assert profile.description == ""
    assert profile.allowed_tools == ()
    assert profile.ui_capabilities == {}
    assert profile.is_default is False


def test_profile_is_frozen() -> None:
    """形态是只读数据：运行期不得被就地改写。"""
    profile = ProfileInfo(name="personal", path=Path("personal.yaml"))
    with pytest.raises(FrozenInstanceError):
        profile.name = "changed"  # type: ignore[misc]
