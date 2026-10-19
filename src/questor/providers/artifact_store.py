"""L5 FileSystemArtifactStore（ADR-0019；HARD C4/C13）。

内容寻址保存大工具输出；路径只由 store root + sha256 组成，调用方不能拼 traversal。
写入使用临时文件 + fsync + atomic replace，同内容天然去重。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from questor.contracts.artifacts import ArtifactRef


class FileSystemArtifactStore:
    """按 run 隔离的内容寻址 artifact 文件存储。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        if self.root.name in {"", ".", ".."}:
            raise ValueError("ArtifactStore root must name a concrete directory")

    async def connect(self) -> None:
        """创建存储根。"""
        await asyncio.to_thread(self._ensure_root)

    async def close(self) -> None:
        """当前为纯文件系统 store；保留 close 以匹配 Port 生命周期。"""
        return None

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    async def put_text(
        self,
        content: str,
        *,
        run_id: str,
        kind: str,
        media_type: str = "text/plain",
    ) -> ArtifactRef:
        """UTF-8 文本原子落盘，返回有界引用而非绝对路径秘密。"""
        return await self.put_bytes(content.encode("utf-8"), run_id=run_id, kind=kind, media_type=media_type)

    async def put_bytes(
        self,
        content: bytes,
        *,
        run_id: str,
        kind: str,
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef:
        """原子写入 bytes；异常向上传给 ProcessRunner/tool，由调用方有界降级。"""
        if not run_id or any(part in {"", ".", ".."} for part in Path(run_id).parts):
            raise ValueError("Artifact run_id must be a safe identifier")
        digest = hashlib.sha256(content).hexdigest()
        suffix = ".txt" if media_type.startswith("text/") else ".bin"
        target = self.root / f"{digest}{suffix}"
        await asyncio.to_thread(self._atomic_write, target, content)
        return ArtifactRef(
            artifact_id=f"artifact://{digest[:16]}",
            sha256=digest,
            total_bytes=len(content),
            kind=kind,
            media_type=media_type,
            created_at=datetime.now(UTC),
        )

    def _atomic_write(self, target: Path, content: bytes) -> None:
        self._ensure_root()
        if target.exists():
            # 内容寻址；已有相同 digest 时不重复覆盖，避免并发写互相竞争。
            return
        handle, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=self.root)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise

    def _referenced_ids_from_files(self) -> dict[str, Path]:
        """扫存储根，映 artifact_id → 文件路径（id = ``artifact://{digest[:16]}``，与 ``put_*`` 产生的 artifact_id 一致）。"""
        out: dict[str, Path] = {}
        if not self.root.is_dir():
            return out
        for path in self.root.iterdir():
            if not path.is_file():
                continue
            # 忽略临时写文件（以 . 开头）；正式文件名 = {64-hex-digest}{suffix}。
            if path.name.startswith("."):
                continue
            digest = path.stem
            if len(digest) >= 16:
                out[f"artifact://{digest[:16]}"] = path
        return out

    async def gc_orphans(self, referenced_ids: set[str], *, dry_run: bool = False) -> list[str]:
        """P10/ADR-0050：**可达性孤儿 GC**。只删不被任何引用 artifact_id 集命中的文件。

        ``referenced_ids`` 应由调用方从 ``event_log``/``checkpoints`` 提取（见 ``referenced_artifact_ids``）。
        内容寻址跨 run 去重 → 删前按 id 全集判定，绝不删活跃引用（承 ADR-0019/0020 log 不裁→活跃 id 恒在）。
        返回被删（或 dry_run 时将被删）的 artifact_id 列表（不返绝对路径）。写失败静默降级（旁路回收，不抛）。
        """
        def _run() -> list[str]:
            removed: list[str] = []
            for artifact_id, path in self._referenced_ids_from_files().items():
                if artifact_id in referenced_ids:
                    continue  # 仍被引用→保留（去重下任一引用者存活即不删）
                removed.append(artifact_id)
                if not dry_run:
                    with contextlib.suppress(OSError):
                        path.unlink()
            return removed

        return await asyncio.to_thread(_run)


def referenced_artifact_ids(records: object) -> set[str]:
    """从事件/快照结构中递归提取所有 ``artifact://`` 指针（供 ``gc_orphans`` 定引用集）。

    遇 dict/list 递归；任何字符串值以 ``artifact://`` 开头即计作一个引用（覆盖
    tool_completed.artifact_ref / peer_ended.result_ref / memory_written.artifact_ref 等）。"""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.startswith("artifact://"):
            found.add(node)

    walk(records)
    return found


__all__ = ["FileSystemArtifactStore", "referenced_artifact_ids"]
