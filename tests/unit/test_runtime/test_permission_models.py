"""Mirror test for ``runtime/swarm/permission_models.py`` (plan 01, R7).

Scope note: this layer was cut out of the 1163-line ``permission_sync.py`` because it is
the **wire format** between a worker and the team leader, and it has rules of its own that
nothing asserted before: which camelCase keys the TypeScript side is accepted under, which
fields are mandatory, and that a request id is millisecond-based with a 7-character suffix.
The transports (filesystem protocol, mailbox protocol) stayed in ``permission_sync``; this
module touches no filesystem, no asyncio and no mailbox.
"""

from __future__ import annotations

import re
import string
import time

import pytest

from questorharness.runtime.swarm.permission_models import (
    PermissionResolution,
    PermissionResponse,
    SwarmPermissionRequest,
    SwarmPermissionResponse,
    generate_request_id,
    generate_sandbox_request_id,
)

REQUIRED = {
    "id": "perm-1",
    "worker_id": "a1",
    "worker_name": "worker-one",
    "team_name": "team",
    "tool_name": "Bash",
    "tool_use_id": "toolu-1",
    "description": "run a command",
    "input": {"command": "ls"},
}


def make(**overrides) -> SwarmPermissionRequest:
    return SwarmPermissionRequest(**(REQUIRED | overrides))


# --- required shape -------------------------------------------------------


def test_the_eight_wire_fields_are_mandatory() -> None:
    for missing in REQUIRED:
        payload = {key: value for key, value in REQUIRED.items() if key != missing}
        with pytest.raises(TypeError):
            SwarmPermissionRequest(**payload)  # type: ignore[arg-type]


def test_defaults_describe_a_request_that_has_not_been_resolved() -> None:
    before = time.time()
    request = make()

    assert request.status == "pending"
    assert request.resolved_by is None
    assert request.resolved_at is None
    assert request.feedback is None
    assert request.updated_input is None
    assert request.permission_updates is None
    assert request.worker_color is None
    assert request.permission_suggestions == []
    assert before <= request.created_at <= time.time()


def test_two_default_requests_do_not_share_their_mutable_list() -> None:
    first, second = make(), make()

    first.permission_suggestions.append({"rule": "always allow Bash"})
    assert second.permission_suggestions == []


# --- serialisation contract ----------------------------------------------


def test_to_dict_carries_every_field_under_its_snake_case_key() -> None:
    payload = make(permission_suggestions=[{"a": 1}], worker_color="red", status="approved").to_dict()

    assert payload["worker_id"] == "a1"
    assert payload["permission_suggestions"] == [{"a": 1}]
    assert payload["worker_color"] == "red"
    assert payload["status"] == "approved"
    assert set(payload) == {
        "id",
        "worker_id",
        "worker_name",
        "team_name",
        "tool_name",
        "tool_use_id",
        "description",
        "input",
        "permission_suggestions",
        "worker_color",
        "status",
        "resolved_by",
        "resolved_at",
        "feedback",
        "updated_input",
        "permission_updates",
        "created_at",
    }


def test_a_round_trip_through_dict_preserves_the_request() -> None:
    original = make(
        resolved_by="leader",
        resolved_at=1_700_000_000.5,
        feedback="ok",
        updated_input={"command": "ls -la"},
        permission_updates=[{"rule": "x"}],
    )

    assert SwarmPermissionRequest.from_dict(original.to_dict()) == original


def test_the_camel_case_keys_the_typescript_side_writes_are_accepted() -> None:
    request = SwarmPermissionRequest.from_dict(
        {
            "id": "perm-2",
            "workerId": "a2",
            "workerName": "worker-two",
            "teamName": "team-b",
            "toolName": "Edit",
            "toolUseId": "toolu-2",
            "permissionSuggestions": [{"s": 1}],
            "workerColor": "blue",
            "resolvedBy": "worker",
            "resolvedAt": 12.5,
            "updatedInput": {"path": "f"},
            "permissionUpdates": [{"u": 1}],
            "createdAt": 7.5,
        }
    )

    assert request.worker_id == "a2"
    assert request.worker_name == "worker-two"
    assert request.team_name == "team-b"
    assert request.tool_name == "Edit"
    assert request.tool_use_id == "toolu-2"
    assert request.permission_suggestions == [{"s": 1}]
    assert request.worker_color == "blue"
    assert (request.resolved_by, request.resolved_at) == ("worker", 12.5)
    assert (request.updated_input, request.permission_updates) == ({"path": "f"}, [{"u": 1}])
    assert request.created_at == 7.5


def test_snake_case_wins_when_both_spellings_are_present() -> None:
    request = SwarmPermissionRequest.from_dict(
        {"id": "perm-3", "worker_id": "snake", "workerId": "camel", "created_at": 1.0, "createdAt": 2.0}
    )

    assert request.worker_id == "snake"
    assert request.created_at == 1.0


def test_optional_fields_may_be_absent_and_the_timestamp_is_stamped_when_missing() -> None:
    before = time.time()
    request = SwarmPermissionRequest.from_dict({"id": "perm-4"})

    assert request.description == ""
    assert request.input == {}
    assert request.permission_suggestions == []
    assert request.feedback is None
    assert request.created_at >= before


def test_the_id_is_the_only_field_a_sender_must_supply() -> None:
    with pytest.raises(KeyError):
        SwarmPermissionRequest.from_dict({"worker_id": "a1"})


# --- the response side ----------------------------------------------------


def test_a_resolution_records_who_decided_what() -> None:
    strict = PermissionResolution(decision="approved", resolved_by="leader")

    assert strict.feedback is None
    assert strict.updated_input is None
    assert strict.permission_updates is None
    assert PermissionResolution(
        decision="rejected", resolved_by="worker", feedback="no", updated_input={"a": 1}
    ).feedback == "no"


def test_the_legacy_response_keeps_the_denied_spelling_for_older_workers() -> None:
    legacy = PermissionResponse(request_id="perm-5", decision="denied", timestamp="2026-01-01T00:00:00")

    assert legacy.decision == "denied"
    assert legacy.feedback is None
    # The leader-facing type uses a boolean instead of a decision string.
    leader = SwarmPermissionResponse(request_id="perm-5", allowed=True)
    assert leader.updated_rules == []
    assert leader.feedback is None


def test_two_leader_responses_do_not_share_their_rule_list() -> None:
    first, second = SwarmPermissionResponse(request_id="r1", allowed=True), SwarmPermissionResponse(request_id="r2", allowed=True)

    first.updated_rules.append({"rule": "x"})
    assert second.updated_rules == []


def test_the_literal_annotations_are_not_runtime_validated() -> None:
    """Pinned so nobody assumes a bad decision is rejected here.

    Enforcement belongs to the permission checker, not to the wire model.
    """
    assert make(status="maybe").status == "maybe"  # type: ignore[arg-type]


# --- id generation --------------------------------------------------------


def test_a_request_id_carries_a_millisecond_timestamp_and_seven_random_chars() -> None:
    before_ms = int(time.time() * 1000)
    value = generate_request_id()
    after_ms = int(time.time() * 1000)

    prefix, stamp, suffix = value.split("-")
    assert prefix == "perm"
    assert before_ms - 1000 <= int(stamp) <= after_ms + 1000
    assert len(suffix) == 7
    assert set(suffix) <= set(string.ascii_lowercase + string.digits)


def test_a_sandbox_id_uses_the_same_shape_with_its_own_prefix() -> None:
    value = generate_sandbox_request_id()

    assert re.fullmatch(r"sandbox-\d{13,}-[a-z0-9]{7}", value), value


def test_ids_do_not_repeat_within_one_batch() -> None:
    generated = {generate_request_id() for _ in range(200)} | {generate_sandbox_request_id() for _ in range(200)}

    assert len(generated) == 400
