"""terminal_client 镜像测试：SSE 解析与默认形态目录。"""

from __future__ import annotations

from questorharness.bootstrap.hosts import terminal_client


def test_sse_frame_parsing() -> None:
    """只认 data 行，非法 JSON 返回 None。"""
    block = b'id: 1\nevent: frame\ndata: {"kind":"text","text":"hi"}\n'
    assert terminal_client._frame_from_sse(block) == {"kind": "text", "text": "hi"}
    assert terminal_client._frame_from_sse(b"id: 1\nevent: frame\ndata: not-json\n") is None


def test_default_profile_root_honours_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """环境变量优先，便于产品切换形态目录。"""
    monkeypatch.setenv("QUESTOR_PROFILE_ROOT", "D:/profiles")
    assert str(terminal_client.default_profile_root()).endswith("profiles")
