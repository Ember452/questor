from __future__ import annotations

from questorharness.channels.impl.base import resolve_channel_media_dir


def test_resolve_channel_media_dir_uses_explicit_media_root(monkeypatch, tmp_path):
    media_root = tmp_path / "media-root"
    monkeypatch.setenv("QUESTORHARNESS_CHANNEL_MEDIA_DIR", str(media_root))
    monkeypatch.delenv("QUESTORHARNESS_DATA_DIR", raising=False)

    media_dir = resolve_channel_media_dir("feishu")

    assert media_dir == media_root / "feishu"
    assert media_dir.is_dir()


def test_resolve_channel_media_dir_uses_questorharness_data_dir(monkeypatch, tmp_path):
    data_dir = tmp_path / ".questorharness-data"
    monkeypatch.delenv("QUESTOR_WORKSPACE", raising=False)
    monkeypatch.delenv("QUESTORHARNESS_CHANNEL_MEDIA_DIR", raising=False)
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(data_dir))

    media_dir = resolve_channel_media_dir("qq")

    assert media_dir == data_dir / "media" / "qq"
    assert media_dir.is_dir()
