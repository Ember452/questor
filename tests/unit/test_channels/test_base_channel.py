"""Mirror test for ``surfaces/channels/impl/base_channel.py`` (plan 01, R7).

Scope note: the two media-directory cases came over from ``test_base.py`` when the
module was renamed, so the test file now names the module it actually covers
instead of borrowing a generic stem. The cases added below cover the part that had
no direct test at all: the ``allow_from`` permission rules and the inbound
forwarding path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from questorharness.surfaces.channels.bus.events import OutboundMessage
from questorharness.surfaces.channels.bus.queue import MessageBus
from questorharness.surfaces.channels.impl.base_channel import (
    BaseChannel,
    resolve_channel_media_dir,
)


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


class _StubChannel(BaseChannel):
    """Smallest concrete channel: it records what it was asked to send."""

    name = "stub"

    def __init__(self, config, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


def _channel(allow_from: list[str] | None = None) -> _StubChannel:
    config = SimpleNamespace(allow_from=[] if allow_from is None else allow_from)
    return _StubChannel(config, MessageBus())


def test_base_channel_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        BaseChannel(SimpleNamespace(allow_from=["*"]), MessageBus())  # type: ignore[abstract]


def test_new_channel_is_not_running() -> None:
    channel = _channel(["*"])
    assert channel.name == "stub"
    assert channel.is_running is False
    assert channel._running is False


async def test_start_and_stop_flip_running_flag() -> None:
    channel = _channel(["*"])
    await channel.start()
    assert channel.is_running is True
    await channel.stop()
    assert channel.is_running is False


def test_empty_allow_from_denies_every_sender() -> None:
    channel = _channel([])
    assert channel.is_allowed("alice") is False


def test_wildcard_allows_any_sender() -> None:
    channel = _channel(["*"])
    assert channel.is_allowed("alice") is True
    assert channel.is_allowed(" anyone ") is True


def test_exact_sender_id_is_allowed() -> None:
    channel = _channel(["alice"])
    assert channel.is_allowed("alice") is True
    assert channel.is_allowed("bob") is False


def test_pipe_separated_sender_matches_any_part() -> None:
    channel = _channel(["team-a"])
    assert channel.is_allowed("user-1|team-a") is True
    assert channel.is_allowed("user-1|team-b") is False


async def test_handle_message_forwards_allowed_sender_to_bus() -> None:
    channel = _channel(["alice"])
    await channel._handle_message(
        "alice",
        "chat-9",
        "hello",
        media=["a.png"],
        metadata={"k": "v"},
        session_key="thread-1",
    )

    msg = channel.bus.inbound.get_nowait()
    assert msg.channel == "stub"
    assert msg.sender_id == "alice"
    assert msg.chat_id == "chat-9"
    assert msg.content == "hello"
    assert msg.media == ["a.png"]
    assert msg.metadata == {"k": "v"}
    assert msg.session_key_override == "thread-1"
    assert msg.session_key == "thread-1"


async def test_handle_message_drops_denied_sender() -> None:
    channel = _channel(["alice"])
    await channel._handle_message("bob", "chat-9", "hello")

    assert channel.bus.inbound.empty()


async def test_handle_message_defaults_media_metadata_and_session_key() -> None:
    channel = _channel(["*"])
    await channel._handle_message("alice", "chat-1", "plain")

    msg = channel.bus.inbound.get_nowait()
    assert msg.media == []
    assert msg.metadata == {}
    assert msg.session_key_override is None
    assert msg.session_key == "stub:chat-1"
