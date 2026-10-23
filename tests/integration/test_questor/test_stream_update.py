"""Mirror test for ``src/questor/gateway/stream_update.py`` (plan 01, R7).

The value type is shared by the runtime pool, media handling and the channel
bridge, so what the test pins is its shape: required fields, no shared mutable
default, and an optional media list.
"""

from __future__ import annotations

from questor.gateway.stream_update import GatewayStreamUpdate


def test_required_fields_are_kept_as_given() -> None:
    update = GatewayStreamUpdate(kind="text", text="hello", metadata={"chat_id": "c1"})

    assert update.kind == "text"
    assert update.text == "hello"
    assert update.metadata == {"chat_id": "c1"}


def test_media_defaults_to_absent() -> None:
    assert GatewayStreamUpdate(kind="text", text="", metadata={}).media is None


def test_media_list_is_per_instance_not_shared() -> None:
    first = GatewayStreamUpdate(kind="media", text="", metadata={}, media=["a.png"])
    second = GatewayStreamUpdate(kind="media", text="", metadata={})

    assert first.media == ["a.png"]
    assert second.media is None
    second.media = ["b.png"]
    assert first.media == ["a.png"], "instances must not share a media list"
