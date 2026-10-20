"""L2 SeedContext：给带 session_id 的新 run 注入有界、只读的会话种子（v3 §4.2/§4.5）。

判据（三态拒收）：
- **idle-only**：只允许注入到尚未开跑的 run（IDLE）；跑中/终态一律拒；
- **cross-session**：``SeedRef.session_id`` 与目标 session 不一致即拒；
- **oversize**：正文 > 24KiB、估算 token > 6000、或 refs > 32 即拒。

种子消息以 ``ContentBlock(type="system_marker", payload={"origin": "seed", ...})`` 承载来源标记；
正文用真实 user/assistant 原文（受预算截断前先拒，不静默截），供 provider 作为新 run 的上下文。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from questor.contracts.common import new_id
from questor.contracts.state_schema import ContentBlock, Message, Role, RunStatus

MAX_SEED_BYTES = 24 * 1024
MAX_SEED_TOKENS = 6000
MAX_SEED_REFS = 32
MAX_SEED_MESSAGES = 4


class SeedRejected(ValueError):
    """种子被拒（reason ∈ idle_only | cross_session | oversize）；surface 映射成 400/CLI 错误。"""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SeedRef:
    """会话内引用：``seq`` 是 event_log 的全局物理序 gseq（跨 run 唯一）。"""

    session_id: str
    seq: int


def _bounded_text(rows: list[dict[str, Any]]) -> str:
    """把事实行（新→旧）翻成 user/assistant 原文；只取可见文本，无正文行跳过。"""
    lines: list[str] = []
    for row in reversed(rows):
        data = row.get("data") or {}
        if row.get("type") == "user_message":
            text = data.get("text")
            if isinstance(text, str) and text.strip():
                lines.append(f"user: {text}")
        elif row.get("type") == "message_completed":
            text = data.get("final_text")
            if isinstance(text, str) and text.strip():
                lines.append(f"assistant: {text}")
    return "\n".join(lines[-MAX_SEED_MESSAGES:])


def coerce_seed_refs(raw: object, session_id: str) -> tuple[SeedRef, ...]:
    """把 HTTP/CLI 传入的 refs（dict 或 SeedRef）归一成 tuple[SeedRef]；非法形状抛 ValueError。"""
    if not raw:
        return ()
    refs: list[SeedRef] = []
    for item in raw:  # type: ignore[union-attr]
        if isinstance(item, SeedRef):
            refs.append(item)
        elif isinstance(item, dict) and "seq" in item:
            refs.append(SeedRef(str(item.get("session_id") or session_id), int(item["seq"])))
        else:
            raise ValueError(f"seed ref must be SeedRef or {{session_id, seq}}, got {item!r}")
    return tuple(refs)


async def build_seed_context(
    store: object | None,
    session_id: str,
    *,
    refs: tuple[SeedRef, ...] = (),
    status: RunStatus = RunStatus.IDLE,
) -> Message:
    """构造一条 seed 消息；无历史也返回仅 marker 的消息（入口可见 origin='seed'）。"""
    if status is not RunStatus.IDLE:
        raise SeedRejected("idle_only", f"seed requires an idle run, got {status}")
    if len(refs) > MAX_SEED_REFS:
        raise SeedRejected("oversize", f"seed refs {len(refs)} exceed {MAX_SEED_REFS}")
    for ref in refs:
        if ref.session_id != session_id:
            raise SeedRejected(
                "cross_session", f"seed ref session {ref.session_id!r} does not match {session_id!r}"
            )

    rows: list[dict[str, Any]] = []
    if store is not None and callable(getattr(store, "session_transcript", None)):
        rows = await store.session_transcript(session_id, limit=max(MAX_SEED_MESSAGES, len(refs) or 0) * 2)  # type: ignore[attr-defined]
        if refs:
            wanted = {ref.seq for ref in refs}
            rows = [row for row in rows if row.get("gseq") in wanted]

    text = _bounded_text(rows)
    raw = text.encode("utf-8")
    if len(raw) > MAX_SEED_BYTES or (len(raw) + 3) // 4 > MAX_SEED_TOKENS:
        raise SeedRejected(
            "oversize",
            f"seed is {len(raw)} bytes (~{(len(raw) + 3) // 4} tokens); budget is {MAX_SEED_BYTES} bytes / {MAX_SEED_TOKENS} tokens",
        )

    marker = ContentBlock(
        type="system_marker",
        payload={
            "origin": "seed",
            "session_id": session_id,
            "refs": [{"session_id": ref.session_id, "seq": ref.seq} for ref in refs],
        },
    )
    content = (marker,) if not text else (marker, ContentBlock(type="text", text=text))
    return Message(id=new_id("msg"), role=Role.USER, content=content, seq=0)


__all__ = ["MAX_SEED_BYTES", "MAX_SEED_REFS", "MAX_SEED_TOKENS", "SeedRef", "SeedRejected", "build_seed_context", "coerce_seed_refs"]
