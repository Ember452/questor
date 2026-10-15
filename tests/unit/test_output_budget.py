"""P2 output budget 与 artifact envelope（ADR-0019）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.capabilities.tools._output import envelope_for_text, preview_bytes
from questor.contracts.artifacts import OutputBudget
from questor.providers.artifact_store import FileSystemArtifactStore


async def test_large_output_is_replaced_by_artifact_envelope(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "artifacts")
    await store.connect()
    text = "x" * 20000
    envelope, ref, truncated = await envelope_for_text(
        text,
        store=store,
        run_id="run",
        tool_call_id="tool",
        budget=OutputBudget(model_result_bytes=1000),
    )
    assert truncated is True
    assert ref is not None
    assert envelope is not None
    assert len(envelope["preview"].encode("utf-8")) <= 1000
    assert (tmp_path / "artifacts" / f"{ref.sha256}.txt").read_text(encoding="utf-8") == text
    await store.close()


def test_preview_bytes_respects_utf8_boundary() -> None:
    text = "é" * 10
    preview = preview_bytes(text, 1)
    assert len(preview.encode("utf-8")) <= 1
    assert preview == ""


async def test_artifact_write_failure_does_not_return_full_text(tmp_path: Path) -> None:
    class _BrokenStore:
        async def put_text(self, content: str, *, run_id: str, kind: str, media_type: str = "text/plain"):
            del content, run_id, kind, media_type
            raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        await envelope_for_text(
            "x" * 5000,
            store=_BrokenStore(),
            run_id="run",
            tool_call_id="tool",
            budget=OutputBudget(model_result_bytes=100),
        )
