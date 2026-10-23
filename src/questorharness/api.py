"""Public engine facade for the product app.

``src/questor`` may import this module and ``questorharness.bootstrap`` only;
the ``product-uses-public-face`` import-linter contract enforces it.

Transitional: a few ``_``-prefixed helpers are re-exported because the product
currently depends on them. They should gain public names when their owning
modules are reshaped.
"""

from __future__ import annotations

from questorharness.bootstrap.hosts.backend_host import run_backend_host
from questorharness.bootstrap.hosts.react_launcher import get_frontend_dir, resolve_npm, resolve_tsx
from questorharness.bootstrap.runtime import (
    RuntimeBundle,
    build_runtime,
    close_runtime,
    handle_line,
    last_user_text,
    start_runtime,
)
from questorharness.capabilities.context.prompts import build_runtime_system_prompt
from questorharness.capabilities.context.prompts.system_prompt import get_base_system_prompt
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
from questorharness.capabilities.schedule.cron_scheduler import register_notification_handler
from questorharness.capabilities.tools.base import BaseTool, ToolExecutionContext, ToolResult
from questorharness.commands import (
    CommandContext,
    CommandResult,
    MemoryCommandBackend,
    lookup_skill_slash_command,
)
from questorharness.config import load_settings
from questorharness.config.schema import Config
from questorharness.contracts.domain.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from questorharness.contracts.domain.message import (
    ConversationMessage,
    ImageBlock,
    TextBlock,
    sanitize_conversation_messages,
)
from questorharness.contracts.usage import UsageSnapshot
from questorharness.engine.query import MaxTurnsExceeded
from questorharness.platform.io import atomic_write_text
from questorharness.platform.locking import exclusive_file_lock
from questorharness.platform.session_storage import (
    persistable_tool_metadata,
    sanitize_snapshot_payload,
)
from questorharness.providers.auth.manager import AuthManager
from questorharness.providers.llm.client import SupportsStreamingMessages
from questorharness.runtime.session.backend import SessionBackend
from questorharness.surfaces.channels.bus.events import InboundMessage, OutboundMessage
from questorharness.surfaces.channels.bus.queue import MessageBus
from questorharness.surfaces.channels.impl.manager import ChannelManager

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
    "last_user_text",
    "persistable_tool_metadata",
    "resolve_npm",
    "resolve_tsx",
    "sanitize_snapshot_payload",
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

# questor: allow R7 -- until W8 adds the mirror test
