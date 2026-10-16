"""L0' console sink：把 ``LogEntry`` 渲染为人读一行写 **stderr**（DESIGN §10；D10）。

三层归属（DESIGN §3）：**内核文件**——运行时 import 只在 observability 包内。

**永不写 stdout**（G-L10）：``--list`` 等机器可读输出走 stdout，console sink 落 stdout 会污染它。
默认流 ``sys.stderr``、``min_level=INFO``（D10 console INFO / file DEBUG）。编码非 UTF-8 locale 下
抛错时降级为 ASCII ``replace`` 重写，绝不把 ``UnicodeEncodeError`` 上冒（参照 hermes ``_safe_stderr``
思路，MIT）。异常最终仍由 pipeline 的 exporter 兜底，本 sink 先自行尽力降级。
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from questor.observability.entry import LogLevel

if TYPE_CHECKING:  # 仅类型。
    from questor.observability.entry import LogEntry


def render_text(entry: LogEntry) -> str:
    """渲染成人读单行：``<ts> <LEVEL> <logger>: <msg> <k=v>…``（关联键/字段尾注）。"""
    line = f"{entry.ts.isoformat()} {entry.level.name} {entry.logger}: {entry.msg}"
    # context（关联键）与 fields（结构化附加）都渲染成 key=value，值不引号包裹便于 grep。
    tail = {**entry.context, **entry.fields}
    if tail:
        line += " " + " ".join(f"{k}={v}" for k, v in tail.items())
    if entry.traceback:
        line += f" | traceback={entry.traceback}"
    return line


class ConsoleSink:
    """stderr 文本出口。属性 ``min_level`` 供 pipeline 过滤；``name`` 供自我观测禁用行标识。"""

    name = "console"

    def __init__(self, stream: object | None = None, min_level: LogLevel = LogLevel.INFO) -> None:
        self._stream = stream  # None → 运行期解析 sys.stderr（配合 capsys 且永不固化 stdout）
        self.min_level = min_level

    def _target(self) -> object:
        return self._stream if self._stream is not None else sys.stderr

    def emit(self, entry: LogEntry) -> None:
        line = render_text(entry)
        try:
            target = self._target()
            target.write(line + "\n")  # type: ignore[attr-defined]
            target.flush()  # type: ignore[attr-defined]
        except (UnicodeEncodeError, ValueError, OSError):
            # 非 UTF-8 字符（Windows 中文 locale 等）→ ASCII replace 兜底重写；再失败则静默。
            safe = line.encode("ascii", "replace").decode("ascii")
            try:
                target = self._target()
                target.write(safe + "\n")  # type: ignore[attr-defined]
                target.flush()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - 观测面绝不拖垮被观测物（D13）
                pass
