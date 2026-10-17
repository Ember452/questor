"""远程 MCP 工具 → ToolSpec 映射与执行语义的判红用例（C19/C22；`docs/plan/05` T3/T11）。

要点（对齐本仓既有件 + DeepCode 思路）：
- 命名 `mcp_<server>_<tool>`；描述走共享 `bound_description` 有界净化；schema 走 `normalize_mcp_schema`。
- C22 非放宽：capability=NETWORK、read_only 默认 False（远程 annotations 是 hint 非 grant）、approval_mode 不设→走 unknown→deny。
- C19 闭合：远程返回 isError → status="error"（真实记录）；transport 异常**向上抛**，交 `_execute_tool` 归一闭合配对。
说明：本单测用 stub connection 验证**映射逻辑**（我方边界的双，非"假对象冒充真进程"）；真子进程 roundtrip /
断连由 `test_mcp_connection_roundtrip.py`、C19 组集成测试覆盖。"""

from __future__ import annotations

import pytest

from questor.capabilities.mcp.remote_tool import McpRemoteTool
from questor.contracts.tool import Capability


class _Block:
    def __init__(self, text):
        self.text = text


class _Result:
    def __init__(self, text, is_error=False):
        self.content = [_Block(text)]
        self.isError = is_error


class _StubConn:
    def __init__(self, *, result=None, exc=None, connected=True):
        self._result = result
        self._exc = exc
        self.connected = connected

    async def call_tool(self, name, arguments):
        if self._exc is not None:
            raise self._exc
        return self._result


def test_spec_mapped_named_bounded_nonwidening() -> None:
    tool = McpRemoteTool(
        connection=_StubConn(),
        server_name="fetch",
        raw_name="get_page",
        description="Fetch a " + "x" * 5000,
        input_schema={"type": "object", "properties": {"url": {"type": ["string", "null"]}}},
    )
    assert tool.spec.name == "mcp_fetch_get_page"
    assert tool.spec.capability is Capability.NETWORK
    assert tool.spec.read_only is False  # C22 fail-closed
    assert len(tool.spec.description) <= 2000  # C19 有界
    assert tool.spec.params["properties"]["url"]["type"] == "string"  # C18 归一


def test_execute_success_maps_result() -> None:
    tool = McpRemoteTool(connection=_StubConn(result=_Result("hi")), server_name="s", raw_name="t", description="d", input_schema=None)
    result = _run(tool.execute({}, _NoopCtx()))
    assert result.status == "success"
    assert result.result == "hi"


def test_execute_is_error_becomes_error_status() -> None:
    tool = McpRemoteTool(connection=_StubConn(result=_Result("boom", is_error=True)), server_name="s", raw_name="t", description="d", input_schema=None)
    result = _run(tool.execute({}, _NoopCtx()))
    assert result.status == "error"


def test_execute_transport_exception_propagates_for_pairing_close() -> None:
    """C19：断连异常必须上抛，交由 Harness `_execute_tool` 回填 error tool_result 闭合配对，绝不吞成成功。"""
    tool = McpRemoteTool(connection=_StubConn(exc=ConnectionError("server gone")), server_name="s", raw_name="t", description="d", input_schema=None)
    with pytest.raises(ConnectionError):
        _run(tool.execute({}, _NoopCtx()))


# ---- 测试辅助 ---- #
class _NoopCtx:
    pass


def _run(coro):
    import asyncio

    return asyncio.run(coro)
