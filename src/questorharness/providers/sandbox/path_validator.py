"""Path boundary enforcement for sandbox file operations."""

from __future__ import annotations

from pathlib import Path


def validate_sandbox_path(
    path: Path,
    cwd: Path,
    extra_allowed: list[str] | None = None,
) -> tuple[bool, str]:
    """Check whether *path* falls within the sandbox boundary.

    Returns ``(True, "")`` when the path is allowed, or ``(False, reason)``
    when it falls outside the permitted directories.
    """
    resolved = path.resolve()
    resolved_cwd = cwd.resolve()

    # 主检查：路径必须位于项目目录内
    try:
        resolved.relative_to(resolved_cwd)
        return True, ""
    except ValueError:
        pass

    # 次检查：检查额外允许路径（来自文件系统设置）
    for allowed in extra_allowed or []:
        allowed_path = Path(allowed).expanduser().resolve()
        try:
            resolved.relative_to(allowed_path)
            return True, ""
        except ValueError:
            continue

    return False, f"path {resolved} is outside the sandbox boundary ({resolved_cwd})"
