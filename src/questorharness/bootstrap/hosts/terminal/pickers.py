"""六个面板：kind → 标题 + 选中后的动作（plan03 E1-E6）。

动作一律走 `/submit` 的斜杠命令，不在终端里重写命令语义：
能带参数的命令（模型 / 技能）把 id 拼进去，列表型命令（会话/任务/cron/git/MCP）
只刷新列表——宁可少做一步，也不伪造一个引擎不支持的调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from questorharness.bootstrap.hosts.terminal import overlay


@dataclass(frozen=True)
class Panel:
    kind: str
    title: str
    action: str  # 斜杠命令模板，`{id}` 会被选中项替换
    uses_id: bool = False


PANELS: Final[dict[str, Panel]] = {
    "models": Panel("models", "模型 / 认证档位", "/model {id}", uses_id=True),
    "sessions": Panel("sessions", "历史会话", "/resume"),
    "skills": Panel("skills", "技能", "/{id}", uses_id=True),
    "mcp": Panel("mcp", "MCP 服务器", "/mcp"),
    "jobs": Panel("jobs", "定时任务", "/tasks"),
    "tasks": Panel("tasks", "后台任务", "/tasks"),
    "git": Panel("git", "分支与工作区", "/branch"),
}

ALIASES: Final[dict[str, str]] = {
    ":model": "models",
    ":models": "models",
    ":session": "sessions",
    ":sessions": "sessions",
    ":skill": "skills",
    ":skills": "skills",
    ":mcp": "mcp",
    ":job": "jobs",
    ":jobs": "jobs",
    ":task": "tasks",
    ":tasks": "tasks",
    ":git": "git",
}


def resolve(kind_or_alias: str) -> Panel | None:
    """`:model` / `models` → Panel；不认识返回 None（调用方提示可用清单）。"""

    key = kind_or_alias.strip().lower()
    kind = ALIASES.get(key, key)
    return PANELS.get(kind)


def action_line(panel: Panel, selected_id: str | None) -> str | None:
    """选中项 → 要提交的斜杠命令；列表型面板无选中项也返回刷新命令。"""

    if not panel.uses_id:
        return panel.action
    if not selected_id:
        return None
    return panel.action.format(id=selected_id)


def open_panel(
    panel: Panel, items: list[dict[str, object]], *, full_screen: bool = True
) -> str | None:
    """打开面板，返回选中的 id（取消返回 None）。"""

    state = overlay.PanelState(title=panel.title, items=[dict(item) for item in items], kind=panel.kind)
    return overlay.run(state, full_screen=full_screen)


def list_hint() -> str:
    """面板清单（未知 kind 时给用户看）。"""

    return "可用面板：" + " · ".join(f":{key}" for key in PANELS)
