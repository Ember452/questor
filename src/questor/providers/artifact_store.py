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


__all__ = ["FileSystemArtifactStore"]
