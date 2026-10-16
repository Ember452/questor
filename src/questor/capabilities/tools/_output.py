"""L3 工具输出预算 helper（ADR-0019；HARD C13/C18）。

超预算内容只以有界 preview + artifact ref 返回。store 写失败会向上抛出，由调用者构造
有界 error ToolResult；绝不能把原文 fallback 回 prompt/event/checkpoint。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from questor.contracts.artifacts import ArtifactRef, OutputBudget


class TextArtifactStore(Protocol):
    """helper 只需要文本 artifact 写入能力。"""

    async def put_text(
        self,
        content: str,
        *,
        run_id: str,
        kind: str,
        media_type: str = "text/plain",
    ) -> ArtifactRef: ...


def preview_bytes(text: str, limit: int) -> str:
    """返回不超过 ``limit`` UTF-8 bytes 的合法前缀。"""
    if limit <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    try:
        return encoded[:limit].decode("utf-8", errors="ignore")
    except UnicodeDecodeError:  # pragma: no cover - errors="ignore" 已兜底
        return ""


async def envelope_for_text(
    text: str,
    *,
    store: TextArtifactStore,
    run_id: str,
    tool_call_id: str,
    budget: OutputBudget,
    kind: str = "stdout",
) -> tuple[dict[str, object] | None, ArtifactRef | None, bool]:
    """若文本超预算则落 artifact；small result 返回 ``(None, None, False)``。"""
    encoded_length = len(text.encode("utf-8"))
    if encoded_length <= budget.model_result_bytes:
        return None, None, False
    ref = await store.put_text(text, run_id=run_id, kind=kind)
    preview = preview_bytes(text, budget.model_result_bytes)
    ref_dict = asdict(ref)
    ref_dict["created_at"] = ref.created_at.isoformat()
    envelope = {
        "kind": "archived_tool_result",
        "artifact_ref": ref_dict,
        "content_sha256": ref.sha256,
        "total_bytes": ref.total_bytes,
        "preview": preview,
        "continuation": {
            "has_more": True,
            "next": {"tool_call_id": tool_call_id, "artifact_id": ref.artifact_id},
        },
    }
    return envelope, ref, True


__all__ = ["envelope_for_text", "preview_bytes", "TextArtifactStore"]
