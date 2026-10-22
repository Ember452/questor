"""Message bus module for decoupled channel-agent communication."""

from questorharness.channels.bus.events import InboundMessage, OutboundMessage
from questorharness.channels.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
