"""面板状态机与 alt-screen 宿主（plan03 C1/E1-E6）。

状态部分是纯函数（可单测、无 TTY 依赖）；真正的全屏渲染只在 TTY 上用
prompt_toolkit `Application(full_screen=True)`——它是 alt-screen 的**唯一 owner**，
退出后 scrollback 原样还在。非 TTY 宿主退化成编号选择，保证脚本/CI 仍可用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from questorharness.bootstrap.hosts.terminal import strings, width

VISIBLE_ROWS = 12

# 面板内按 `/` 请求进入搜索的哨兵：只在 run() 的循环里流转，绝不作为选中 id 外泄。
SEARCH = "__search__"


@dataclass
class PanelState:
    """一个面板：标题 + 行 + 游标 + 搜索词。"""

    title: str
    items: list[dict[str, Any]]
    index: int = 0
    query: str = ""
    kind: str = "browse"

    def visible(self) -> list[dict[str, Any]]:
        """当前过滤后的行（搜索按 id/label/detail 子串匹配）。"""

        if not self.query:
            return list(self.items)
        needle = self.query.lower()
        return [
            item
            for item in self.items
            if any(needle in str(item.get(key, "")).lower() for key in ("id", "label", "detail"))
        ]

    def selected(self) -> dict[str, Any] | None:
        rows = self.visible()
        if not rows:
            return None
        return rows[min(self.index, len(rows) - 1)]


def move(state: PanelState, delta: int) -> PanelState:
    """上下移动游标（越界夹住，不循环——循环会让长列表失去方向感）。"""

    rows = state.visible()
    if not rows:
        state.index = 0
        return state
    state.index = max(0, min(len(rows) - 1, state.index + delta))
    return state


def set_query(state: PanelState, query: str) -> PanelState:
    """改搜索词；游标回到顶部，避免"过滤后指向不存在的行"。"""

    state.query = query
    state.index = 0
    return state


def render_lines(state: PanelState, *, limit: int = VISIBLE_ROWS) -> list[str]:
    """把面板渲染成若干行文本（alt-screen 与编号回退共用同一份内容）。"""

    rows = state.visible()
    header = f"{state.title}  ({len(rows)} 项)"
    lines = [header]
    if state.query:
        lines.append(f"  搜索：{state.query}")
    if not rows:
        lines.append("  （空）")
        return lines
    start = max(0, min(state.index - limit // 2, max(0, len(rows) - limit)))
    last_group = None
    for offset, item in enumerate(rows[start : start + limit]):
        group = item.get("group")
        if group and group != last_group:
            # 命令族标题（plan03 C2/T18）：族变了就插一行，不硬编码清单。
            lines.append(strings.PANEL_GROUP.format(group=group))
            last_group = group
        position = start + offset
        marker = ">" if position == state.index else " "
        current = "*" if item.get("current") else " "
        label = str(item.get("label", item.get("id", "")))
        detail = str(item.get("detail", ""))
        line = f"{marker}{current} {label}"
        if detail:
            line += f"  {detail}"
        lines.append("  " + width.truncate(line, 100))
    lines.append(strings.PANEL_HINT)
    return lines


def _numbered_choice(state: PanelState) -> str | None:
    """非 TTY：打印编号列表并读一个序号（`/` 请求搜索，空输入=取消）。"""

    rows = state.visible()
    for number, item in enumerate(rows, start=1):
        detail = item.get("detail")
        suffix = f"  {detail}" if detail else ""
        print(f"  {number}. {item.get('label', item.get('id', ''))}{suffix}")
    try:
        raw = input(strings.PANEL_CHOICE_PROMPT)
    except (EOFError, KeyboardInterrupt):
        return None
    raw = raw.strip()
    if raw == "/":
        return SEARCH
    if not raw.isdigit():
        return None
    index = int(raw) - 1
    if 0 <= index < len(rows):
        return str(rows[index].get("id", ""))
    return None


def _read_search(state: PanelState) -> None:
    """读一个搜索词并应用（空=清过滤；EOF/Ctrl-C 保持现状）。"""

    try:
        query = input(strings.PANEL_SEARCH_PROMPT)
    except (EOFError, KeyboardInterrupt):
        return
    set_query(state, query.strip())


def run(
    state: PanelState, *, console: Any | None = None, full_screen: bool = True
) -> str | None:
    """打开面板并返回被选中项的 id（Esc/q/空输入 → None）。

    `/` 请求搜索时先退出面板读一个搜索词，再带着过滤重开；搜索哨兵只在
    本循环流转，绝不当成选中 id 返回（否则会被拼进斜杠命令提交出去）。
    TTY + prompt_toolkit 时进 alt-screen；否则退化为编号选择。
    """

    while True:
        result = _open_once(state, full_screen=full_screen)
        if result != SEARCH:
            return result if isinstance(result, str) else None
        _read_search(state)


def _open_once(state: PanelState, *, full_screen: bool) -> str | None:
    """打开一次面板（不处理搜索往返）。"""

    import sys

    if not full_screen or not sys.stdin.isatty():
        return _numbered_choice(state)

    try:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
    except ImportError:  # 没有 prompt_toolkit 就退回编号选择
        return _numbered_choice(state)

    bindings = KeyBindings()

    @bindings.add("j")
    @bindings.add("down")
    def _down(event: Any) -> None:
        move(state, 1)
        event.app.invalidate()

    @bindings.add("k")
    @bindings.add("up")
    def _up(event: Any) -> None:
        move(state, -1)
        event.app.invalidate()

    @bindings.add("/")
    def _search(event: Any) -> None:
        state.kind = "search"
        event.app.exit(result=SEARCH)

    @bindings.add("escape")
    @bindings.add("q")
    @bindings.add("c-c")
    def _cancel(event: Any) -> None:
        event.app.exit(result=None)

    @bindings.add("enter")
    def _accept(event: Any) -> None:
        item = state.selected()
        event.app.exit(result=None if item is None else str(item.get("id", "")))

    control = FormattedTextControl(lambda: [("", "\n".join(render_lines(state)))])
    app: Any = Application(
        layout=Layout(Window(content=control)),
        key_bindings=bindings,
        full_screen=True,
    )
    result = app.run()
    return result if isinstance(result, str) else None
