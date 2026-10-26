"""`pickers.py`：六个面板的别名解析与动作行（不重写命令语义）。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.serve.catalog import KINDS
from questorharness.bootstrap.hosts.terminal import pickers


def test_every_catalog_kind_has_a_panel() -> None:
    """catalog 加了 kind 而面板没跟上 → 用户看得见的面板黑洞。"""

    assert set(KINDS) <= set(pickers.PANELS)


def test_aliases_resolve_to_panels() -> None:
    for alias, kind in pickers.ALIASES.items():
        panel = pickers.resolve(alias)
        assert panel is not None and panel.kind == kind, alias


def test_unknown_panel_returns_none() -> None:
    assert pickers.resolve(":nope") is None


def test_model_panel_submits_the_selected_profile() -> None:
    panel = pickers.resolve(":model")
    assert panel is not None
    assert pickers.action_line(panel, "work") == "/model work"
    assert pickers.action_line(panel, None) is None


def test_mode_panel_submits_the_permissions_command() -> None:
    """:mode 面板落在引擎已有的 /permissions 三态上，不新写语义。"""

    panel = pickers.resolve(":mode")
    assert panel is not None and panel.kind == "posture"
    assert pickers.action_line(panel, "full_auto") == "/permissions full_auto"
    assert pickers.resolve(":posture").kind == "posture"
    assert pickers.resolve(":permission").kind == "posture"


def test_status_panel_is_read_only() -> None:
    """:status 只给人看（模型/推理强度现状），选中不得误发命令。"""

    panel = pickers.resolve(":status")
    assert panel is not None and panel.kind == "status"
    assert pickers.action_line(panel, "glm") is None


def test_todo_panel_is_read_only() -> None:
    """:todo 只给人看清单（写入是模型侧工具），选中不得误发命令。"""

    panel = pickers.resolve(":todo")
    assert panel is not None and panel.kind == "todos"
    assert pickers.resolve(":todos").kind == "todos"
    assert pickers.action_line(panel, "写文档") is None


def test_skill_panel_submits_the_skill_command() -> None:
    panel = pickers.resolve(":skills")
    assert panel is not None
    assert pickers.action_line(panel, "pdf") == "/pdf"


def test_list_panels_refresh_through_their_own_command() -> None:
    expected = {
        ":sessions": "/resume",
        ":mcp": "/mcp",
        ":tasks": "/tasks",
        ":jobs": "/tasks",
        ":git": "/branch",
    }
    for alias, command in expected.items():
        panel = pickers.resolve(alias)
        assert panel is not None
        assert pickers.action_line(panel, "whatever") == command, alias


def test_hint_lists_every_panel_kind() -> None:
    hint = pickers.list_hint()
    for kind in pickers.PANELS:
        assert f":{kind}" in hint, kind


def test_transcript_panel_is_read_only() -> None:
    """transcript 面板只给人看，选中不能误发命令。"""

    panel = pickers.resolve(":t")
    assert panel is not None and panel.kind == "transcript"
    assert pickers.resolve(":history") is panel
    assert pickers.action_line(panel, "3") is None
