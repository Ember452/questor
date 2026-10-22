"""QuestorHarness channels subsystem.

Provides a message-bus architecture for integrating chat platforms
(Telegram, Discord, Slack, etc.) with the QuestorHarness query engine.

Usage::

    from questorharness.channels import BaseChannel, ChannelManager, MessageBus
"""

from questorharness.channels.bus.events import InboundMessage, OutboundMessage
from questorharness.channels.bus.queue import MessageBus
from questorharness.channels.impl.base import BaseChannel
from questorharness.channels.impl.manager import ChannelManager

__all__ = [
    "BaseChannel",
    "ChannelManager",
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
]
