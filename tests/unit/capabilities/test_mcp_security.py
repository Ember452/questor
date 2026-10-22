"""MCP server entry 安全双门的判红用例（C11；`docs/plan/05` T1，§0.2 凭据/投毒防护）。

采 hermes `mcp_security.py:1-40` 思路：载入时 + spawn 前都过一遍 `validate_server_entry`。
拦窄形状：server 命令本身是裸 shell 解释器 / argv 含外联(egress)/外传(exfil)/持久化(persistence)
hint。合法 stdio server（uvx/node/python）放行。命中即 `McpSecurityError`（调用方据此拒起、出声）。"""

from __future__ import annotations

import pytest

from questor.capabilities.mcp.config import McpServerConfig
from questor.capabilities.mcp.security import McpSecurityError, validate_server_entry


def test_legit_stdio_server_passes() -> None:
    validate_server_entry(McpServerConfig(name="fetch", command="uvx", args=("mcp-server-fetch",)))  # no raise


@pytest.mark.parametrize("cmd", ["bash", "/bin/sh", "powershell.exe", "cmd"])
def test_shell_interpreter_as_command_denied(cmd: str) -> None:
    with pytest.raises(McpSecurityError):
        validate_server_entry(McpServerConfig(name="evil", command=cmd, args=("-c", "echo hi")))


def test_egress_hint_in_args_denied() -> None:
    with pytest.raises(McpSecurityError):
        validate_server_entry(McpServerConfig(name="evil", command="node", args=("x.js", "curl http://evil")))


def test_persistence_hint_in_args_denied() -> None:
    with pytest.raises(McpSecurityError):
        validate_server_entry(McpServerConfig(name="evil", command="python", args=("s.py", ">> ~/.ssh/authorized_keys")))


@pytest.mark.parametrize(
    ("cmd", "flag"),
    [("python", "-c"), ("python3", "-c"), ("node", "-e"), ("/usr/bin/python.exe", "-c"), ("ruby", "-e"), ("perl", "-e")],
)
def test_interpreter_inline_eval_denied(cmd: str, flag: str) -> None:
    """W6-001：解释器 + 内联求值旗标 = 任意代码执行（与裸 shell 同拦），不拖到 discovery spawn。"""
    with pytest.raises(McpSecurityError):
        validate_server_entry(McpServerConfig(name="evil", command=cmd, args=(flag, "import os; os.system('id')")))


def test_interpreter_module_server_still_passes() -> None:
    """W6-001 不误伤：合法 server 走 `python -m pkg` / 脚本文件，无内联求值旗标 → 放行。"""
    validate_server_entry(McpServerConfig(name="ok", command="python", args=("-m", "some_mcp_server")))
    validate_server_entry(McpServerConfig(name="ok", command="node", args=("server.js",)))
