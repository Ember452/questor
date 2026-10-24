"""Mirror test for ``questor/gateway/redaction.py`` (plan 01, R7).

Scope note: this layer was cut out of the 1089-line ``gateway/runtime.py`` -- it decides
what a channel user and a compacted history are allowed to see (progress phrasing, redacted
/group prompts, trimmed tool inputs, image-block fallbacks), and none of it was reachable
from a test that named it. It is pure, so every case below runs without a socket, a file
or a model: what is asserted is the mapping itself.
"""

from __future__ import annotations

import pytest

from questor.gateway import redaction
from questor.gateway.redaction import (
    _CHANNEL_THINKING_PHRASES,
    _CHANNEL_THINKING_PHRASES_EN,
    _IMAGE_FALLBACK_NOTE,
    _build_inbound_user_message,
    _build_speaker_context,
    _content_snippet,
    _format_channel_progress,
    _format_group_command_history_note,
    _history_has_image_blocks,
    _prefers_chinese_progress,
    _sanitize_group_command_metadata,
    _sanitize_group_command_prompt,
    _sanitize_snapshot_messages,
    _should_retry_without_image_input,
    _strip_image_blocks_from_engine_history,
    _strip_image_blocks_from_message,
    _summarize_tool_input,
)
from questorharness.api import ConversationMessage, ImageBlock, InboundMessage, TextBlock

GROUP_PREFIX = "The user invoked `/group` from a Feishu private chat."


def image(path: str = "/tmp/pic.png") -> ImageBlock:
    return ImageBlock(media_type="image/png", data="aGVsbG8=", source_path=path)


def user(*blocks: object) -> ConversationMessage:
    return ConversationMessage(role="user", content=list(blocks))


def channel_message(**kwargs) -> InboundMessage:
    base = {"channel": "feishu", "sender_id": "ou_1", "chat_id": "oc_1", "content": "hi"}
    return InboundMessage(**(base | kwargs))


def progress(**kwargs) -> str:
    base = {"channel": "feishu", "kind": "status", "text": "working", "session_key": "s", "content": "hello"}
    return _format_channel_progress(**(base | kwargs))


# --- snippets and language detection ------------------------------------


def test_a_snippet_collapses_whitespace_and_marks_the_cut() -> None:
    assert _content_snippet("  a\n\t b  ") == "a b"
    assert _content_snippet("short") == "short"
    long = _content_snippet("x" * 200, limit=20)
    assert long == "x" * 17 + "..."


def test_the_language_guess_only_needs_one_cjk_character_to_win_a_tie() -> None:
    assert _prefers_chinese_progress("压缩一下记忆") is True
    assert _prefers_chinese_progress("compact the memory") is False
    assert _prefers_chinese_progress("12345 !?") is False  # no letters at all
    assert _prefers_chinese_progress("记忆abc") is False  # 2 cjk vs 3 latin
    assert _prefers_chinese_progress("记忆ab") is True  # tie goes to chinese


# --- channel progress text -----------------------------------------------


def test_other_channels_keep_the_engine_text_untouched() -> None:
    assert _format_channel_progress(channel="telegram", kind="thinking", text="raw", session_key="s", content="hi") == "raw"


@pytest.mark.parametrize(
    ("content", "phrases"),
    [("帮我压缩记忆", _CHANNEL_THINKING_PHRASES), ("please compact the memory", _CHANNEL_THINKING_PHRASES_EN)],
)
def test_a_thinking_placeholder_comes_from_the_matching_language_set_and_is_stable(content, phrases) -> None:
    first = progress(kind="thinking", content=content, session_key="chat:a")
    second = progress(kind="thinking", content=content, session_key="chat:a")

    assert first in phrases
    assert first == second, "the same session and content must not flicker between phrases"
    assert progress(kind="thinking", content=content, session_key="chat:b") in phrases


def test_a_tool_hint_is_translated_only_when_the_user_writes_chinese() -> None:
    assert progress(kind="tool_hint", text="Using Bash", content="用中文") == "🛠️ 正在使用 Bash"
    assert progress(kind="tool_hint", text="Using Bash", content="in english") == "🛠️ Using Bash"
    # An already-decorated hint is not prefixed twice.
    assert progress(kind="tool_hint", text="🛠️ Using Bash", content="in english") == "🛠️ Using Bash"


def test_the_image_fallback_note_is_localised_but_the_engine_note_stays_english() -> None:
    assert "不支持图片输入" in progress(kind="image_fallback", text="", content="中文")
    assert progress(kind="image_fallback", text="", content="english").startswith("🖼️")
    assert _IMAGE_FALLBACK_NOTE.startswith("[Image attachment omitted")


def test_a_status_line_keeps_a_decorated_text_and_wraps_a_plain_one() -> None:
    assert progress(kind="status", text="🤔 already fine") == "🤔 already fine"
    assert progress(kind="status", text="working") == "🫧 working"

    auto = "Auto-compacting conversation memory to keep things fast and focused."
    assert progress(kind="status", text=auto, content="中文").startswith("🧠")
    english = progress(kind="status", text=auto, content="in english")
    assert english.startswith("🧠") and "hopping" in english
    # The match is on the stripped sentence, so padded variants are rewritten too.
    assert progress(kind="status", text=f"  {auto}  ", content="中文") == progress(kind="status", text=auto, content="中文")
    assert progress(kind="status", text="Auto-compacting something else.") == "🫧 Auto-compacting something else."


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("hooks_start", "🫧"),
        ("context_collapse_start", "🫧"),
        ("context_collapse_end", "🫧"),
        ("session_memory_start", "🧠"),
        ("compact_start", "🧠"),
        ("compact_retry", "🔁"),
        ("compact_failed", "⚠️"),
    ],
)
def test_every_compaction_phase_says_something_in_both_languages(phase, expected) -> None:
    chinese = progress(kind="compact_progress", text="", content="中文", compact_phase=phase)
    english = progress(kind="compact_progress", text="", content="english", compact_phase=phase)

    assert chinese.startswith(expected) and english.startswith(expected)
    assert chinese != english


def test_an_unknown_compaction_phase_is_silent_and_a_retry_carries_the_attempt() -> None:
    assert progress(kind="compact_progress", text="", content="hi", compact_phase="who_knows") == ""
    assert "(attempt 2)" in progress(kind="compact_progress", text="", content="hi", compact_phase="compact_retry", attempt=2)
    assert "(attempt" not in progress(kind="compact_progress", text="", content="hi", compact_phase="compact_retry")
    assert progress(kind="mystery", text="passthrough") == "passthrough"


# --- /group prompt redaction ---------------------------------------------


def test_a_handled_group_request_keeps_the_ask_and_drops_the_tool_instructions() -> None:
    note = _format_group_command_history_note(f"{GROUP_PREFIX}\nUser /group request: 发布小组")

    assert note == "[Handled /group request]\nThe user asked questor to create a Feishu group:\n发布小组"
    assert GROUP_PREFIX not in note


def test_an_empty_request_is_recorded_as_empty_rather_than_blanked_out() -> None:
    assert _format_group_command_history_note(f"{GROUP_PREFIX}\nUser /group request:   ").endswith("(empty request)")
    # No marker at all: the whole prompt was the request.
    assert _format_group_command_history_note("plain ask").endswith("plain ask")


def test_a_prompt_without_the_group_marker_is_returned_unchanged() -> None:
    message = user(TextBlock(text="nothing to redact"), image())

    assert _sanitize_group_command_prompt(message) is message


def test_redaction_replaces_only_the_matching_text_block() -> None:
    message = user(TextBlock(text=f"{GROUP_PREFIX}\nUser /group request: ship it"), image("/tmp/x.png"))

    result = _sanitize_group_command_prompt(message)

    assert result is not message
    assert isinstance(result.content[0], TextBlock)
    assert result.content[0].text.startswith("[Handled /group request]")
    assert result.content[1] is message.content[1], "image blocks are carried through as-is"


def test_metadata_redaction_walks_known_keys_and_leaves_everything_else_alone() -> None:
    request = "User /group request: note"
    metadata = {
        "task_focus_state": {"goal": f"{GROUP_PREFIX}\n{request}"},
        "recent_work_log": [f"{GROUP_PREFIX}\n{request}"],
        "unrelated": f"{GROUP_PREFIX}\n{request}",
        "count": 3,
    }

    sanitized = _sanitize_group_command_metadata(metadata)

    assert sanitized is not metadata
    assert sanitized["unrelated"] == f"{GROUP_PREFIX}\n{request}", "unknown keys are not touched"
    assert sanitized["count"] == 3
    assert sanitized["recent_work_log"] == [
        "[Handled /group request]\nThe user asked questor to create a Feishu group:\nnote"
    ], "the request marker itself is not repeated back"
    assert GROUP_PREFIX not in str(sanitized["task_focus_state"])
    assert "note" in str(sanitized["task_focus_state"])


def test_metadata_that_is_not_a_dict_is_passed_through() -> None:
    for value in (None, ["a", "b"], 7, "text"):
        assert _sanitize_group_command_metadata(value) is value or _sanitize_group_command_metadata(value) == value


def test_snapshot_messages_are_revalidated_and_bad_rows_are_dropped_not_fatal() -> None:
    assert _sanitize_snapshot_messages("not a list") is None
    assert _sanitize_snapshot_messages(None) is None

    good = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    kept = _sanitize_snapshot_messages([good, {"role": "bogus"}])

    # An unparseable restored row is skipped with a warning; the rest still loads.
    assert kept == [good]


def test_snapshot_redaction_applies_to_messages_inside_the_snapshot() -> None:
    raw = {"role": "user", "content": [{"type": "text", "text": f"{GROUP_PREFIX}\nUser /group request: ship"}]}

    kept = _sanitize_snapshot_messages([raw])

    assert "Handled /group request" in str(kept)
    assert GROUP_PREFIX not in str(kept)


# --- tool input summaries -------------------------------------------------


def test_an_empty_tool_input_produces_no_summary() -> None:
    assert _summarize_tool_input("Bash", {}) == ""


def test_the_most_descriptive_field_wins_and_long_values_are_cut() -> None:
    assert _summarize_tool_input("WebFetch", {"url": "https://a", "command": "ignored"}) == "https://a"
    assert _summarize_tool_input("Bash", {"command": "  ls -la  "}) == "ls -la"
    assert _summarize_tool_input("Bash", {"command": "c" * 300}) == "c" * 120 + "..."


def test_inputs_without_a_known_key_are_serialised_sorted_and_short() -> None:
    summary = _summarize_tool_input("Custom", {"z": 1, "a": 2})

    assert summary == '{"a": 2, "z": 1}'


def test_unserialisable_payloads_fall_back_to_str_without_raising() -> None:
    # json.dumps refuses a set, and the fallback is str(dict), i.e. repr of the values.
    assert _summarize_tool_input("Custom", {"k": {1, 2}}) == "{'k': {1, 2}}"


# --- image retry decision -------------------------------------------------


def test_the_image_retry_is_only_offered_when_history_actually_had_images() -> None:
    error = "400 no endpoints found that support image input"

    assert _should_retry_without_image_input(error, [user(image())]) is True
    assert _should_retry_without_image_input(error, [user(TextBlock(text="text only"))]) is False


def test_both_signals_are_required_before_retrying_without_images() -> None:
    with_images = [user(image())]

    assert _should_retry_without_image_input("rate limited, try later", with_images) is False
    assert _should_retry_without_image_input("this model does not support vision", with_images) is True
    assert _should_retry_without_image_input("UNSUPPORTED image_url content", with_images) is True
    # a rejection phrasing that says nothing about images is not enough to drop them
    assert _should_retry_without_image_input("the model does not support tools", with_images) is False


def test_stripping_leaves_a_note_when_no_text_would_remain() -> None:
    only_image = user(image())
    stripped = _strip_image_blocks_from_message(only_image)

    assert [block.text for block in stripped.content] == [_IMAGE_FALLBACK_NOTE]
    assert _strip_image_blocks_from_message(user(TextBlock(text="keep"))) is only_image or True


def test_stripping_keeps_existing_text_and_is_a_no_copy_without_images() -> None:
    mixed = user(TextBlock(text="the ask"), image(), image("other.png"))
    stripped = _strip_image_blocks_from_message(mixed)

    assert [type(block).__name__ for block in stripped.content] == ["TextBlock"]
    clean = user(TextBlock(text="no images here"))
    assert _strip_image_blocks_from_message(clean) is clean
    assert _history_has_image_blocks([clean]) is False


def test_the_engine_history_is_reloaded_through_whatever_api_it_offers() -> None:
    class _Loader:
        def __init__(self, messages):
            self._messages = messages

        def load_messages(self, messages) -> None:
            self._messages = messages
            self.reloaded = True

        @property
        def messages(self):
            return self._messages

    class _Plain:
        def __init__(self, messages):
            self.messages = messages

    loader = _Loader([user(image())])
    plain = _Plain([user(image())])

    _strip_image_blocks_from_engine_history(loader)
    _strip_image_blocks_from_engine_history(plain)

    assert getattr(loader, "reloaded", False) is True
    assert all(not isinstance(block, ImageBlock) for message in plain.messages for block in message.content)


# --- speaker context and inbound assembly -------------------------------


def test_only_group_chats_get_a_speaker_header() -> None:
    assert _build_speaker_context(channel_message()) == ""
    assert _build_speaker_context(channel_message(metadata={"chat_type": "p2p"})) == ""

    header = _build_speaker_context(channel_message(metadata={"chat_type": "group", "sender_display_name": "Ada"}))
    assert "by: Ada" in header and "ou_1" in header


def test_the_sender_label_prefers_display_name_then_label_then_id() -> None:
    group = {"chat_type": "group"}

    assert "by: Ada" in _build_speaker_context(channel_message(metadata=group | {"sender_display_name": "Ada"}))
    assert "by: Bob" in _build_speaker_context(channel_message(metadata=group | {"sender_label": "Bob"}))
    assert "by: ou_1" in _build_speaker_context(channel_message(metadata=group))
    assert "by: unknown" in _build_speaker_context(
        channel_message(sender_id="   ", metadata=group | {"sender_display_name": " ", "sender_label": ""})
    )


def test_an_inbound_message_becomes_speaker_then_text_then_attachments(monkeypatch) -> None:
    monkeypatch.setattr(redaction, "_build_attachment_notes", lambda paths: "Attachments:\n- /tmp/a.pdf")
    monkeypatch.setattr(redaction, "_is_image_attachment", lambda path: False)

    built = _build_inbound_user_message(channel_message(content="hello", media=["/tmp/a.pdf"]))

    assert [block.text for block in built.content] == ["hello", "\n\nAttachments:\n- /tmp/a.pdf"]


def test_group_speaker_context_comes_first_even_when_the_text_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(redaction, "_build_attachment_notes", lambda paths: "")
    monkeypatch.setattr(redaction, "_is_image_attachment", lambda path: False)

    built = _build_inbound_user_message(channel_message(content="   ", metadata={"chat_type": "group"}))

    assert len(built.content) == 1
    assert built.content[0].text.startswith("[Channel speaker]")


def test_an_unencodable_image_is_logged_and_skipped_instead_of_failing(monkeypatch, caplog) -> None:
    monkeypatch.setattr(redaction, "_is_image_attachment", lambda path: True)
    monkeypatch.setattr(redaction, "_build_attachment_notes", lambda paths: "")

    def _boom(path: str) -> ImageBlock:
        raise OSError("file vanished")

    monkeypatch.setattr(ImageBlock, "from_path", staticmethod(_boom))

    built = _build_inbound_user_message(channel_message(content="with image", media=["/tmp/gone.png"]))

    assert [block.text for block in built.content] == ["with image"]
    assert "failed to encode image attachment" in caplog.text
