"""共享描述净化器的判红用例（C08；`docs/plan/05` T9）。

单一真源：把 `registry._sanitize_description` 里的字符串规则抽出成 `bound_description`，供
ToolRegistry（内置+未来 MCP 远程工具）与 skills 目录共用。行为须与原实现一致（回归不破）。
规则：去控制字符 → 折叠空白 → 过短退化（含工具名、绝不空）→ 超界截断加省略号。"""

from __future__ import annotations

from questor.capabilities.tools.registry import bound_description


def test_strips_control_chars_and_collapses_whitespace() -> None:
    # 输入足够长以避开"过短退化"下限；\x00 紧靠空白→删除后不粘连，单独验证去控制字符 + 折叠空白。
    assert bound_description("hello\x00 world\t\tdone here", name="t", max_chars=2000) == "hello world done here"


def test_truncates_over_long_with_ellipsis() -> None:
    out = bound_description("x" * 50, name="t", max_chars=20)
    assert len(out) == 20
    assert out.endswith("…")


def test_degenerate_short_falls_back_to_named_description() -> None:
    # 太短（<20）退化为含工具名、达下限的说明，绝不给 provider 空/过短 description。
    out = bound_description("hi", name="web_search", max_chars=2000)
    assert "web_search" in out
    assert len(out) >= 20


def test_empty_description_still_yields_nonempty_named_fallback() -> None:
    out = bound_description("", name="t", max_chars=2000)
    assert out.strip() != ""
    assert "t" in out
