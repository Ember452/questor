"""host 模块镜像测试：构造期接线与不变式。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from questorharness.bootstrap.hosts.serve import ServeHost
from questorharness.bootstrap.hosts.serve.authority import Authority


def test_host_wires_notifier_and_keeps_injected_runtime(tmp_path: Path) -> None:
    """宿主收注入的 runtime，并把提示回调接到 authority（不自己建 runtime）。"""
    authority = Authority()
    runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
    host = ServeHost(runtime, authority=authority, profile_root=tmp_path)  # type: ignore[arg-type]
    assert host.runtime is runtime
    assert authority._on_prompt is not None
    assert host.profile_id == "coding"
    assert host.router is not None


def test_lease_released_even_when_turn_done_publish_is_cancelled(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """第二次取消不得饿死租约：turn_done 广播被打断也要 finish/pop_queued。"""
    import questorharness.bootstrap.runtime as runtime_module

    async def fake_handle_line(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(runtime_module, "handle_line", fake_handle_line)

    authority = Authority()
    runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
    host = ServeHost(runtime, authority=authority, profile_root=tmp_path)  # type: ignore[arg-type]
    original_publish = host.broadcaster.publish

    async def flaky_publish(frame):  # type: ignore[no-untyped-def]
        if frame.get("kind") == "turn_done":
            raise asyncio.CancelledError
        await original_publish(frame)

    monkeypatch.setattr(host.broadcaster, "publish", flaky_publish)

    async def scenario() -> None:
        begin = authority.begin("c1", "req-1", "hi")
        record = authority.active_turn
        assert record is not None
        assert record.turn_id == begin.turn_id
        await host._run_turn(record)  # type: ignore[attr-defined]
        assert authority.active_turn is None

    asyncio.run(scenario())


def test_api_rejection_notice_carries_provider_context(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """401/403 裸错误对用户无信息量：notice 必须带上当前生效的连接配置。"""
    import questorharness.bootstrap.runtime as runtime_module

    async def broken_handle_line(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("Error code: 403 - {'error': {'type': 'forbidden', 'message': 'Request not allowed'}}")

    monkeypatch.setattr(runtime_module, "handle_line", broken_handle_line)

    authority = Authority()
    runtime = SimpleNamespace(
        cwd=str(tmp_path),
        session_id="sid",
        current_settings=lambda: SimpleNamespace(
            provider="anthropic", api_format="anthropic", base_url=None, model="claude-haiku-4-5"
        ),
    )
    host = ServeHost(runtime, authority=authority, profile_root=tmp_path)  # type: ignore[arg-type]
    frames: list[dict] = []

    async def capture_publish(frame):  # type: ignore[no-untyped-type]
        frames.append(frame)

    monkeypatch.setattr(host.broadcaster, "publish", capture_publish)

    async def scenario() -> None:
        begin = authority.begin("c1", "req-1", "hi")
        record = authority.active_turn
        assert record is not None
        await host._run_turn(record)  # type: ignore[attr-defined]

    asyncio.run(scenario())
    notices = [f for f in frames if f.get("kind") == "notice"]
    assert notices, "失败回合必须落 notice"
    text = str(notices[0].get("text"))
    assert "provider=anthropic" in text
    assert "api_format=anthropic" in text
    assert "官方默认" in text
    assert "claude-haiku-4-5" in text
