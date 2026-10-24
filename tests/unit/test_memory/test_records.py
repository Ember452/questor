"""Mirror test for ``capabilities/memory/extract/records.py`` (plan 01, R7)."""

from __future__ import annotations

from questorharness.capabilities.memory.extract.records import (
    ExtractionRecord,
    ExtractionResult,
    _extract_json_object,
    parse_extraction_records,
)
from questorharness.capabilities.memory.schema import DEFAULT_MEMORY_SCOPE, DEFAULT_MEMORY_TYPE

PAYLOAD = (
    '{"memories":['
    '{"title":"User Role","type":"user","scope":"private","description":"who they are",'
    '"body":"User knows Go.","tags":["profile"," "]},'
    '{"title":"Plain Note","type":"feedback","body":"Use real database tests."}'
    "]}"
)


def test_parse_reads_declared_fields() -> None:
    records = parse_extraction_records(PAYLOAD, max_records=5)

    assert len(records) == 2
    first, second = records
    assert first.title == "User Role"
    assert first.memory_type == "user"
    assert first.scope == "private"
    assert first.description == "who they are"
    assert first.body == "User knows Go."
    # Blank tags are dropped rather than kept as empty strings.
    assert first.tags == ("profile",)
    # A declared type wins; a missing scope falls back to the schema default.
    assert second.memory_type == "feedback"
    assert second.scope == DEFAULT_MEMORY_SCOPE
    assert second.tags == ()


def test_parse_infers_nothing_about_undeclared_fields() -> None:
    # Undeclared type/scope take the schema defaults and are never guessed from
    # the title or body, even when the title reads like a known type.
    undeclared = parse_extraction_records('{"memories":[{"title":"Feedback","body":"b"}]}')

    assert undeclared[0].memory_type == DEFAULT_MEMORY_TYPE
    assert undeclared[0].scope == DEFAULT_MEMORY_SCOPE


def test_parse_accepts_json_wrapped_in_prose() -> None:
    wrapped = f"Here you go:\n{PAYLOAD}\nHope that helps."
    assert len(parse_extraction_records(wrapped, max_records=5)) == 2


def test_parse_rejects_unusable_output() -> None:
    assert parse_extraction_records("no json here") == ()
    assert parse_extraction_records('{"memories": "not a list"}') == ()
    assert parse_extraction_records('{"other": []}') == ()
    # A record without title or body is dropped, not stored half-empty.
    assert parse_extraction_records('{"memories":[{"title":"only title"}]}') == ()
    assert parse_extraction_records('{"memories":[{"body":"only body"}]}') == ()


def test_parse_respects_max_records() -> None:
    many = '{"memories":[' + ",".join(
        f'{{"title":"t{index}","body":"b{index}"}}' for index in range(5)
    ) + "]}"

    assert [record.title for record in parse_extraction_records(many, max_records=2)] == ["t0", "t1"]


def test_json_object_extractor_handles_bare_and_plain_text() -> None:
    assert _extract_json_object('{"a": 1}') == '{"a": 1}'
    assert _extract_json_object('prefix {"a": 1} suffix') == '{"a": 1}'
    assert _extract_json_object("plain text") == "plain text"


def test_result_dataclasses_are_frozen_and_default_empty() -> None:
    result = ExtractionResult(skipped=True)

    assert (result.reason, result.records, result.written_paths) == ("", (), ())
    record = ExtractionRecord(title="t", body="b")
    assert record.memory_type == DEFAULT_MEMORY_TYPE and record.tags == ()
