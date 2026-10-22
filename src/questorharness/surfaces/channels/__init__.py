"""QuestorHarness channels subsystem.

Provides a message-bus architecture for integrating chat platforms
(Telegram, Discord, Slack, etc.) with the QuestorHarness query engine.

Usage::

    from questorharness.surfaces.channels import BaseChannel, ChannelManager, MessageBus
"""

from questorharness.surfaces.channels.bus.events import InboundMessage, OutboundMessage
from questorharness.surfaces.channels.bus.queue import MessageBus
from questorharness.surfaces.channels.impl.base import BaseChannel
from questorharness.surfaces.channels.impl.manager import ChannelManager

__all__ = [
    "BaseChannel",
    "ChannelManager",
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
]
