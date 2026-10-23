"""Event types for the message bus."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str  # feishu、qq
    sender_id: str  # 用户标识
    chat_id: str  # 聊天/频道标识
    content: str  # 消息文本
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # 媒体 URL
    metadata: dict[str, Any] = field(default_factory=dict)  # 渠道专用数据
    session_key_override: str | None = None  # 线程级会话的可选覆盖项

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


