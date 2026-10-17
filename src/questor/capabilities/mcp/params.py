"""L3 构造 SDK `StdioServerParameters`（把 mcp SDK 类型收口在 capabilities/mcp，ADR-0030）。

L6 组合根经 `McpManager` 的 `make_stdio_params` 工厂调用本函数，从而**不必自己 import SDK**；
env 直接取 config.env（用户为该 server 显式声明的值，已在上游被 provider 凭据门过滤）。
"""

from __future__ import annotations

from mcp import StdioServerParameters

from questor.capabilities.mcp.config import McpServerConfig


def make_stdio_params(config: McpServerConfig) -> StdioServerParameters:
    """把 `McpServerConfig` 映射成 SDK 的 stdio 启动参数（env 为空则交 SDK 用其安全白名单）。"""
    return StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=dict(config.env) if config.env else None,
    )
