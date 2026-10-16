"""把 ProcessResult 映射成有界 ToolResult（bash/powershell 共用）。"""

from __future__ import annotations

from dataclasses import asdict

from questor.contracts.artifacts import ArtifactRef
from questor.contracts.process import ProcessResult
from questor.contracts.tool import ToolResult


def _ref_dict(ref: ArtifactRef | None) -> dict[str, object] | None:
    if ref is None:
        return None
    data = asdict(ref)
    data["created_at"] = ref.created_at.isoformat()
    return data


def process_to_tool_result(result: ProcessResult, *, name: str) -> ToolResult:
    """进程事实 → 给模型的文本 + 给人 display + artifact 引用；失败也不抛（保配对）。"""
    if result.error is not None:
        return ToolResult(status="error", result=f"{name} could not run: {result.error}", display=result.warning)

    parts: list[str] = []
    if result.timed_out:
        parts.append(f"[timed out after killing process tree, exit={result.exit_code}]")
    else:
        parts.append(f"[exit {result.exit_code}]")
    if result.stdout_text:
        parts.append(result.stdout_text)
    if result.stderr_text:
        parts.append(f"[stderr]\n{result.stderr_text}")
    if result.warning:
        parts.append(f"[sandbox] {result.warning}")
    if result.env_scrubbed:
        parts.append(f"[env scrubbed: {', '.join(result.env_scrubbed)}]")
    body = "\n".join(parts)

    artifact: dict[str, object] = {}
    if result.stdout_artifact is not None:
        artifact["stdout"] = _ref_dict(result.stdout_artifact)
    if result.stderr_artifact is not None:
        artifact["stderr"] = _ref_dict(result.stderr_artifact)

    # 超时单独成状态：账本要能区分“被 Harness 杀死”与“工具自己失败”（C7/ADR-0016）。
    status = "timed_out" if result.timed_out else "success"
    display = f"{name} exit={result.exit_code}" + (" (timed out)" if result.timed_out else "")
    return ToolResult(status=status, result=body, display=display, artifact=artifact or None)


__all__ = ["process_to_tool_result"]
