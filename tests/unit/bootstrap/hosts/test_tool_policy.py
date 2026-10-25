"""`--allowed-tools/--disallowed-tools` 的解析语义。"""

from __future__ import annotations

import pytest

from questorharness.bootstrap.hosts.tool_policy import ToolPolicyError, resolve_tool_policy

KNOWN = frozenset({"read_file", "grep", "write_file", "edit_file", "bash"})


def test_no_flags_means_inherit() -> None:
    """都没给 → (None, None)，不得把“继承”降级成“全禁”。"""
    assert resolve_tool_policy(None, None, known_names=KNOWN) == (None, None)


def test_disallowed_only_passes_through() -> None:
    """只给黑名单 → allowed=None，denied 原样。"""
    assert resolve_tool_policy(None, ["write_file"], known_names=KNOWN) == (
        None,
        ["write_file"],
    )


def test_allowed_is_a_strict_allowlist() -> None:
    """白名单 = 只允许列出的工具，其余全部进 denied。"""
    allowed, denied = resolve_tool_policy(["read_file", "grep"], None, known_names=KNOWN)
    assert allowed == ["grep", "read_file"]
    assert denied == ["bash", "edit_file", "write_file"]


def test_allowed_and_denied_union() -> None:
    """显式黑名单与补集合并去重。"""
    allowed, denied = resolve_tool_policy(["read_file"], ["write_file"], known_names=KNOWN)
    assert allowed == ["read_file"]
    assert denied == ["bash", "edit_file", "grep", "write_file"]


def test_comma_and_space_tokens_are_split() -> None:
    """Typer 把 `a,b` 当一个 token 传进来时也要拆开。"""
    allowed, _ = resolve_tool_policy(["read_file,grep"], None, known_names=KNOWN)
    assert allowed == ["grep", "read_file"]


def test_wildcard_means_everything() -> None:
    """`*` 等价于不限制；显式黑名单仍生效。"""
    assert resolve_tool_policy(["*"], ["bash"], known_names=KNOWN) == (None, ["bash"])


def test_unknown_tool_name_is_rejected() -> None:
    """拼错名字必须报错，不能静默忽略。"""
    with pytest.raises(ToolPolicyError) as excinfo:
        resolve_tool_policy(["read_fiel"], None, known_names=KNOWN)
    assert "read_fiel" in str(excinfo.value)


def test_allow_deny_overlap_is_rejected() -> None:
    """同一工具既放又禁 → 配置矛盾，直接报错。"""
    with pytest.raises(ToolPolicyError):
        resolve_tool_policy(["read_file"], ["read_file"], known_names=KNOWN)
