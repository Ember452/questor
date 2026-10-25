"""补全：斜杠命令（前缀 + 子序列 + 描述）与路径（含 `@` 前缀）。

参照 Reasonix `tui/complete.go` 的三类补全（命令 / 参数 / 路径）收窄成本项目需要的两类：
本仓命令语义归引擎注册表，这里只负责**怎么让人更快打出来**。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

MAX_PATH_RESULTS = 50


def _subsequence(token: str, candidate: str) -> bool:
    """子序列模糊匹配：`/cmp` 命中 `/compact`。"""

    it = iter(candidate)
    return all(char in it for char in token)


class SlashCompleter(Completer):
    """斜杠命令补全：前缀优先，其次子序列；描述作为 meta 显示。"""

    def __init__(self, catalog: Mapping[str, str]) -> None:
        self._catalog = dict(catalog)

    def get_completions(
        self, document: Document, complete_event: object
    ) -> Iterable[Completion]:
        del complete_event
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        token = text
        exact = sorted(name for name in self._catalog if name.startswith(token))
        fuzzy = sorted(
            name
            for name in self._catalog
            if name not in exact and _subsequence(token.lstrip("/"), name.lstrip("/"))
        )
        for name in (*exact, *fuzzy):
            yield Completion(
                name,
                start_position=-len(token),
                display=name,
                display_meta=self._catalog[name],
            )


class FileCompleter(Completer):
    """路径补全：`@path` 与裸路径；只列当前目录一层，避免一次刷屏。"""

    def __init__(self, base: Path | None = None) -> None:
        self._base = base or Path.cwd()

    def get_completions(
        self, document: Document, complete_event: object
    ) -> Iterable[Completion]:
        del complete_event
        text = document.text_before_cursor
        if not text or text.startswith("/"):
            return
        token = text.split()[-1] if text.split() else text
        prefix_marker = "@" if token.startswith("@") else ""
        raw = token[len(prefix_marker) :]
        if not raw and not prefix_marker:
            return
        directory = (self._base / raw).parent if raw else self._base
        name_prefix = Path(raw).name if raw else ""
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        shown = 0
        for entry in entries:
            if name_prefix and not entry.name.startswith(name_prefix):
                continue
            if shown >= MAX_PATH_RESULTS:
                return
            shown += 1
            suffix = "/" if entry.is_dir() else ""
            completion = f"{prefix_marker}{raw[: len(raw) - len(name_prefix)]}{entry.name}{suffix}"
            yield Completion(
                completion,
                start_position=-len(token),
                display=f"{entry.name}{suffix}",
                display_meta="目录" if entry.is_dir() else "",
            )
