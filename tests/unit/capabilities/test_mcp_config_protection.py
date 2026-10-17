"""MCP 配置面写保护的机器耦合守卫（C10；`docs/plan/05` T1，C8/C17）。

价值：`config.MCP_CONFIG_FILENAME` 必须落在 `contracts/tool_args.PROTECTED_IN_ROOTS` 里，
否则"agent 不得自改 mcp.json 扩大能力面"这条保护对配置文件本身失效。任一侧改名都会让本测试判红。
（mode 不能放宽 protected 文件的执行期判据已由 `tests/unit/test_permission_policy.py:212-220` 覆盖，
本测试只补"配置文件名 ↔ 保护 token"的静态耦合，避免重复实现权限断言。）"""

from __future__ import annotations

from questor.capabilities.mcp.config import MCP_CONFIG_FILENAME
from questor.contracts.tool_args import PROTECTED_IN_ROOTS


def test_mcp_config_filename_is_write_protected_token() -> None:
    assert MCP_CONFIG_FILENAME == "mcp.json"  # 钉死：改了名就必须同步改 PROTECTED_IN_ROOTS
    assert MCP_CONFIG_FILENAME in PROTECTED_IN_ROOTS


def test_control_files_all_present_in_protection_set() -> None:
    # 能控制 agent 能力的文件都在保护集里（防未来有人误删 mcp.json 条目）。
    assert {"mcp.json", "permissions.json", "config.json", ".env"} <= PROTECTED_IN_ROOTS
