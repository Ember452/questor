"""Mirror test for ``surfaces/channels/impl/channel_manager.py`` (plan 01, R7).

Scope note: this manager had no test of any kind before the module was named after
what it holds. Covered here: config-driven construction (including the missing
dependency degradation), the outbound dispatcher's routing and filtering rules, and
the start/stop lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from types import ModuleType, SimpleNamespace

from questorharness.config.schema import Config
from questorharness.surfaces.channels.bus.events import OutboundMessage
from questorharness.surfaces.channels.bus.queue import MessageBus
from questorharness.surfaces.channels.impl.channel_manager import ChannelManager


class _RecordingChannel:
    """Duck-typed channel: records sends, optionally fails to start."""

    name = "stub"

    def __init__(self, config, bus: MessageBus, *, fail_start: bool = False, expect: str | None = None):
        self.config = config
        self.bus = bus
        self.sent: list[OutboundMessage] = []
        self.stopped = False
        self._running = False
        self._fail_start = fail_start
        self._expect = expect
        self.received = asyncio.Event()

    async def start(self) -> None:
        if self._fail_start:
            raise RuntimeError("boom")
        self._running = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)
        if self._expect is None or msg.content == self._expect:
            self.received.set()

    @property
    def is_running(self) -> bool:
        return self._running


def _manager() -> ChannelManager:
    return ChannelManager(Config(), MessageBus())


def _stub(manager: ChannelManager, **kwargs) -> _RecordingChannel:
    channel = _RecordingChannel(SimpleNamespace(allow_from=["*"]), manager.bus, **kwargs)
    manager.channels["stub"] = channel
    return channel


def test_disabled_config_initializes_no_channels() -> None:
    manager = _manager()

    assert manager.channels == {}
    assert manager.enabled_channels == []
    assert manager.get_channel("feishu") is None
    assert manager.get_status() == {}


def test_missing_channel_dependency_degrades_to_warning(monkeypatch, caplog) -> None:
    # A None entry in sys.modules makes the import raise ImportError, exactly what
    # happens when the optional channel package is not installed.
    monkeypatch.setitem(sys.modules, "questorharness.surfaces.channels.impl.feishu", None)
    config = Config()
    config.channels.feishu.enabled = True

    with caplog.at_level(logging.WARNING):
        manager = ChannelManager(config, MessageBus())

    assert manager.channels == {}
    assert "Feishu channel not available" in caplog.text


def test_enabled_channels_are_built_from_their_own_config(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _make(kind: str):
        class _Channel:
            def __init__(self, config, bus, managed_group_checker=None):
                self.config = config
                seen[kind] = (config, bus, managed_group_checker)

        return _Channel

    feishu = ModuleType("questorharness.surfaces.channels.impl.feishu")
    feishu.FeishuChannel = _make("feishu")
    qq = ModuleType("questorharness.surfaces.channels.impl.qq")
    qq.QQChannel = _make("qq")
    monkeypatch.setitem(sys.modules, "questorharness.surfaces.channels.impl.feishu", feishu)
    monkeypatch.setitem(sys.modules, "questorharness.surfaces.channels.impl.qq", qq)

    config = Config()
    config.channels.feishu.enabled = True
    config.channels.qq.enabled = True
    checker = object()
    manager = ChannelManager(config, MessageBus(), managed_group_checker=checker)

    assert list(manager.channels) == ["feishu", "qq"]
    # Each adapter gets its own sub-config, the shared bus, and the group checker.
    assert seen["feishu"] == (config.channels.feishu, manager.bus, checker)
    assert seen["qq"][0] is config.channels.qq
    assert seen["qq"][2] is None


async def test_start_all_without_channels_is_a_noop() -> None:
    manager = _manager()

    await manager.start_all()

    assert manager._dispatch_task is None


async def test_stop_all_without_started_channels_is_safe() -> None:
    manager = _manager()

    await manager.stop_all()

    assert manager._dispatch_task is None


async def test_start_and_stop_all_drives_every_channel() -> None:
    manager = _manager()
    stub = _stub(manager)

    await manager.start_all()
    assert manager._dispatch_task is not None
    assert stub.is_running is True

    await manager.stop_all()
    assert stub.stopped is True
    assert manager._dispatch_task.done()


async def test_dispatcher_routes_matching_channel_and_reports_unknown(caplog) -> None:
    manager = _manager()
    stub = _stub(manager, expect="hi")

    await manager.bus.publish_outbound(OutboundMessage(channel="ghost", chat_id="c", content="gone"))
    await manager.bus.publish_outbound(OutboundMessage(channel="stub", chat_id="c1", content="hi"))
    with caplog.at_level(logging.WARNING):
        await manager.start_all()
        await asyncio.wait_for(stub.received.wait(), timeout=5)
        await manager.stop_all()

    assert [msg.content for msg in stub.sent] == ["hi"]
    assert "Unknown channel: ghost" in caplog.text


async def test_dispatcher_honours_progress_and_tool_hint_switches() -> None:
    config = Config()
    config.channels.send_progress = False
    config.channels.send_tool_hints = False
    manager = ChannelManager(config, MessageBus())
    stub = _stub(manager, expect="final")

    await manager.bus.publish_outbound(
        OutboundMessage(channel="stub", chat_id="c", content="progress", metadata={"_progress": True})
    )
    await manager.bus.publish_outbound(
        OutboundMessage(
            channel="stub", chat_id="c", content="hint", metadata={"_progress": True, "_tool_hint": True}
        )
    )
    await manager.bus.publish_outbound(OutboundMessage(channel="stub", chat_id="c", content="final"))

    await manager.start_all()
    await asyncio.wait_for(stub.received.wait(), timeout=5)
    await manager.stop_all()

    assert [msg.content for msg in stub.sent] == ["final"]


async def test_send_failure_is_contained(caplog) -> None:
    manager = _manager()

    class _Failing(_RecordingChannel):
        async def send(self, msg: OutboundMessage) -> None:
            self.sent.append(msg)
            self.received.set()
            raise RuntimeError("transport down")

    stub = _Failing(SimpleNamespace(allow_from=["*"]), manager.bus)
    manager.channels["stub"] = stub

    await manager.bus.publish_outbound(OutboundMessage(channel="stub", chat_id="c", content="hi"))
    with caplog.at_level(logging.ERROR):
        await manager.start_all()
        await asyncio.wait_for(stub.received.wait(), timeout=5)
        await manager.stop_all()

    assert "Error sending to stub" in caplog.text


async def test_failing_channel_start_is_recorded_not_raised(caplog) -> None:
    manager = _manager()
    broken = _RecordingChannel(SimpleNamespace(allow_from=["*"]), manager.bus, fail_start=True)

    with caplog.at_level(logging.ERROR):
        await manager._start_channel("broken", broken)

    assert broken.last_error == "boom"
    assert "Failed to start channel broken" in caplog.text


def test_empty_allow_from_is_flagged(caplog) -> None:
    manager = _manager()
    manager.channels["stub"] = _RecordingChannel(SimpleNamespace(allow_from=[]), manager.bus)

    with caplog.at_level(logging.WARNING):
        manager._validate_allow_from()

    assert "stub channel has empty allow_from" in caplog.text


async def test_get_status_reports_enabled_and_running() -> None:
    manager = _manager()
    stub = _stub(manager)

    assert manager.get_status() == {"stub": {"enabled": True, "running": False}}

    await stub.start()
    assert manager.get_status() == {"stub": {"enabled": True, "running": True}}
    assert manager.enabled_channels == ["stub"]
    assert manager.get_channel("stub") is stub
