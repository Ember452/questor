"""Turn a user-supplied name into one safe filename component.

Used when a channel receives an attachment whose name comes from the other side of the
network, so the value must never become a path. Replaces the ``helpers`` module this came
out of (plan 01 ledger #127): the file is named after what it does, and the only
in-repository caller is the Feishu adapter.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

__all__ = ["dedupe_filename", "safe_filename"]

# 名字来自网络另一侧,可能是 POSIX 路径、Windows 路径,或两者混着来。按两种分隔符
# 切而不是用 ``Path(...).name``:后者的分隔符语义跟着宿主 OS 走,POSIX 上的
# ``Path(r"C:\Users\me\photo.jpg").name`` 会原样返回整串(iOS/Android 客户端与
# 网关所在的 Linux 正是 POSIX),同一个名字在 Windows 与 Linux 上就得到两个结果。
_SEPARATORS = re.compile(r"[\\/]")


def safe_filename(value: object, *, max_length: int = 128) -> str:
    """Return a conservative filename-safe representation of ``value``.

    Path separators, control characters, shell metacharacters, and whitespace
    collapse to underscores; Unicode word characters (CJK included) survive,
    because Chinese attachment names are the common case on Feishu, not an
    attack. The result is a single basename, not a path.
    """

    if value is None:
        return ""
    name = _SEPARATORS.split(str(value))[-1]
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[^\w.-]+", "_", name, flags=re.UNICODE).strip("_.-")
    if not name or name in {".", ".."}:
        return ""
    return name[:max_length]


def dedupe_filename(name: str, *, exists: Callable[[str], bool]) -> str:
    """Return ``name``, or ``name-N``, for the first candidate that does not exist.

    Two attachments in one message can carry the same sanitised name; the caller
    decides existence (usually ``(directory / candidate).exists()``) so the
    function stays pure and testable.
    """

    if not exists(name):
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem:
        stem, extension = name, ""
    index = 1
    while index < 1000:
        candidate = f"{stem}-{index}.{extension}" if extension else f"{stem}-{index}"
        if not exists(candidate):
            return candidate
        index += 1
    return f"{stem}-999.{extension}" if extension else f"{stem}-999"

