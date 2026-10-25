"""CLI 工具名单必须真的进 build_runtime（否则 flag 只是装饰）。"""

from __future__ import annotations

import asyncio
import io
import sys
from typing import Any

from questorharness.bootstrap.hosts import app


def test_task_worker_forwards_tool_policy(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """--allowed-tools/--disallowed-tools 经 task worker 落到 build_runtime。"""
    captured: dict[str, Any] = {}

    async def fake_build_runtime(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    async def fake_noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(app, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(app, "start_runtime", fake_noop)
    monkeypatch.setattr(app, "close_runtime", fake_noop)
    monkeypatch.setattr(app, "handle_line", fake_noop)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    asyncio.run(
        app.run_task_worker(
            cwd=str(tmp_path),
            allowed_tools=["read_file"],
            denied_tools=["write_file"],
        )
    )

    assert captured["allowed_tools"] == ["read_file"]
    assert captured["denied_tools"] == ["write_file"]


def test_task_worker_without_policy_inherits(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """未给名单时传 None，表示完全继承（不得被写成空列表）。"""
    captured: dict[str, Any] = {}

    async def fake_build_runtime(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    async def fake_noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(app, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(app, "start_runtime", fake_noop)
    monkeypatch.setattr(app, "close_runtime", fake_noop)
    monkeypatch.setattr(app, "handle_line", fake_noop)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    asyncio.run(app.run_task_worker(cwd=str(tmp_path)))

    assert captured["allowed_tools"] is None
    assert captured["denied_tools"] is None
