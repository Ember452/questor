"""T15：文件工具共享的路径解析（design/03 §5/§7；ADR-0018）。

所有文件工具的路径都经这里过一遍，保证一致的 containment 语义：
- 展开 ``~`` 与环境变量；
- 相对路径锚定 workspace root（或给定 cwd）；
- ``realpath``（``Path.resolve()``）解析 symlink/junction，解析失败即拒绝；
- 解析后必须仍在 workspace root 内（normcase 做 Windows 大小写不敏感比较）。

只返回结构化结果，绝不抛；调用方把 ``error`` 直接转成 ``ToolResult(status="error")``。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PathResolution:
    ok: bool
    path: Path | None = None
    error: str = ""


def _contained(candidate: Path, root: Path) -> bool:
    """candidate 是否落在 root 内（realpath 之后，跨平台大小写/分隔符归一）。"""
    try:
        Path(os.path.normcase(str(candidate))).relative_to(Path(os.path.normcase(str(root))))
        return True
    except ValueError:
        return False


def resolve_in_workspace(
    raw: str,
    *,
    root: Path,
    cwd: Path | None = None,
    must_exist: bool = False,
) -> PathResolution:
    """把工具给来的路径解析成 workspace 内的绝对路径；越界/解析失败/缺失都拒绝。"""
    if not isinstance(raw, str) or not raw.strip():
        return PathResolution(False, error="missing or empty path")
    expanded = Path(os.path.expandvars(str(Path(raw).expanduser())))
    base = (cwd or root)
    candidate = expanded if expanded.is_absolute() else base / expanded
    try:
        resolved = candidate.resolve()
        resolved_root = root.resolve()
    except OSError as exc:  # realpath 失败：宁可拒绝也不猜（fail-closed）
        return PathResolution(False, error=f"path resolution failed: {exc}")
    if not _contained(resolved, resolved_root):
        return PathResolution(False, error=f"path escapes workspace root: {raw}")
    if must_exist and not resolved.exists():
        return PathResolution(False, error="path does not exist")
    return PathResolution(True, path=resolved)


__all__ = ["PathResolution", "resolve_in_workspace"]
