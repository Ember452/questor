from __future__ import annotations

from questorharness.channels.impl.base import resolve_channel_media_dir


def test_resolve_channel_media_dir_uses_questor_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / ".questor-home"
    monkeypatch.setenv("QUESTOR_WORKSPACE", str(workspace))
    monkeypatch.delenv("QUESTORHARNESS_CHANNEL_MEDIA_DIR", raising=False)
    monkeypatch.delenv("QUESTORHARNESS_DATA_DIR", raising=False)

    media_dir = resolve_channel_media_dir("feishu")

    assert media_dir == workspace / "attachments" / "feishu"
    assert media_dir.is_dir()


def test_resolve_channel_media_dir_uses_questorharness_data_dir(monkeypatch, tmp_path):
    data_dir = tmp_path / ".questorharness-data"
    monkeypatch.delenv("QUESTOR_WORKSPACE", raising=False)
    monkeypatch.delenv("QUESTORHARNESS_CHANNEL_MEDIA_DIR", raising=False)
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(data_dir))

    media_dir = resolve_channel_media_dir("qq")

    assert media_dir == data_dir / "media" / "qq"
    assert media_dir.is_dir()
