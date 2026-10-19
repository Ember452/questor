"""内置补丁工具：``apply_patch``（design/03 §6）。精确上下文、逐文件 all-or-nothing。

支持标准 unified diff 的 ``--- a/<path>`` / ``+++ b/<path>`` 头与 ``@@`` hunk；
``--- /dev/null`` 表示新建，``+++ /dev/null`` 表示删除。先对全部文件按上下文校验，任一
hunk 上下文不匹配即整体报错、不写任何文件（不留半文件）；每个路径逐条做 workspace
containment（越界 deny）。
"""

from __future__ import annotations

import contextlib
import re
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
        # 每个 hunk: (old_start 或 None, old_block_lines, new_block_lines)
        self.hunks: list[tuple[int | None, list[str], list[str]]] = []
        self.is_new = old_path is None
        self.is_delete = new_path is None


def _parse_patch(text: str) -> list[_FileChange]:
    changes: list[_FileChange] = []
    lines = text.splitlines()
    i = 0
    current: _FileChange | None = None

    def _is_header(idx: int) -> bool:
        # 真文件段头 = `--- <path>` 紧跟 `+++ <path>`。正文里形如 `--- BREAK` 的行（后不接 `+++ `）
        # 不得被误判为新文件段（#156 BLK-11：否则静默删除同名无关文件并报 success）。
        return lines[idx].startswith("--- ") and idx + 1 < len(lines) and lines[idx + 1].startswith("+++ ")

    while i < len(lines):
        line = lines[i]
        if _is_header(i):
            old = _strip_prefix(line[4:])
            new = _strip_prefix(lines[i + 1][4:])
            current = _FileChange(old, new)
            changes.append(current)
            i += 2
            continue
        if line.startswith("@@"):
            if current is None:
                raise ValueError("hunk outside any file section")
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            old_start = int(m.group(1)) if m else None
            i += 1
            old_block: list[str] = []
            new_block: list[str] = []
            while i < len(lines) and not lines[i].startswith("@@") and not _is_header(i):
                body = lines[i]
                if body.startswith("\\"):  # "\ No newline at end of file" —— 忽略标记行
                    i += 1
                    continue
                if body.startswith("-"):
                    old_block.append(body[1:])
                elif body.startswith("+"):
                    new_block.append(body[1:])
                elif body == "" or body.startswith(" "):  # 上下文行（前导空格或空行）
                    old_block.append(body[1:] if body[:1] == " " else body)
                    new_block.append(body[1:] if body[:1] == " " else body)
                else:
                    # 非 diff 内容行（如 `diff --git` 元数据）→ 不属本 hunk，停止交主循环。
                    break
                i += 1
            current.hunks.append((old_start, old_block, new_block))
            continue
        i += 1
    return changes


def _apply_hunks(original_lines: list[str], hunks: list[tuple[int | None, list[str], list[str]]]) -> list[str]:
    """逐个 hunk 用 old_block 作为子序列精确匹配后替换为 new_block；找不到即抛错。

    纯新增 hunk（old_block 为空）按 ``@@`` 声明的行号位置插入（#156 MAJ-12：旧实现一律插到文件头）；
    无行号（裸 ``@@``）时回退到末尾追加。"""
    working = list(original_lines)
    for old_start, old_block, new_block in hunks:
        if not old_block:
            pos = max(0, min(old_start - 1, len(working))) if old_start else len(working)
            working = working[:pos] + new_block + working[pos:]
            continue
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
            raw = str(rel or "")
            norm = raw.replace("\\", "/")
            if norm[:2] in ("a/", "b/"):
                norm = norm[2:]
            # 同时试原始与 a/b-剥离候选（#156 BLK-1）：`a/` 前缀 diff 落到真实路径、受权限/保护区约束，
            # 而不是原样建出 `a/secret.txt`。
            for cand in (raw, norm):
                res = resolve_in_workspace(cand, root=ctx.workspace_root, cwd=ctx.cwd)
                if res.ok and res.path is not None:
                    break
            else:
                return ToolResult(status="error", result=f"{raw}: {res.error or 'invalid path'}")
            target = res.path
            if change.is_delete:
                if not target.exists():
                    return ToolResult(status="error", result=f"delete target missing: {target.name}")
                planned.append((target, None))
                continue
            sep = "\n"
            if change.is_new:
                existing: list[str] = []
            else:
                if not target.is_file():
                    return ToolResult(status="error", result=f"patch target not a file: {target.name}")
                try:
                    raw = target.read_bytes().decode("utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    return ToolResult(status="error", result=f"read failed: {exc}")
                # 行尾保真（#156 MAJ-13）：CRLF 文件写回 CRLF、LF 保持 LF，避免整文件换行翻转。
                sep = "\r\n" if "\r\n" in raw else "\n"
                existing = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if change.is_new and target.exists():
                return ToolResult(status="error", result=f"create target exists: {target.name}")
            try:
                if change.is_new:
                    new_lines: list[str] = []
                    for _old_start, _old_block, new_block in change.hunks:
                        new_lines += new_block
                else:
                    new_lines = _apply_hunks(existing, change.hunks)
            except ValueError:
                return ToolResult(status="error", result=f"context mismatch in {target.name}; aborting whole apply_patch (no files written)")
            planned.append((target, sep.join(new_lines).encode("utf-8")))

        # 阶段二：原子落盘（#156 MAJ-11）——先快照所有目标的原字节/存在性，任一写或删失败即回滚全部，
        # 跨多文件不留“半改”（此前一个文件失败会留下其余已写入的修改）。
        originals: list[tuple[Path, bytes | None]] = []
        for target, _payload in planned:
            try:
                originals.append((target, target.read_bytes() if target.is_file() else None))
            except OSError as exc:  # 预读失败：尚未改动任何文件，直接结构化报错。
                return ToolResult(status="error", result=f"cannot read {target.name}: {exc}; no files were changed")
        try:
            for target, payload in planned:
                if payload is None:
                    target.unlink()
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
        except OSError as exc:
            failed = target.name
            for target, blob in originals:  # 回滚到快照：恢复原内容 / 删刚建的文件 / 复原被删文件。
                with contextlib.suppress(OSError):
                    if blob is None:
                        if target.exists():
                            target.unlink()
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(blob)
            return ToolResult(status="error", result=f"apply failed on {failed}: {exc}; rolled back all files")
        written = [str(target) for target, _ in planned]
        return ToolResult(status="success", result=f"applied patch to {len(written)} file(s)", display="patched: " + ", ".join(Path(w).name for w in written), files=tuple(written))


__all__ = ["ApplyPatchTool"]
