"""内置补丁工具：``apply_patch``（design/03 §6）。精确上下文、逐文件 all-or-nothing。

支持标准 unified diff 的 ``--- a/<path>`` / ``+++ b/<path>`` 头与 ``@@`` hunk；
``--- /dev/null`` 表示新建，``+++ /dev/null`` 表示删除。先对全部文件按上下文校验，任一
hunk 上下文不匹配即整体报错、不写任何文件（不留半文件）；每个路径逐条做 workspace
containment（越界 deny）。
"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools._paths import resolve_in_workspace
from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_APPLY_PATCH_SPEC = ToolSpec(
    name="apply_patch",
    description="Apply a precise-context unified diff across workspace files, atomically.",
    params={
        "type": "object",
        "properties": {"input": {"type": "string", "description": "unified diff text"}},
        "required": ["input"],
        "additionalProperties": False,
    },
    capability=Capability.WRITE,
    risk=Risk.HIGH,
    read_only=False,
    timeout_s=30,
)


def _strip_prefix(raw: str) -> str | None:
    """从 diff 头取实际路径：去 ``a/``/``b/`` 前缀；``/dev/null`` 视为无路径标记。"""
    value = raw.strip()
    if value == "/dev/null" or not value:
        return None
    if len(value) > 2 and value[1] == "/" and value[0] in "ab":
        return value[2:]
    return value


class _FileChange:
    def __init__(self, old_path: str | None, new_path: str | None) -> None:
        self.old_path = old_path
        self.new_path = new_path
        self.hunks: list[tuple[list[str], list[str]]] = []  # (old_block_lines, new_block_lines)
        self.is_new = old_path is None
        self.is_delete = new_path is None


def _parse_patch(text: str) -> list[_FileChange]:
    changes: list[_FileChange] = []
    lines = text.splitlines()
    i = 0
    current: _FileChange | None = None
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            old = _strip_prefix(line[4:])
            new = _strip_prefix(lines[i + 1][4:]) if i + 1 < len(lines) and lines[i + 1].startswith("+++ ") else None
            current = _FileChange(old, new)
            changes.append(current)
            i += 2
            continue
        if line.startswith("+++ ") and current is None:
            current = _FileChange(None, _strip_prefix(line[4:]))
            changes.append(current)
            i += 1
            continue
        if line.startswith("@@"):
            if current is None:
                raise ValueError("hunk outside any file section")
            i += 1
            old_block: list[str] = []
            new_block: list[str] = []
            while i < len(lines) and not lines[i].startswith("@@") and not lines[i].startswith("--- "):
                body = lines[i]
                if body.startswith("\\"):  # "\ No newline at end of file" —— 忽略标记行
                    i += 1
                    continue
                if body.startswith("-"):
                    old_block.append(body[1:])
                elif body.startswith("+"):
                    new_block.append(body[1:])
                else:  # 上下文行（前导空格或空行）
                    old_block.append(body[1:] if body[:1] == " " else body)
                    new_block.append(body[1:] if body[:1] == " " else body)
                i += 1
            current.hunks.append((old_block, new_block))
            continue
        i += 1
    return changes


def _apply_hunks(original_lines: list[str], hunks: list[tuple[list[str], list[str]]]) -> list[str]:
    """逐个 hunk 用 old_block 作为子序列精确匹配后替换为 new_block；找不到即抛错。"""
    working = list(original_lines)
    for old_block, new_block in hunks:
        idx = _find_subsequence(working, old_block)
        if idx < 0:
            raise ValueError("context mismatch")
        working = working[:idx] + new_block + working[idx + len(old_block) :]
    return working


def _find_subsequence(haystack: list[str], needle: list[str]) -> int:
    if not needle:
        return 0
    n, m = len(haystack), len(needle)
    for start in range(n - m + 1):
        if haystack[start : start + m] == needle:
            return start
    return -1


class ApplyPatchTool(Tool):
    """把 unified diff 原子地应用到 workspace 内的多个文件。"""

    spec = _APPLY_PATCH_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        patch = args.get("input")
        if not isinstance(patch, str) or not patch.strip():
            return ToolResult(status="error", result="'input' must be non-empty unified diff")
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        try:
            changes = _parse_patch(patch)
        except ValueError as exc:
            return ToolResult(status="error", result=f"malformed patch: {exc}")
        if not changes:
            return ToolResult(status="error", result="no file sections in patch")

        # 阶段一：全部校验 + 生成目标内容，绝不落盘。
        planned: list[tuple[Path, bytes | None]] = []  # bytes=None 表示删除
        for change in changes:
            rel = change.new_path or change.old_path
            res = resolve_in_workspace(str(rel or ""), root=ctx.workspace_root, cwd=ctx.cwd)
            if not res.ok or res.path is None:
                return ToolResult(status="error", result=f"{rel}: {res.error or 'invalid path'}")
            target = res.path
            if change.is_delete:
                if not target.exists():
                    return ToolResult(status="error", result=f"delete target missing: {target.name}")
                planned.append((target, None))
                continue
            if change.is_new:
                existing: list[str] = []
            else:
                if not target.is_file():
                    return ToolResult(status="error", result=f"patch target not a file: {target.name}")
                try:
                    existing = target.read_text(encoding="utf-8").split("\n")
                except (OSError, UnicodeDecodeError) as exc:
                    return ToolResult(status="error", result=f"read failed: {exc}")
            if change.is_new and target.exists():
                return ToolResult(status="error", result=f"create target exists: {target.name}")
            try:
                if change.is_new:
                    new_lines: list[str] = []
                    for _old, new_block in change.hunks:
                        new_lines += new_block
                else:
                    new_lines = _apply_hunks(existing, change.hunks)
            except ValueError:
                return ToolResult(status="error", result=f"context mismatch in {target.name}; no files were changed")
            planned.append((target, "\n".join(new_lines).encode("utf-8")))

        # 阶段二：全部校验通过后统一落盘。
        written: list[str] = []
        for target, payload in planned:
            try:
                if payload is None:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
            except OSError as exc:
                return ToolResult(status="error", result=f"apply failed on {target.name}: {exc}")
            written.append(str(target))
        return ToolResult(status="success", result=f"applied patch to {len(written)} file(s)", display="patched: " + ", ".join(Path(w).name for w in written), files=tuple(written))


__all__ = ["ApplyPatchTool"]
