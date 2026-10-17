"""L6 组合根：把 MCP server 配置接成"可注册进某次 run 的远程工具"（Group 5 / C17 / DoD②⑤）。

只有组合根/surfaces 层可同时 import L3 `capabilities.mcp`（config/security/manager/params）与
L5 `providers`（`env_safety` 凭据擦除、`mcp_stderr` per-run stderr）——这是把两者粘起来而不破
分层（C1）的唯一合法位置；kernel/L3 都不 import providers。

生命周期：**per-run**（每次 run 起→用→teardown），与 `docs/plan/05` §16.4 的"spawn 侧注入
run_id 到独立 stderr 文件"一致（长驻连接无法做 per-run 文件）。`run_once` 结束经 `teardown`
关连接（SDK 回收子进程树）+ 关 stderr 句柄，不留悬空进程/文件句柄。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TextIO

from questor.capabilities.mcp.config import load_server_configs
from questor.capabilities.mcp.manager import McpManager
from questor.capabilities.mcp.params import make_stdio_params
from questor.capabilities.mcp.security import McpSecurityError, validate_server_entry
from questor.contracts.tool import Tool
from questor.providers.env_safety import is_provider_credential
from questor.providers.mcp_stderr import open_mcp_stderr_log

_log = logging.getLogger("questor.mcp")

Teardown = Callable[[], Awaitable[None]]


def _has_provider_credential_env(config) -> bool:
    """C17：server.env 里出现 provider 凭据名即拒绝起它（绝不把我们的模型凭据递给任意远程 server）。"""
    for name in config.env:
        if is_provider_credential(name):
            _log.warning("refusing MCP server '%s': env declares provider credential %r (C17)", config.name, name)
            return True
    return False


async def _noop_teardown() -> None:
    return None


async def discover_mcp_tools(*, mcp_json: Path, log_dir: Path, run_id: str) -> tuple[list[Tool], Teardown]:
    """载入→安全门→env 凭据门→连接→发现，返回 (远程工具, teardown)。无 server → ([], noop)。"""
    configs = load_server_configs(mcp_json)
    candidates = []
    for config in configs:
        try:
            validate_server_entry(config)  # 载入侧第一道门（spawn 侧在 manager 内再跑一次）
        except McpSecurityError as exc:
            _log.warning("skipping MCP server '%s' at load gate: %s", config.name, exc)
            continue
        if _has_provider_credential_env(config):
            continue
        candidates.append(config)
    if not candidates:
        return [], _noop_teardown

    handles: list[TextIO] = []

    def make_errlog(config) -> TextIO:
        # per-run + per-server 独立 stderr 文件（D-16.4-A/B）；文件名带 run_id 前缀可被关联定位。
        handle = open_mcp_stderr_log(Path(log_dir) / "mcp", f"{run_id}-{config.name}")
        handles.append(handle)
        return handle

    manager = McpManager(make_stdio_params=make_stdio_params, make_errlog=make_errlog)
    tools = await manager.discover(candidates)

    async def teardown() -> None:
        await manager.aclose()  # 关连接：SDK 负责终止子进程树
        for handle in handles:
            try:
                handle.close()
            except OSError:  # pragma: no cover - 关闭失败不该拖垮收尾
                pass

    return tools, teardown
