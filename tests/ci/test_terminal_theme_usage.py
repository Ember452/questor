"""主题公开图元必须真的被用到（plan03 F1：声明了行为却没行为 = 缺陷）。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THEME = REPO_ROOT / "src/questorharness/bootstrap/hosts/serve/terminal_theme.py"
SRC = REPO_ROOT / "src"

_ALLOWED_ZERO_CALL: frozenset[str] = frozenset()


def _public_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]


def _call_sites(name: str) -> int:
    """消耗方的 `theme.<name>(` 引用次数。

    只认限定调用（全仓都 `import ... terminal_theme as theme`），否则“同名函数自己定义”会被算成调用。
    """

    pattern = re.compile(rf"theme\.{re.escape(name)}\s*\(")
    hits = 0
    for path in SRC.rglob("*.py"):
        if path == THEME:
            continue
        hits += len(pattern.findall(path.read_text(encoding="utf-8")))
    return hits


def test_every_public_theme_primitive_is_called() -> None:
    unused = [name for name in _public_functions(THEME) if _call_sites(name) == 0]
    assert set(unused) <= _ALLOWED_ZERO_CALL, f"零调用的主题图元：{unused}"


def test_guard_self_test() -> None:
    """自证：不存在的图元必须算出 0 个引用，否则守卫是假绿。"""

    names = _public_functions(THEME)
    assert names, "terminal_theme 没有公开函数，守卫已失去意义"
    assert _call_sites("status_bar") > 0, "F1 回归：status_bar 必须有人调用"
    assert _call_sites("no_such_primitive") == 0
