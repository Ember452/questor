"""McpManager 编排的判红用例（Group 5 / C23-T3；真子进程）。

Manager（L3）对每个 server：spawn 侧安全门 → connect → list_tools → 产 McpRemoteTool；
env 擦除与 per-run stderr 由调用方以工厂注入（capabilities 不得 import providers，C1）。
断连/坏 server 出声跳过、不拖垮其余（C6）；aclose 回收全部子进程（线程/进程泄漏守卫）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from questor.capabilities.mcp.config import McpServerConfig
from questor.capabilities.mcp.manager import McpManager

SERVER = Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py"


def _demo_config() -> McpServerConfig:
    return McpServerConfig(name="demo", command=sys.executable, args=(str(SERVER),))


def _factories():
    # L6 组合根会传真 env_safety / mcp_stderr；本测用最小工厂（errlog 走 stderr、env 直传）。
    def make_params(cfg: McpServerConfig) -> StdioServerParameters:
        return StdioServerParameters(command=cfg.command, args=list(cfg.args), env=dict(cfg.env))

    import sys as _s

    return make_params, (lambda cfg: _s.stderr)


@pytest.mark.asyncio
async def test_manager_discovers_remote_tools() -> None:
    make_params, make_errlog = _factories()
    mgr = McpManager(make_stdio_params=make_params, make_errlog=make_errlog)
    try:
        tools = await mgr.discover([_demo_config()])
        names = {t.spec.name for t in tools}
        assert {"mcp_demo_echo", "mcp_demo_boom"} <= names
        assert all(t.spec.capability.value == "network" for t in tools)  # C22 远程=NETWORK
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_unreachable_server_is_skipped_voiced_good_still_found(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    make_params, make_errlog = _factories()
    mgr = McpManager(make_stdio_params=make_params, make_errlog=make_errlog)
    bad = McpServerConfig(name="down", command="__no_such_bin__")
    try:
        with caplog.at_level("WARNING", logger="questor.mcp"):
            tools = await mgr.discover([bad, _demo_config()])
        names = {t.spec.name for t in tools}
        assert "mcp_demo_echo" in names  # 坏 server 不拖垮其余（C6）
        assert not any(t.spec.name.startswith("mcp_down_") for t in tools)
        warns = [r.getMessage() for r in caplog.records if r.name == "questor.mcp"]
        assert any("down" in m for m in warns)
    finally:
        await mgr.aclose()
