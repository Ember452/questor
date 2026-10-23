"""Public engine facade for the product app.

``src/questor`` may import this module and ``questorharness.bootstrap`` only;
the ``product-uses-public-face`` import-linter contract enforces it.

Transitional: a few ``_``-prefixed helpers are re-exported because the product
currently depends on them. They should gain public names when their owning
modules are reshaped.
"""

from __future__ import annotations

from questorharness.capabilities.memory import load_memory_prompt
from questorharness.capabilities.memory.scan import scan_memory_files
from questorharness.capabilities.memory.schema import (
    SCHEMA_VERSION,
    coerce_int,
    compute_memory_signature,
    first_content_line,
    format_datetime,
    generate_memory_id,
    memory_metadata_from_path,
    render_memory_file,
    split_memory_file,
    utc_now,
)
from questorharness.capabilities.tools.base import BaseTool, ToolExecutionContext, ToolResult
from questorharness.commands import (
    CommandContext,
    CommandResult,
    MemoryCommandBackend,
    lookup_skill_slash_command,
)
from questorharness.config import load_settings
from questorharness.config.schema import Config
from questorharness.contracts.domain.message import (
    ConversationMessage,
    ImageBlock,
    TextBlock,
    sanitize_conversation_messages,
)
from questorharness.engine.query import MaxTurnsExceeded
from questorharness.contracts.domain.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from questorharness.capabilities.context.prompts import build_runtime_system_prompt
from questorharness.capabilities.context.prompts.system_prompt import get_base_system_prompt
from questorharness.providers.auth.manager import AuthManager
from questorharness.providers.llm.client import SupportsStreamingMessages
from questorharness.contracts.usage import UsageSnapshot
from questorharness.capabilities.schedule.cron_scheduler import register_notification_handler
from questorharness.runtime.session.backend import SessionBackend
from questorharness.contracts.session_storage import (
    _persistable_tool_metadata,
    _sanitize_snapshot_payload,
)
from questorharness.surfaces.channels.bus.events import InboundMessage, OutboundMessage
from questorharness.surfaces.channels.bus.queue import MessageBus
from questorharness.surfaces.channels.impl.manager import ChannelManager
from questorharness.ui.backend_host import run_backend_host
from questorharness.ui.react_launcher import _resolve_npm, _resolve_tsx, get_frontend_dir
from questorharness.ui.runtime import (
    RuntimeBundle,
    _last_user_text,
    build_runtime,
    close_runtime,
    handle_line,
    start_runtime,
)
from questorharness.contracts.locking import exclusive_file_lock
from questorharness.contracts.io import atomic_write_text

__all__ = [
    "SCHEMA_VERSION",
    "AssistantTextDelta",
    "AssistantTurnComplete",
    "AuthManager",
    "BaseTool",
    "ChannelManager",
    "CommandContext",
    "CommandResult",
    "CompactProgressEvent",
    "Config",
    "ConversationMessage",
    "ErrorEvent",
    "ImageBlock",
    "InboundMessage",
    "MaxTurnsExceeded",
    "MemoryCommandBackend",
    "MessageBus",
    "OutboundMessage",
    "RuntimeBundle",
    "SessionBackend",
    "StatusEvent",
    "SupportsStreamingMessages",
    "TextBlock",
    "ToolExecutionContext",
    "ToolExecutionCompleted",
    "ToolExecutionStarted",
    "ToolResult",
    "UsageSnapshot",
    "_last_user_text",
    "_persistable_tool_metadata",
    "_resolve_npm",
    "_resolve_tsx",
    "_sanitize_snapshot_payload",
    "atomic_write_text",
    "build_runtime",
    "build_runtime_system_prompt",
    "close_runtime",
    "coerce_int",
    "compute_memory_signature",
    "exclusive_file_lock",
    "first_content_line",
    "format_datetime",
    "generate_memory_id",
    "get_base_system_prompt",
    "get_frontend_dir",
    "handle_line",
    "load_memory_prompt",
    "load_settings",
    "lookup_skill_slash_command",
    "memory_metadata_from_path",
    "register_notification_handler",
    "render_memory_file",
    "run_backend_host",
    "sanitize_conversation_messages",
    "scan_memory_files",
    "split_memory_file",
    "start_runtime",
    "utc_now",
]
