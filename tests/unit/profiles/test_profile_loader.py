"""profile bundle 读取测试：产品侧两份 bundle 的工具面必须可区分。"""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.profiles import ProfileError, list_profiles, load_profile

BUNDLES = Path(__file__).resolve().parents[3] / "src" / "questor" / "profiles"


def test_product_bundles_load() -> None:
    """两份产品 bundle 可读，默认形态是 coding。"""
    profiles = {profile.name: profile for profile in list_profiles(BUNDLES)}
    assert set(profiles) == {"coding", "personal"}
    assert profiles["coding"].is_default is True


def test_tool_surface_differs_between_forms() -> None:
    """工具面可枚举且互不相同：personal 不放行编码工具并显式拒绝。"""
    coding = load_profile(BUNDLES, "coding")
    personal = load_profile(BUNDLES, "personal")
    assert coding.allowed_tools == ()
    assert coding.denied_tools == ()
    assert personal.allowed_tools == ("ask_user_question",)
    assert "bash" in personal.denied_tools
    assert personal.allowed_tools != coding.allowed_tools
    assert personal.denied_tools != coding.denied_tools
    assert not set(personal.denied_tools) & set(personal.allowed_tools)


def test_personal_capabilities_are_declared_not_ready() -> None:
    """首批五页只登记 declared，入口不出现。"""
    personal = load_profile(BUNDLES, "personal")
    assert set(personal.ui_capabilities) == {"chat", "persona", "memory", "schedule", "channels"}
    assert set(personal.ui_capabilities.values()) == {"declared"}


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    """未知键 fail-closed，避免写错却静默生效。"""
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\nunexpected: 1\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(tmp_path, "bad")


def test_invalid_capability_state_is_rejected(tmp_path: Path) -> None:
    """能力位只能是 ready / declared / absent。"""
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\nui:\n  capabilities:\n    chat: maybe\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(tmp_path, "bad")


def test_missing_profile_does_not_fallback(tmp_path: Path) -> None:
    """缺失形态必须报错，不得偷偷回退到默认。"""
    with pytest.raises(ProfileError):
        load_profile(tmp_path, "nope")
