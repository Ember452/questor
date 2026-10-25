"""terminal_client 镜像测试：SSE 解析、默认形态目录与工具面注入。"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any

from questorharness.bootstrap.hosts import terminal_client


def test_sse_frame_parsing() -> None:
    """只认 data 行，非法 JSON 返回 None。"""
    block = b'id: 1\nevent: frame\ndata: {"kind":"text","text":"hi"}\n'
    assert terminal_client._frame_from_sse(block) == {"kind": "text", "text": "hi"}
    assert terminal_client._frame_from_sse(b"id: 1\nevent: frame\ndata: not-json\n") is None


def test_merge_tool_overrides_keeps_profile_baseline() -> None:
    """CLI 只给黑名单时，profile 的白名单仍要保留（覆盖只许收窄）。"""
    profile = SimpleNamespace(allowed_tools=("ask_user_question",), denied_tools=("bash",))
    merged = terminal_client.merge_tool_overrides(
        profile, {"allowed_tools": None, "denied_tools": ["write_file"]}
    )
    assert merged["allowed_tools"] == ["ask_user_question"]
    assert merged["denied_tools"] == ["write_file"]
    assert terminal_client.merge_tool_overrides(profile, None) == {
        "allowed_tools": ["ask_user_question"],
        "denied_tools": ["bash"],
    }


def test_default_profile_root_honours_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """环境变量优先，便于产品切换形态目录。"""
    monkeypatch.setenv("QUESTOR_PROFILE_ROOT", "D:/profiles")
    assert str(terminal_client.default_profile_root()).endswith("profiles")


def test_build_serve_host_forwards_profile_tool_surface(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """端到端断言：profile 的 allowed/denied 真的进了 build_runtime。"""
    (tmp_path / "coding.yaml").write_text(
        "name: coding\nallowed_tools: []\ndenied_tools: []\nui:\n  capabilities:\n    chat: ready\n",
        encoding="utf-8",
    )
    (tmp_path / "personal.yaml").write_text(
        "name: personal\nallowed_tools: [ask_user_question]\n"
        "denied_tools: [bash, edit_file]\nui:\n  capabilities:\n    chat: declared\n",
        encoding="utf-8",
    )
    captured: dict[str, Any] = {}

    async def fake_build_runtime(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace()

    class FakeHost:
        def __init__(self, runtime: Any, **kwargs: Any) -> None:
            self.runtime = runtime
            self.kwargs = kwargs

    monkeypatch.setattr(terminal_client, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(terminal_client, "ServeHost", FakeHost)

    asyncio.run(terminal_client.build_serve_host(profile_root=tmp_path, profile_id="personal"))
    assert captured["allowed_tools"] == ["ask_user_question"]
    assert captured["denied_tools"] == ["bash", "edit_file"]


def test_completion_catalog_maps_names_and_aliases() -> None:
    """补全目录：主名与别名都指向描述，主名优先不被别名覆盖。"""
    commands = [
        {"name": "help", "description": "列出指令", "aliases": ["h"]},
        {"name": "exit", "description": "退出", "aliases": []},
    ]
    catalog = terminal_client.completion_catalog(commands)
    assert catalog["/help"] == "列出指令"
    assert catalog["/h"] == "列出指令"
    assert catalog["/exit"] == "退出"
    assert len(catalog) == 3


def test_build_prompt_session_returns_none_off_tty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """非 TTY（管道/CI）一律回退裸 input，不建交互会话。"""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert terminal_client._build_prompt_session([]) is None
