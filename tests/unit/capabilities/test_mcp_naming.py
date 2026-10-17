"""远程工具命名 `mcp_<server>_<tool>` 的判红用例（C20；`docs/plan/05` T3，stub 钉死约定）。

沿用 `capabilities/mcp/README.md` 的 `mcp_<server>_<tool>` + suffix 匹配（**非** DeepCode 双下划线）。
每段清洗成 provider 安全字符集 [A-Za-z0-9_-]；空段退化 "unnamed"。名字里含服务器段，天然不与
内置裸名相同（防伪装），真冲突由注册表 C21 兜。"""

from __future__ import annotations

from questor.capabilities.mcp.naming import remote_tool_name


def test_basic_name_uses_single_underscore_prefix() -> None:
    assert remote_tool_name("fetch", "get_page") == "mcp_fetch_get_page"


def test_invalid_chars_sanitized_per_segment() -> None:
    assert remote_tool_name("my server", "get.page!") == "mcp_my_server_get_page"


def test_empty_segment_falls_back_to_unnamed() -> None:
    assert remote_tool_name("", "tool") == "mcp_unnamed_tool"


def test_name_starts_with_server_prefix_for_suffix_match() -> None:
    # 权限规则按 suffix 匹配：`mcp_fetch_*` 命中。名字须以该前缀开头。
    assert remote_tool_name("fetch", "anything").startswith("mcp_fetch_")
