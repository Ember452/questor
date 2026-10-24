"""Mirror test for ``capabilities/context/compact/attachments.py`` (plan 01, R7).

Scope note: none of this module's nine public names appeared anywhere under ``tests/``
before this file. That matters more than it looks: an attachment is what survives a
compaction boundary, so a regression here does not crash -- it silently drops the
user's goal, the verified state or the last read files from the model's context. The
truncation windows (4 files, 3 goals, 5 artifacts, 4 verified items, 8 log entries) are
pinned exactly because they are invisible until something is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.capabilities.context.compact.attachments import (
    CompactAttachment,
    _build_compact_attachments,
    _create_attachment,
    _extract_attachment_paths,
    _extract_discovered_tools,
    _replace_images_with_compaction_placeholders,
    _sanitize_metadata,
    create_async_agent_attachment_if_needed,
    create_invoked_skills_attachment_if_needed,
    create_plan_attachment_if_needed,
    create_recent_files_attachment_if_needed,
    create_recent_verified_work_attachment_if_needed,
    create_task_focus_attachment_if_needed,
    create_work_log_attachment_if_needed,
    render_compact_attachment,
)
from questorharness.capabilities.context.compact.limits import (
    MAX_COMPACT_ATTACHMENTS,
    MAX_DISCOVERED_TOOLS,
)
from questorharness.contracts.domain.message import (
    ConversationMessage,
    ImageBlock,
    TextBlock,
    ToolUseBlock,
)


def user(text: str) -> ConversationMessage:
    return ConversationMessage.from_user_text(text)


def image(source_path: str = "") -> ImageBlock:
    return ImageBlock(media_type="image/png", data="base64blob", source_path=source_path)


# --- the container --------------------------------------------------------


def test_an_attachment_is_a_title_and_a_body_of_dropped_blanks() -> None:
    attachment = _create_attachment("kind", "Title", ["  ", "first  ", "", "second", "   "])

    assert isinstance(attachment, CompactAttachment)
    assert (attachment.kind, attachment.title) == ("kind", "Title")
    assert attachment.body == "first\nsecond"
    assert attachment.metadata == {}


def test_nothing_to_say_means_no_attachment() -> None:
    assert _create_attachment("kind", "Title", []) is None
    assert _create_attachment("kind", "Title", ["", "   ", "\t"]) is None


def test_rendering_wraps_the_attachment_in_one_user_message() -> None:
    message = render_compact_attachment(CompactAttachment(kind="plan", title="Plan mode context", body="keep going"))

    assert message.role == "user"
    assert len(message.content) == 1
    text = message.content[0].text
    assert text.startswith("[Compact attachment: plan] Plan mode context\n")
    assert text.endswith("keep going")


def test_a_titleless_kind_still_renders_without_a_stray_bracket() -> None:
    text = render_compact_attachment(CompactAttachment(kind="k", title="", body="b")).content[0].text

    assert text == "[Compact attachment: k]\nb"


# --- metadata sanitising -------------------------------------------------


def test_metadata_survives_paths_sets_and_odd_objects() -> None:
    class _Odd:
        def __str__(self) -> str:
            return "odd-rendered"

    cleaned = _sanitize_metadata(
        {
            Path("key"): "value",
            "nested": {"count": 2, "flag": False, "nothing": None},
            "paths": [Path("dir", "a.txt"), "/tmp/b"],
            "unique": {"only"},
            "odd": _Odd(),
        }
    )

    assert cleaned["key"] == "value"
    assert cleaned["nested"] == {"count": 2, "flag": False, "nothing": None}
    # A Path becomes its native string form, so this is the platform the test runs on.
    assert cleaned["paths"] == [str(Path("dir", "a.txt")), "/tmp/b"]
    assert cleaned["unique"] == ["only"]
    assert cleaned["odd"] == "odd-rendered"
    assert all(isinstance(key, str) for key in cleaned)


# --- what is extracted from the transcript -------------------------------


def test_attachment_paths_come_from_images_and_from_both_text_shapes() -> None:
    messages = [
        ConversationMessage(role="user", content=[image("/tmp/photo.png"), TextBlock(text="see path: /tmp/a.py")]),
        user("[attachment: /tmp/b.pdf] and [attachment: download failed: /tmp/c.pdf]"),
        ConversationMessage(role="user", content=[image("/tmp/photo.png")]),  # duplicate
    ]

    found = _extract_attachment_paths(messages)

    # Image paths are normalised through Path (so they carry the native separator) while
    # paths lifted out of message text are kept verbatim. The asymmetry is asserted, not
    # smoothed over: a consumer that compares the two must normalise first.
    assert found[0] == str(Path("/tmp/photo.png"))
    assert found[1:] == ["/tmp/a.py", "/tmp/b.pdf"]
    assert all("download failed" not in path for path in found)


def test_attachment_paths_stop_at_the_declared_cap() -> None:
    many = [user(f"path: /tmp/{index}.py") for index in range(MAX_COMPACT_ATTACHMENTS + 5)]

    found = _extract_attachment_paths(many)

    assert len(found) == MAX_COMPACT_ATTACHMENTS
    assert found == [f"/tmp/{index}.py" for index in range(MAX_COMPACT_ATTACHMENTS)]


def test_discovered_tools_are_unique_and_capped() -> None:
    def with_tools(names: list[str]) -> ConversationMessage:
        return ConversationMessage(role="assistant", content=[ToolUseBlock(name=name, id=f"t-{i}") for i, name in enumerate(names)])

    messages = [with_tools(["read", "write", "read"]), with_tools(["bash"])]

    assert _extract_discovered_tools(messages) == ["read", "write", "bash"]

    overflow = _extract_discovered_tools([with_tools([f"tool{index}" for index in range(MAX_DISCOVERED_TOOLS + 4)])])
    assert len(overflow) == MAX_DISCOVERED_TOOLS
    assert overflow[0] == "tool0"


def test_images_become_text_placeholders_and_nothing_else_changes() -> None:
    plain = user("no images here")
    with_image = ConversationMessage(
        role="user",
        content=[TextBlock(text="before"), image("/tmp/shot.png"), image()],
    )

    first, second = _replace_images_with_compaction_placeholders([plain, with_image])

    # A message without images is returned as the same object, not a copy.
    assert first is plain
    assert [type(block).__name__ for block in second.content] == ["TextBlock", "TextBlock", "TextBlock"]
    assert second.content[1].text.startswith("[Image omitted from compaction summarization; source: /tmp/shot.png.]")
    assert "source: inline" in second.content[2].text
    assert second.role == "user"


# --- task focus: what survives is a decision -----------------------------


def test_task_focus_needs_something_worth_saving() -> None:
    assert create_task_focus_attachment_if_needed({}) is None
    assert create_task_focus_attachment_if_needed({"task_focus_state": "not a dict"}) is None
    assert create_task_focus_attachment_if_needed({"task_focus_state": {"goal": "   ", "recent_goals": ["  "]}}) is None


def test_task_focus_keeps_the_recent_tail_of_each_list() -> None:
    attachment = create_task_focus_attachment_if_needed(
        {
            "task_focus_state": {
                "goal": "ship the compaction guard",
                "recent_goals": [f"g{index}" for index in range(6)],
                "active_artifacts": [f"a{index}" for index in range(8)],
                "verified_state": [f"v{index}" for index in range(7)],
                "next_step": "run the suite",
            }
        }
    )

    assert attachment is not None
    assert attachment.metadata["recent_goals"] == ["g3", "g4", "g5"]
    assert attachment.metadata["active_artifacts"] == ["a3", "a4", "a5", "a6", "a7"]
    assert attachment.metadata["verified_state"] == ["v3", "v4", "v5", "v6"]

    body = attachment.body
    assert "- Goal: ship the compaction guard" in body
    assert "- Recent user goals that still matter:" in body
    assert "  - g3" in body and "  - g0" not in body
    assert "- Suggested next step: run the suite" in body


def test_task_focus_renders_only_the_sections_that_have_content() -> None:
    attachment = create_task_focus_attachment_if_needed({"task_focus_state": {"next_step": "just a next step"}})

    assert attachment is not None
    assert attachment.body == "Current working focus to preserve across compaction:\n- Suggested next step: just a next step"
    assert attachment.metadata["goal"] == ""


# --- recent files --------------------------------------------------------


def test_recent_files_needs_a_list() -> None:
    assert create_recent_files_attachment_if_needed(None) is None
    assert create_recent_files_attachment_if_needed("not a list") is None
    assert create_recent_files_attachment_if_needed([]) is None
    # A list with no usable entry must not produce an attachment: every sibling
    # factory in this module returns None once its entries are empty.
    assert create_recent_files_attachment_if_needed([{'path': '  '}, 'junk']) is None


def test_recent_files_are_newest_first_and_limited_to_four() -> None:
    attachment = create_recent_files_attachment_if_needed(
        [
            {"path": "/old.py", "timestamp": 1.0},
            {"path": "/mid.py", "timestamp": 5.0, "span": "10-20", "preview": "def mid(): ..."},
            {"path": "/new.py", "timestamp": 9.0},
            {"path": "/a4.py", "timestamp": 4.0},
            {"path": "/a5.py", "timestamp": 3.0},
            {"path": "/a6.py", "timestamp": 2.0},
        ]
    )

    assert attachment is not None
    # Newest first, then cut at four: a6 (ts 2.0) and old (ts 1.0) both fall off.
    assert [entry["path"] for entry in attachment.metadata["entries"]] == [
        "/new.py",
        "/mid.py",
        "/a4.py",
        "/a5.py",
    ]
    assert "/new.py" in attachment.body
    assert "/a6.py" not in attachment.body
    assert "/old.py" not in attachment.body
    assert "  Preview: def mid(): ..." in attachment.body
    assert "- /mid.py (10-20)" in attachment.body


def test_a_file_without_a_timestamp_sorts_oldest() -> None:
    attachment = create_recent_files_attachment_if_needed([{"path": "/no-ts.py"}, {"path": "/ts.py", "timestamp": 0.5}])

    assert [entry["path"] for entry in attachment.metadata["entries"]] == ["/ts.py", "/no-ts.py"]


# --- the remaining factories --------------------------------------------


@pytest.mark.parametrize("bad", [None, "", 7, {}, "string"])
def test_list_shaped_inputs_refuse_anything_that_is_not_a_list(bad) -> None:
    for factory in (
        create_recent_verified_work_attachment_if_needed,
        create_invoked_skills_attachment_if_needed,
        create_async_agent_attachment_if_needed,
        create_work_log_attachment_if_needed,
    ):
        assert factory(bad) is None


def test_verified_work_keeps_the_last_eight_entries() -> None:
    attachment = create_recent_verified_work_attachment_if_needed([f"v{index}" for index in range(11)])

    assert attachment is not None
    assert attachment.kind == "recent_verified_work"
    assert attachment.metadata["entries"] == [f"v{index}" for index in range(3, 11)]
    assert "- v10" in attachment.body and "- v0" not in attachment.body


def test_invoked_skills_are_one_comma_separated_line() -> None:
    attachment = create_invoked_skills_attachment_if_needed(["review", "  ", "release"])

    assert attachment is not None
    assert "- review, release" in attachment.body
    assert attachment.metadata == {"skills": ["review", "release"]}


def test_async_agents_keep_the_last_six() -> None:
    attachment = create_async_agent_attachment_if_needed([f"task{index}" for index in range(9)])

    assert attachment is not None
    assert attachment.metadata["entries"] == [f"task{index}" for index in range(3, 9)]


def test_work_log_keeps_the_last_eight() -> None:
    attachment = create_work_log_attachment_if_needed([f"log{index}" for index in range(10)])

    assert attachment is not None
    assert attachment.title == "Recent execution checkpoints"
    assert attachment.metadata["entries"] == [f"log{index}" for index in range(2, 10)]


def test_plan_context_survives_only_in_plan_mode() -> None:
    assert create_plan_attachment_if_needed({}) is None
    assert create_plan_attachment_if_needed({"permission_mode": "acceptEdits"}) is None

    attachment = create_plan_attachment_if_needed({"permission_mode": " PLAN ", "plan_summary": " two steps "})

    assert attachment is not None
    assert attachment.metadata == {"permission_mode": "plan", "plan_summary": "two steps"}
    assert "Plan mode is still active for this session." in attachment.body
    assert "Do not execute mutating tools until the user explicitly exits plan mode." in attachment.body
    assert "Current plan summary: two steps" in attachment.body


def test_plan_context_without_a_summary_still_forbids_mutation() -> None:
    attachment = create_plan_attachment_if_needed({"permission_mode": "plan"})

    assert "Current plan summary" not in attachment.body
    assert "Do not execute mutating tools" in attachment.body


# --- the assembled list --------------------------------------------------


def test_the_builder_order_is_the_priority_order() -> None:
    metadata = {
        "task_focus_state": {"goal": "keep this first"},
        "recent_verified_work": ["verified"],
        "read_file_state": [{"path": "/x.py", "timestamp": 1.0}],
        "permission_mode": "plan",
        "invoked_skills": ["review"],
        "async_agent_state": ["task"],
        "recent_work_log": ["log"],
    }
    messages = [user("path: /attach.py")]

    attachments = _build_compact_attachments(messages, metadata=metadata)

    assert [attachment.kind for attachment in attachments] == [
        "task_focus",
        "recent_verified_work",
        "recent_attachments",
        "recent_files",
        "plan",
        "invoked_skills",
        "async_agents",
        "recent_work_log",
    ]


def test_an_empty_session_produces_no_attachments() -> None:
    assert _build_compact_attachments([], metadata=None) == []
    assert _build_compact_attachments([user("plain words")], metadata={}) == []
