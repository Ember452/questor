"""File-based async message queue for leader-worker communication in QuestorHarness swarms.

Each message is stored as an individual JSON file:
    ~/.questorharness/teams/<team>/agents/<agent_id>/inbox/<timestamp>_<message_id>.json

Atomic writes use a .tmp file followed by os.rename to prevent partial reads.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from questorharness.swarm.lockfile import exclusive_file_lock


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

MessageType = Literal[
    "user_message",
    "permission_request",
    "permission_response",
    "sandbox_permission_request",
    "sandbox_permission_response",
    "shutdown",
    "idle_notification",
]


@dataclass
class MailboxMessage:
    """A single message exchanged between swarm agents."""

    id: str
    type: MessageType
    sender: str
    recipient: str
    payload: dict[str, Any]
    timestamp: float
    read: bool = False

    # ------------------------------------------------------------------
    # 序列化辅助函数
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MailboxMessage":
        return cls(
            id=data["id"],
            type=data["type"],
            sender=data["sender"],
            recipient=data["recipient"],
            payload=data.get("payload", {}),
            timestamp=data["timestamp"],
            read=data.get("read", False),
        )


# ---------------------------------------------------------------------------
# 目录辅助函数
# ---------------------------------------------------------------------------


def get_team_dir(team_name: str) -> Path:
    """Return ~/.questorharness/teams/<team_name>/"""
    base = Path.home() / ".questorharness" / "teams" / team_name
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_agent_mailbox_dir(team_name: str, agent_id: str) -> Path:
    """Return ~/.questorharness/teams/<team_name>/agents/<agent_id>/inbox/"""
    inbox = get_team_dir(team_name) / "agents" / agent_id / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


# ---------------------------------------------------------------------------
# 队友邮箱
# ---------------------------------------------------------------------------


class TeammateMailbox:
    """File-based mailbox for a single agent within a swarm team.

    Each message lives in its own JSON file named ``<timestamp>_<id>.json``
    inside the agent's inbox directory.  Writes are atomic: the payload is
    first written to a ``.tmp`` file, then renamed into place so that readers
    never see a partial message.
    """

    def __init__(self, team_name: str, agent_id: str) -> None:
        self.team_name = team_name
        self.agent_id = agent_id

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def get_mailbox_dir(self) -> Path:
        """Return the inbox directory path, creating it if necessary."""
        return get_agent_mailbox_dir(self.team_name, self.agent_id)

    def _lock_path(self) -> Path:
        return self.get_mailbox_dir() / ".write_lock"

    async def write(self, msg: MailboxMessage) -> None:
        """Atomically write *msg* to the inbox as a JSON file.

        The file is first written to ``<name>.tmp`` then renamed into the
        inbox directory so that concurrent readers never observe a partial
        write.

        This method uses a thread pool for the blocking I/O operations and
        acquires an exclusive lock to prevent concurrent write conflicts.
        """
        inbox = self.get_mailbox_dir()
        filename = f"{msg.timestamp:.6f}_{msg.id}.json"
        final_path = inbox / filename
        tmp_path = inbox / f"{filename}.tmp"
        lock_path = inbox / ".write_lock"

        payload = json.dumps(msg.to_dict(), indent=2)

        def _write_atomic() -> None:
            with exclusive_file_lock(lock_path):
                tmp_path.write_text(payload, encoding="utf-8")
                os.replace(tmp_path, final_path)

        # 将阻塞式 I/O 卸载到线程池
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_atomic)

    async def read_all(self, unread_only: bool = True) -> list[MailboxMessage]:
        """Return messages from the inbox, sorted by timestamp (oldest first).

        Args:
            unread_only: When *True* (default) only unread messages are
                returned.  Pass *False* to retrieve all messages including
                already-read ones.
        """
        inbox = self.get_mailbox_dir()

        def _read_all() -> list[MailboxMessage]:
            messages: list[MailboxMessage] = []
            for path in sorted(inbox.glob("*.json")):
                # 跳过锁文件和临时文件
                if path.name.startswith(".") or path.name.endswith(".tmp"):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    msg = MailboxMessage.from_dict(data)
                    if not unread_only or not msg.read:
                        messages.append(msg)
                except (json.JSONDecodeError, KeyError):
                    # 跳过损坏的消息文件，而不是崩溃。
                    continue
            return messages

        # 将阻塞式 I/O 卸载到线程池
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _read_all)

    async def mark_read(self, message_id: str) -> None:
        """Mark the message with *message_id* as read (in-place update)."""
        inbox = self.get_mailbox_dir()
        lock_path = self._lock_path()

        def _mark_read() -> bool:
            with exclusive_file_lock(lock_path):
                for path in inbox.glob("*.json"):
                    # 跳过锁文件和临时文件
                    if path.name.startswith(".") or path.name.endswith(".tmp"):
                        continue
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        continue

                    if data.get("id") == message_id:
                        data["read"] = True
                        tmp_path = path.with_suffix(".json.tmp")
                        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        os.replace(tmp_path, path)
                        return True
                return False

        # 将阻塞式 I/O 卸载到线程池
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _mark_read)

    async def clear(self) -> None:
        """Remove all message files from the inbox."""
        inbox = self.get_mailbox_dir()
        lock_path = self._lock_path()

        def _clear() -> None:
            with exclusive_file_lock(lock_path):
                for path in inbox.glob("*.json"):
                    # 跳过锁文件
                    if path.name.startswith("."):
                        continue
                    try:
                        path.unlink()
                    except OSError:
                        pass

        # 将阻塞式 I/O 卸载到线程池
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _clear)


# ---------------------------------------------------------------------------
# 工厂辅助函数（基础）
# ---------------------------------------------------------------------------


def _make_message(
    msg_type: MessageType,
    sender: str,
    recipient: str,
    payload: dict[str, Any],
) -> MailboxMessage:
    return MailboxMessage(
        id=str(uuid.uuid4()),
        type=msg_type,
        sender=sender,
        recipient=recipient,
        payload=payload,
        timestamp=time.time(),
    )


def create_user_message(sender: str, recipient: str, content: str) -> MailboxMessage:
    """Create a plain text user message."""
    return _make_message("user_message", sender, recipient, {"content": content})


def create_shutdown_request(sender: str, recipient: str) -> MailboxMessage:
    """Create a shutdown request message."""
    return _make_message("shutdown", sender, recipient, {})


def create_idle_notification(
    sender: str, recipient: str, summary: str
) -> MailboxMessage:
    """Create an idle-notification message with a brief summary."""
    return _make_message(
        "idle_notification", sender, recipient, {"summary": summary}
    )


# ---------------------------------------------------------------------------
# 权限消息工厂函数（对应 TS 的 teammateMailbox.ts）
# ---------------------------------------------------------------------------


def create_permission_request_message(
    sender: str,
    recipient: str,
    request_data: dict[str, Any],
) -> MailboxMessage:
    """Create a permission_request message from worker to leader.

    Args:
        sender: The sending worker's agent name.
        recipient: The recipient leader's agent name.
        request_data: Dict with keys: request_id, agent_id, tool_name,
            tool_use_id, description, input, permission_suggestions.

    Returns:
        A :class:`MailboxMessage` of type ``permission_request``.
    """
    payload: dict[str, Any] = {
        "type": "permission_request",
        "request_id": request_data.get("request_id", ""),
        "agent_id": request_data.get("agent_id", sender),
        "tool_name": request_data.get("tool_name", ""),
        "tool_use_id": request_data.get("tool_use_id", ""),
        "description": request_data.get("description", ""),
        "input": request_data.get("input", {}),
        "permission_suggestions": request_data.get("permission_suggestions", []),
    }
    return _make_message("permission_request", sender, recipient, payload)


def create_permission_response_message(
    sender: str,
    recipient: str,
    response_data: dict[str, Any],
) -> MailboxMessage:
    """Create a permission_response message from leader to worker.

    Args:
        sender: The sending leader's agent name.
        recipient: The target worker's agent name.
        response_data: Dict with keys: request_id, subtype ('success'|'error'),
            error (optional), updated_input (optional), permission_updates (optional).

    Returns:
        A :class:`MailboxMessage` of type ``permission_response``.
    """
    subtype = response_data.get("subtype", "success")
    if subtype == "error":
        payload: dict[str, Any] = {
            "type": "permission_response",
            "request_id": response_data.get("request_id", ""),
            "subtype": "error",
            "error": response_data.get("error", "Permission denied"),
        }
    else:
        payload = {
            "type": "permission_response",
            "request_id": response_data.get("request_id", ""),
            "subtype": "success",
            "response": {
                "updated_input": response_data.get("updated_input"),
                "permission_updates": response_data.get("permission_updates"),
            },
        }
    return _make_message("permission_response", sender, recipient, payload)


def create_sandbox_permission_request_message(
    sender: str,
    recipient: str,
    request_data: dict[str, Any],
) -> MailboxMessage:
    """Create a sandbox_permission_request message from worker to leader.

    Args:
        sender: The sending worker's agent name.
        recipient: The recipient leader's agent name.
        request_data: Dict with keys: requestId, workerId, workerName,
            workerColor (optional), host.

    Returns:
        A :class:`MailboxMessage` of type ``sandbox_permission_request``.
    """
    payload: dict[str, Any] = {
        "type": "sandbox_permission_request",
        "requestId": request_data.get("requestId", ""),
        "workerId": request_data.get("workerId", sender),
        "workerName": request_data.get("workerName", sender),
        "workerColor": request_data.get("workerColor"),
        "hostPattern": {"host": request_data.get("host", "")},
        "createdAt": int(time.time() * 1000),
    }
    return _make_message("sandbox_permission_request", sender, recipient, payload)


def create_sandbox_permission_response_message(
    sender: str,
    recipient: str,
    response_data: dict[str, Any],
) -> MailboxMessage:
    """Create a sandbox_permission_response message from leader to worker.

    Args:
        sender: The sending leader's agent name.
        recipient: The target worker's agent name.
        response_data: Dict with keys: requestId, host, allow.

    Returns:
        A :class:`MailboxMessage` of type ``sandbox_permission_response``.
    """
    from datetime import datetime, timezone

    payload: dict[str, Any] = {
        "type": "sandbox_permission_response",
        "requestId": response_data.get("requestId", ""),
        "host": response_data.get("host", ""),
        "allow": bool(response_data.get("allow", False)),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    return _make_message("sandbox_permission_response", sender, recipient, payload)


# ---------------------------------------------------------------------------
# 类型守卫辅助函数（对应 TS 的 isPermissionRequest 等）
# ---------------------------------------------------------------------------


def is_permission_request(msg: MailboxMessage) -> dict[str, Any] | None:
    """Return the permission request payload if *msg* is a permission_request, else None."""
    if msg.type == "permission_request":
        return msg.payload
    # 同时检查 text 字段，以兼容文本信封消息
    text = msg.payload.get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("type") == "permission_request":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def is_permission_response(msg: MailboxMessage) -> dict[str, Any] | None:
    """Return the permission response payload if *msg* is a permission_response, else None."""
    if msg.type == "permission_response":
        return msg.payload
    text = msg.payload.get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("type") == "permission_response":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def is_sandbox_permission_request(msg: MailboxMessage) -> dict[str, Any] | None:
    """Return payload if *msg* is a sandbox_permission_request, else None."""
    if msg.type == "sandbox_permission_request":
        return msg.payload
    text = msg.payload.get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("type") == "sandbox_permission_request":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def is_sandbox_permission_response(msg: MailboxMessage) -> dict[str, Any] | None:
    """Return payload if *msg* is a sandbox_permission_response, else None."""
    if msg.type == "sandbox_permission_response":
        return msg.payload
    text = msg.payload.get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("type") == "sandbox_permission_response":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


# ---------------------------------------------------------------------------
# 全局邮箱便捷函数（对应 TS 的 writeToMailbox 等）
# ---------------------------------------------------------------------------


async def write_to_mailbox(
    recipient_name: str,
    message: dict[str, Any],
    team_name: str | None = None,
) -> None:
    """Write a TeammateMessage-format dict to a recipient's mailbox.

    This mirrors the TS ``writeToMailbox(recipientName, message, teamName)``
    function.  The *message* dict should have at minimum a ``from`` key and
    a ``text`` key (the serialised message content), and optionally
    ``timestamp``, ``color``, and ``summary``.

    Args:
        recipient_name: The recipient agent's name/id.
        message: Dict with ``from``, ``text``, and optional fields.
        team_name: Optional team name; defaults to ``CLAUDE_CODE_TEAM_NAME``
            env var, then ``"default"``.
    """
    team = team_name or os.environ.get("CLAUDE_CODE_TEAM_NAME", "default")
    text = message.get("text", "")

    # 从序列化文本内容检测消息类型，确保路由正常
    msg_type: MessageType = "user_message"
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "type" in parsed:
            t = parsed["type"]
            if t in (
                "permission_request",
                "permission_response",
                "sandbox_permission_request",
                "sandbox_permission_response",
                "shutdown",
                "idle_notification",
            ):
                msg_type = t  # type: ignore[assignment]
    except (json.JSONDecodeError, TypeError):
        pass

    msg = MailboxMessage(
        id=str(uuid.uuid4()),
        type=msg_type,
        sender=message.get("from", "unknown"),
        recipient=recipient_name,
        payload={
            "text": text,
            "color": message.get("color"),
            "summary": message.get("summary"),
            "timestamp": message.get("timestamp"),
        },
        timestamp=time.time(),
    )
    mailbox = TeammateMailbox(team, recipient_name)
    await mailbox.write(msg)
