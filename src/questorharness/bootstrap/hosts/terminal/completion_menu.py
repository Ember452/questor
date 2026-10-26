"""Reasonix 风格补全菜单的纯逻辑（无 prompt_toolkit、无 TTY 依赖）。

移植自 `DeepSeek-Reasonix/internal/frontend/tui/complete.go`，对应关系：

- `wants_menu`          ← `wantsMenu`：裸 `/cmd` 或 `@ref` 才自动弹；
- `build`               ← `onCompletion` 的"有候选才建菜单"；
- `move`                ← `menuKey` 的 `(sel±1+n)%n` 环形移动；
- `accept_text`         ← `acceptCompletion`：用选中项替换 token，返回新光标；
- `should_accept_on_enter` ← `menuChoiceTyped` 的反面：已打字=提交，否则=补全；
- `visible_rows`        ← `menuLines` 的 8 行滑动窗口（`sel-4` 起、边界夹住）。

中文文案不落在本模块（终端包文案集中在 `strings.py`），快捷键提示由调用方传入。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from questorharness.bootstrap.hosts.terminal.width import truncate

#: 菜单窗口行数：Reasonix `menuRows` 同值，8 行在 110 条命令面前仍够看。
VISIBLE_ROWS = 8

#: 选中行前缀（Reasonix 的 `›` 游标）与未选中行的对齐缩进。
SELECT_MARKER = "› "
INDENT = "  "


@dataclass(frozen=True)
class MenuRow:
    """一行候选：`label` 是展示文本，`insert` 是接受后写回编辑区的文本。"""

    label: str
    insert: str
    hint: str = ""


@dataclass
class Menu:
    """当前打开的补全菜单；`start`/`end` 是 `insert` 要替换的文本区间。"""

    rows: list[MenuRow] = field(default_factory=list)
    start: int = 0
    end: int = 0
    kind: str = "slash"
    sel: int = 0

    def selected(self) -> MenuRow | None:
        """当前高亮行；空菜单返回 None（调用方据此决定是否接受）。"""

        if not self.rows:
            return None
        return self.rows[max(0, min(self.sel, len(self.rows) - 1))]


def wants_menu(text: str, cursor: int, *, force: bool = False) -> bool:
    """光标处是否处于补全上下文。

    Reasonix 同款判定：整行是裸 `/token`（没有空格/换行），或光标所在词以 `@`
    开头。`force=True`（Tab 显式补全）额外允许裸路径词——自动弹仍只认 `/` 与 `@`。
    """

    before = text[:cursor]
    if before.startswith("/") and not any(ch in before for ch in " \n\t"):
        return True
    token_start = max(before.rfind(" "), before.rfind("\n"), before.rfind("\t")) + 1
    token = before[token_start:]
    if token.startswith("@"):
        return True
    return force and bool(token) and not token.startswith("/")


def build(rows: list[MenuRow], start: int, end: int, *, kind: str = "slash") -> Menu | None:
    """有候选就建菜单（选中第一行），否则 None。"""

    if not rows:
        return None
    return Menu(rows=list(rows), start=start, end=end, kind=kind, sel=0)


def move(menu: Menu, delta: int) -> int:
    """环形移动选中项（越界回绕，长列表不会卡在两端）。返回新下标。"""

    count = len(menu.rows)
    if count == 0:
        menu.sel = 0
        return 0
    menu.sel = (menu.sel + delta) % count
    return menu.sel


def accept_text(menu: Menu, line: str) -> tuple[str, int]:
    """用选中行替换 `[start, end)`，返回（新整行, 新光标）。无选中则原样返回。"""

    row = menu.selected()
    if row is None:
        return line, len(line)
    head = line[: menu.start] + row.insert
    return head + line[menu.end :], len(head)


def should_accept_on_enter(menu: Menu, line: str) -> bool:
    """Enter 是否该当成"接受补全"而不是"提交"。

    Reasonix 规则：行内容已经等于高亮项 → 提交（False）；只是前缀 → 补全（True）。
    """

    row = menu.selected()
    if row is None:
        return False
    return line.strip() != row.label


def visible_rows(
    menu: Menu, *, rows_per_page: int = VISIBLE_ROWS
) -> list[tuple[int, MenuRow]]:
    """当前窗口内的 `(原始下标, 行)`；选中项居中、边界夹住（Reasonix `menuLines`）。"""

    count = len(menu.rows)
    if count == 0:
        return []
    page = max(1, rows_per_page)
    first = max(0, min(menu.sel - page // 2, count - page))
    last = min(count, first + page)
    return [(index, menu.rows[index]) for index in range(first, last)]


def menu_lines(
    menu: Menu,
    width: int,
    *,
    rows_per_page: int = VISIBLE_ROWS,
    hint: str = "",
) -> list[str]:
    """把菜单渲染成纯文本行（测试与非 TTY 回退共用）；`hint` 追加为末行。"""

    lines: list[str] = []
    for index, row in visible_rows(menu, rows_per_page=rows_per_page):
        marker = SELECT_MARKER if index == menu.sel else INDENT
        text = f"{marker}{row.label}"
        if row.hint:
            text = f"{text}  {row.hint}"
        lines.append(truncate(text, width))
    if hint:
        lines.append(hint)
    return lines
