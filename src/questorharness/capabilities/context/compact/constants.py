"""Compaction constants and type aliases."""

from __future__ import annotations

COMPACTABLE_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "bash",
    "grep",
    "glob",
    "web_search",
    "web_fetch",
    "edit_file",
    "write_file",
})

TIME_BASED_MC_CLEARED_MESSAGE = "[Old tool result content cleared]"

AUTOCOMPACT_BUFFER_TOKENS = 13_000

MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000

MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3

COMPACT_TIMEOUT_SECONDS = 25

MAX_COMPACT_STREAMING_RETRIES = 2

MAX_PTL_RETRIES = 3

SESSION_MEMORY_KEEP_RECENT = 12

SESSION_MEMORY_MAX_LINES = 48

SESSION_MEMORY_MAX_CHARS = 4_000

CONTEXT_COLLAPSE_TEXT_CHAR_LIMIT = 2_400

CONTEXT_COLLAPSE_HEAD_CHARS = 900

CONTEXT_COLLAPSE_TAIL_CHARS = 500

MAX_COMPACT_ATTACHMENTS = 6

MAX_DISCOVERED_TOOLS = 12

DEFAULT_KEEP_RECENT = 5

DEFAULT_GAP_THRESHOLD_MINUTES = 60

TOKEN_ESTIMATION_PADDING = 4 / 3

_DEFAULT_VISION_IMAGE_TOKEN_ESTIMATE = 3_072

_DEFAULT_CONTEXT_WINDOW = 200_000

PTL_RETRY_MARKER = "[earlier conversation truncated for compaction retry]"

ERROR_MESSAGE_INCOMPLETE_RESPONSE = "Compaction interrupted before a complete summary was returned."

NO_TOOLS_PREAMBLE = """\
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use read_file, bash, grep, glob, edit_file, write_file, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

"""

BASE_COMPACT_PROMPT = """\
Your task is to create a detailed summary of the conversation so far. This summary will replace the earlier messages, so it must capture all important information.

First, draft your analysis inside <analysis> tags. Walk through the conversation chronologically and extract:
- Every user request and intent (explicit and implicit)
- The approach taken and technical decisions made
- Specific code, files, and configurations discussed (with paths and line numbers where available)
- All errors encountered and how they were fixed
- Any user feedback or corrections

Then, produce a structured summary inside <summary> tags with these sections:

1. **Primary Request and Intent**: All user requests in full detail, including nuances and constraints.
2. **Key Technical Concepts**: Technologies, frameworks, patterns, and conventions discussed.
3. **Files and Code Sections**: Every file examined or modified, with specific code snippets and line numbers.
4. **Errors and Fixes**: Every error encountered, its cause, and how it was resolved.
5. **Problem Solving**: Problems solved and approaches that worked vs. didn't work.
6. **All User Messages**: Non-tool-result user messages (preserve exact wording for context).
7. **Pending Tasks**: Explicitly requested work that hasn't been completed yet.
8. **Current Work**: Detailed description of the last task being worked on before compaction.
9. **Optional Next Step**: The single most logical next step, directly aligned with the user's recent request.
"""

NO_TOOLS_TRAILER = """
REMINDER: Do NOT call any tools. Respond with plain text only — an <analysis> block followed by a <summary> block. Tool calls will be rejected and you will fail the task."""
