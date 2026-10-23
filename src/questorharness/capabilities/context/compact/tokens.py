"""Token estimation for compaction decisions."""

from __future__ import annotations

import logging
import os

from questorharness.capabilities.context.compact.limits import (
    _DEFAULT_VISION_IMAGE_TOKEN_ESTIMATE,
    TOKEN_ESTIMATION_PADDING,
)
from questorharness.contracts.domain.message import (
    ConversationMessage,
    ImageBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from questorharness.contracts.tokens import estimate_tokens

log = logging.getLogger(__name__)


def estimate_message_tokens(messages: list[ConversationMessage]) -> int:
    """Estimate total tokens for a conversation, including the 4/3 padding."""
    total = 0
    image_token_estimate = _vision_token_budget_per_image()
    for msg in messages:
        for block in msg.content:
            if isinstance(block, TextBlock):
                total += estimate_tokens(block.text)
            elif isinstance(block, ToolResultBlock):
                total += estimate_tokens(block.content)
            elif isinstance(block, ToolUseBlock):
                total += estimate_tokens(block.name)
                total += estimate_tokens(str(block.input))
            elif isinstance(block, ImageBlock):
                total += image_token_estimate
    return int(total * TOKEN_ESTIMATION_PADDING)

def estimate_conversation_tokens(messages: list[ConversationMessage]) -> int:
    """Alias kept for backward compatibility."""
    return estimate_message_tokens(messages)

def _vision_token_budget_per_image() -> int:
    raw = os.environ.get("QUESTORHARNESS_IMAGE_TOKEN_ESTIMATE", "").strip()
    if raw:
        try:
            return max(64, int(raw))
        except ValueError:
            log.warning("Ignoring invalid QUESTORHARNESS_IMAGE_TOKEN_ESTIMATE=%r", raw)
    return _DEFAULT_VISION_IMAGE_TOKEN_ESTIMATE

# questor: allow R7 -- until W8 adds the mirror test
