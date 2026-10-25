"""profile 工具面在权限层的效果：personal 形态下编码工具被拒。"""

from __future__ import annotations

from pathlib import Path

from questorharness.capabilities.policy.checker import PermissionChecker
from questorharness.config.settings_models import PermissionSettings
from questorharness.profiles import load_profile

BUNDLES = Path(__file__).resolve().parents[3] / "src" / "questor" / "profiles"


def test_personal_denies_bash_and_coding_does_not() -> None:
    """同一策略层：personal 拒绝 bash，coding 沿既有规则（不额外拒绝）。"""
    personal = load_profile(BUNDLES, "personal")
    coding = load_profile(BUNDLES, "coding")
    personal_checker = PermissionChecker(
        PermissionSettings(
            allowed_tools=list(personal.allowed_tools),
            denied_tools=list(personal.denied_tools),
        )
    )
    coding_checker = PermissionChecker(
        PermissionSettings(
            allowed_tools=list(coding.allowed_tools),
            denied_tools=list(coding.denied_tools),
        )
    )
    personal_decision = personal_checker.evaluate("bash", is_read_only=False, command="ls")
    coding_decision = coding_checker.evaluate("bash", is_read_only=False, command="ls")
    # personal：硬拒绝；coding：仍走“变更类工具需确认”的既有策略，不是被 profile 拒绝。
    assert personal_decision.allowed is False
    assert "explicitly denied" in personal_decision.reason
    assert coding_decision.allowed is False
    assert coding_decision.requires_confirmation is True
    assert "explicitly denied" not in coding_decision.reason


def test_personal_denies_write_tools_and_coding_allows_them() -> None:
    """阶段 1 关门判红：personal 下 write_file/edit_file 被硬拒，coding 不额外拒。"""
    personal = load_profile(BUNDLES, "personal")
    coding = load_profile(BUNDLES, "coding")
    personal_checker = PermissionChecker(
        PermissionSettings(
            allowed_tools=list(personal.allowed_tools),
            denied_tools=list(personal.denied_tools),
        )
    )
    coding_checker = PermissionChecker(
        PermissionSettings(
            allowed_tools=list(coding.allowed_tools),
            denied_tools=list(coding.denied_tools),
        )
    )
    for tool in ("write_file", "edit_file", "notebook_edit"):
        denied = personal_checker.evaluate(tool, is_read_only=False)
        assert denied.allowed is False
        assert "explicitly denied" in denied.reason
        allowed = coding_checker.evaluate(tool, is_read_only=False)
        assert "explicitly denied" not in allowed.reason


def test_personal_allows_question_tool_without_prompt() -> None:
    """personal 显式放行提问工具（无副作用的交互）。"""
    personal = load_profile(BUNDLES, "personal")
    checker = PermissionChecker(
        PermissionSettings(
            allowed_tools=list(personal.allowed_tools),
            denied_tools=list(personal.denied_tools),
        )
    )
    decision = checker.evaluate("ask_user_question", is_read_only=False)
    assert decision.allowed is True
    assert "explicitly allowed" in decision.reason
