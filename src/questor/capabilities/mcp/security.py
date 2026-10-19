"""L3 MCP server entry 安全门（C11；`docs/plan/05` T1，§0.2 凭据/投毒防护）。

**载入时 + spawn 前**都调 `validate_server_entry`，
使手改/预植的 `mcp.json` 条目在执行前也被拦。只拦窄形状（宁可漏报不误伤合法 server）：
- server 命令本身是裸 shell 解释器（bash/sh/cmd/powershell…）；
- argv 文本含外联(egress)/外传(exfil)/OS 持久化(persistence) hint。
命中抛 `McpSecurityError`，调用方据此拒起该 server 并出声（C6）——**绝不静默放行**。
只依赖 stdlib（HARD C1/C14）。"""

from __future__ import annotations

import re

from questor.capabilities.mcp.config import McpServerConfig

_SHELL_INTERPRETERS = frozenset(
    {"bash", "sh", "zsh", "dash", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
)

# 外联工具 / reverse shell 目标。lookaround 避免命中 "network" 这类子串。
_EGRESS_RE = re.compile(
    r"(?<![\w.-])(?:curl|wget|nc|ncat|socat)(?![\w.-])|/dev/tcp/|\bInvoke-WebRequest\b|\bInvoke-RestMethod\b|\bSystem\.Net\.WebClient\b",
    re.IGNORECASE,
)
# 外传 hint（读 .env、raw POST body、redirect-from 文件）。
_EXFIL_RE = re.compile(r"\.env\b|--data-binary|--data-raw|\bPOST\b|<\s*[^\s]+", re.IGNORECASE)
# OS 持久化面（SSH key / PAM / sudoers / cron）——合法 MCP server 无理由写这些。
_PERSISTENCE_RE = re.compile(
    r"authorized_keys|\.ssh/|/etc/ssh|/etc/pam|/etc/sudoers|crontab|/etc/cron",
    re.IGNORECASE,
)


class McpSecurityError(ValueError):
    """server entry 命中安全门（窄形状），拒绝在启动它之前放行。"""


def _command_basename(command: str) -> str:
    return command.replace("\\", "/").rsplit("/", 1)[-1].lower()


def validate_server_entry(config: McpServerConfig) -> None:
    """校验单个 server entry；命中任一危险形状抛 `McpSecurityError`。合法则静默返回（正常放行）。"""
    if _command_basename(config.command) in _SHELL_INTERPRETERS:
        raise McpSecurityError(f"MCP server '{config.name}': command is a raw shell interpreter ({config.command!r})")
    joined = " ".join((config.command, *config.args))
    for label, pattern in (("egress", _EGRESS_RE), ("exfil", _EXFIL_RE), ("persistence", _PERSISTENCE_RE)):
        if pattern.search(joined):
            raise McpSecurityError(f"MCP server '{config.name}': {label} pattern in command line")
