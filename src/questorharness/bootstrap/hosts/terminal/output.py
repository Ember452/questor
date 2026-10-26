"""控制台写端的编码降级：cp936 宿主写不下 `✓` 时只降级字符，不抛异常。

实跑现场（plan03 波 F）：非 UTF-8 代码页的控制台里，footer 的 `✓` 让
`Console.print` 抛 `UnicodeEncodeError`，异常顺着消费任务冒到 SSE 循环外，
`turn_done` 的 `done.set()` 永不执行——EOF 前的 drain 白等 300s 才退出，
用户看到的是“答完了但什么都不打印，卡五分钟”。

单点修法：把 stdout 包一层 `errors="replace"` 的写端，字形装不下就落 `?`。
"""

from __future__ import annotations

import sys
from typing import IO, Any, cast

from rich.console import Console


class _Tolerant:
    """转发写端；不能编码的字符按目标编码 `replace` 掉，其余属性原样透传。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def write(self, text: str) -> int:
        encoding = getattr(self._inner, "encoding", None) or "utf-8"
        try:
            text.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            text = text.encode(encoding, "replace").decode(encoding, "replace")
        return int(self._inner.write(text))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def tolerant_stream(stream: IO[str]) -> IO[str]:
    """给任意文本流套一层编码降级（幂等：已经套过的原样返回）。"""

    if isinstance(stream, _Tolerant):
        return stream
    return cast(IO[str], _Tolerant(stream))


def console(stream: IO[str] | None = None, **kwargs: Any) -> Console:
    """终端客户端用的控制台：默认写 `sys.stdout`，但写端永不因编码抛异常。"""

    target = stream if stream is not None else sys.stdout
    return Console(file=tolerant_stream(target), **kwargs)
