"""Artifact/output budget contracts。"""

from __future__ import annotations

import pytest

from questor.contracts.artifacts import ArtifactEnvelope, ArtifactRef, OutputBudget


def _ref(total: int = 3) -> ArtifactRef:
    return ArtifactRef(
        artifact_id="sha",
        sha256="a" * 64,
        total_bytes=total,
        kind="stdout",
        media_type="text/plain",
    )


def test_artifact_ref_requires_digest_and_budgets_are_positive() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        ArtifactRef(artifact_id="x", sha256="short", total_bytes=1, kind="stdout", media_type="text/plain")
    with pytest.raises(ValueError, match="positive"):
        OutputBudget(model_result_bytes=0)


def test_artifact_envelope_prevents_unbounded_full_output() -> None:
    envelope = ArtifactEnvelope(
        kind="archived_tool_result",
        artifact=_ref(3),
        preview="abc",
        total_bytes=3,
        truncated=False,
    )
    assert envelope.preview == "abc"
    with pytest.raises(ValueError, match="untruncated"):
        ArtifactEnvelope(
            kind="archived_tool_result",
            artifact=_ref(10),
            preview="abc",
            total_bytes=10,
            truncated=False,
        )
