"""内置只读工具：``grep``（design/03 §6）。Python 回退实现的正则内容搜索。

纯标准库、无 subprocess（capabilities 层守卫禁止 import subprocess/沙箱具体实现），逐文件
按行匹配，跳过噪音目录/二进制/过大文件，命中数上限；``rg`` 若存在可由 bash/powershell 工具
走进程沙箱路径，本工具不直接 spawn 进程，保证与 shell 工具的边界/预算语义一致。
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from questor.capabilities.tools._output import preview_bytes
from questor.capabilities.tools._paths import SKIP_DIR_NAMES, resolve_in_workspace
from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_GREP_SPEC = ToolSpec(
    name="grep",
    description="Regex content search across workspace files (pure-python fallback).",
    params={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "regex"},
            "path": {"type": "string", "description": "search root, default '.'"},
            "glob": {"type": "string", "description": "filename filter like '*.py'"},
            "max_matches": {"type": "integer", "minimum": 1},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
    capability=Capability.READONLY,
    risk=Risk.LOW,
    read_only=True,
    timeout_s=30,
)

_DEFAULT_MAX_MATCHES = 200
_MAX_FILE_BYTES = 2 * 1024 * 1024  # 超过则跳过（避免整读巨型文件）


class GrepTool(Tool):
    spec = _GREP_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult(status="error", result="'pattern' must be a non-empty regex")
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(status="error", result=f"invalid regex pattern: {exc}")
        base = resolve_in_workspace(str(args.get("path", ".")), root=ctx.workspace_root, cwd=ctx.cwd, must_exist=True)
        if not base.ok or base.path is None:
            return ToolResult(status="error", result=base.error or "invalid path")
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        name_glob = args.get("glob")
        name_glob = name_glob if isinstance(name_glob, str) and name_glob else None
        max_matches = _as_int(args.get("max_matches"), _DEFAULT_MAX_MATCHES)
        root = ctx.workspace_root.resolve()
        hits: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base.path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            if ctx.is_cancelled():
                return ToolResult(status="error", result="cancelled")
            for filename in sorted(filenames):
                if name_glob and not fnmatch.fnmatch(filename, name_glob):
                    continue
                full = Path(dirpath) / filename
                try:
                    if full.stat().st_size > _MAX_FILE_BYTES:
                        continue
                    text = full.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue  # 二进制/不可读：跳过而非中断
                rel = _relpath(full, root)
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line):
                        hits.append(f"{rel}:{lineno}:{line.strip()[:200]}")
                        if len(hits) >= max_matches:
                            body = preview_bytes("\n".join(hits), 64 * 1024)
                            return ToolResult(status="success", result=body, display=f"grep {pattern}: {len(hits)} match(es) (capped)")
        body = preview_bytes("\n".join(hits), 64 * 1024)
        return ToolResult(status="success", result=body or "(no matches)", display=f"grep {pattern}: {len(hits)} match(es)")


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _as_int(value: object, default: int) -> int:
    try:
        return max(1, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


__all__ = ["GrepTool"]
