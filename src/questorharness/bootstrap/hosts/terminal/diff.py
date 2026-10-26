"""审批 detail → diff 卡。

`authority.edit_approval_prompt` 交出来的形状是：

    +{added}/-{removed}
    {补丁正文，最多 4000 字符}

本模块只做"读得懂"这一件事：首行摘要单独成行，补丁按 `+` / `-` / `@@` / 文件头
着色，长行折行而**不截断**（审批必须看清改了什么）。到 4000 字符上限时补一行
可见提示——静默少内容是审批卡最不能犯的错。
"""

from __future__ import annotations

from typing import Final

from rich.console import Group, RenderableType
from rich.text import Text

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.terminal import strings

PATCH_LIMIT: Final[int] = 4000


def _line_style(line: str) -> str:
    if line.startswith(("+++", "---")):
        return theme.DIM
    if line.startswith("@@"):
        return theme.DELEG
    if line.startswith("+"):
        return theme.OK
    if line.startswith("-"):
        return theme.ERR
    return ""


def render_patch(patch: str, *, added: int, removed: int) -> RenderableType:
    """结构化字段（plan03 波 D2）：统计行自己拼，补丁正文照旧进块状态机。"""

    header = f"+{added}/-{removed}"
    return render_detail(f"{header}\n{patch}" if patch else header)


def render_detail(detail: str) -> RenderableType:
    """把 detail 字符串渲染成 (摘要行, 补丁行...) 的分组。"""

    text = detail.strip("\n")
    if not text:
        return Text("")

    lines = text.splitlines()
    head, patch = lines[0], lines[1:]

    parts: list[RenderableType] = [Text("  " + head, style=theme.DIM)]
    for line in patch:
        parts.append(Text("  " + line, style=_line_style(line)))
    if len(detail) >= PATCH_LIMIT:
        parts.append(Text("  " + strings.DIFF_TRUNCATED, style=theme.WARN))
    return Group(*parts)
