"""真实 runtime + 假 provider 的 serve 全链测试。

与 `test_serve_host_smoke.py` 的区别：那里替换的是 `handle_line`，这里只替换
模型客户端（ScriptedClient），`build_runtime`、引擎回合循环、快照写入、
路由与 SSE 字节全部是真的。
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from questorharness.bootstrap.hosts.serve import ServeHost
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.terminal_client import run_terminal_client
from questorharness.bootstrap.runtime import build_runtime
from questorharness.contracts.domain.message import ConversationMessage, TextBlock
from questorharness.contracts.usage import UsageSnapshot
from questorharness.providers.llm.client import ApiMessageCompleteEvent

PROFILE_YAML = "name: coding\ndescription: engine e2e\nui:\n  capabilities:\n    chat: ready\n"


class ScriptedClient:
    """按脚本回一条助手消息的流式客户端。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    async def stream_message(self, request: Any) -> Any:
        """忽略请求内容，回放固定事件。"""
        del request
        self.calls += 1
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(
                role="assistant", content=[TextBlock(text=self._text)]
            ),
            usage=UsageSnapshot(input_tokens=7, output_tokens=5),
            stop_reason=None,
        )


def test_real_engine_turn_over_memory_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """真 runtime：提交 → 引擎跑一轮 → message/turn_done → 快照落盘可读。"""
    (tmp_path / "coding.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setenv("QUESTORHARNESS_CONFIG_DIR", str(tmp_path / "cfg"))

    async def scenario() -> None:
        client = ScriptedClient("pong")
        runtime = await build_runtime(
            cwd=str(tmp_path),
            model="fake-model",
            system_prompt="you are a test double",
            api_client=client,
            enforce_max_turns=False,
        )
        host = ServeHost(runtime, authority=Authority(), profile_root=tmp_path)
        await host.start()
        try:
            response = await host.transport.request(
                "POST",
                "/rt/r1/submit",
                body=json.dumps({"line": "ping", "clientRequestId": "engine-1"}).encode(),
            )
            assert response.status == 202
            await asyncio.wait_for(
                asyncio.gather(*host._tasks.values()), timeout=30  # noqa: SLF001
            )
            assert client.calls == 1
            frames = [frame for _, frame in host.broadcaster.replay(0).frames]
            kinds = [frame["kind"] for frame in frames]
            assert kinds[0] == "turn_started"
            assert "message" in kinds
            assert kinds[-1] == "turn_done"
            message_frame = next(frame for frame in frames if frame["kind"] == "message")
            assert message_frame["blocks"] == [{"type": "text", "text": "pong"}]
            assert message_frame["usage"] == {"inputTokens": 7, "outputTokens": 5}
            done = next(frame for frame in frames if frame["kind"] == "turn_done")
            assert done["outcome"] == "completed"
            assert done["cancelled"] is False
            history = await host.transport.request("GET", "/rt/r1/history")
            payload = json.loads(history.body)
            assert payload["messages"], "引擎回合应写入会话快照"
        finally:
            await host.close()

    asyncio.run(scenario())


def test_repl_survives_two_turns_against_real_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真 REPL 客户端 + 真引擎：连输两句，两句都必须拿到 turn_done。"""
    (tmp_path / "coding.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setenv("QUESTORHARNESS_CONFIG_DIR", str(tmp_path / "cfg"))
    lines = iter(["ping one", "ping two"])

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(lines)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr("builtins.input", fake_input)

    async def scenario() -> None:
        client = ScriptedClient("pong")
        runtime = await build_runtime(
            cwd=str(tmp_path),
            model="fake-model",
            system_prompt="you are a test double",
            api_client=client,
            enforce_max_turns=False,
        )
        host = ServeHost(runtime, authority=Authority(), profile_root=tmp_path)
        await host.start()
        output = Console(file=io.StringIO(), force_terminal=False)
        try:
            code = await asyncio.wait_for(
                run_terminal_client(host, console=output), timeout=30
            )
        finally:
            await host.close()
        assert code == 0
        assert client.calls == 2, "两轮必须各自调用一次模型"
        text = output.file.getvalue()  # type: ignore[union-attr]
        assert text.count("completed") == 2, text

    asyncio.run(scenario())
