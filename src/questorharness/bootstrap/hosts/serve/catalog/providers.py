"""只读内省目录：一个路由、按 kind 分发的纯函数提供者（plan03 波 D catalog）。

八个同构端点（sessions/models/skills/mcp/jobs/tasks/git）在形状上是同一件事：
`GET → 读一个内部注册表 → JSON`。合并成一个 `GET /catalog/{kind}` 之后，
新增一个面板只需加一个 provider 函数 + schema 加一个 kind 分支，扇出表只加一行。

响应 **不是** wire 帧：`CatalogResponse` 独立于 `ServerFrame` 联合，否则会触发
`apps/web` 的 cardSlots 全等守卫（plan03 §2.3）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from questorharness.capabilities.schedule.cron import load_cron_jobs
from questorharness.capabilities.skills.bundled import get_bundled_skills
from questorharness.config.settings import load_settings
from questorharness.platform.session_storage import list_session_snapshots
from questorharness.providers.auth.auth_manager import AuthManager
from questorharness.runtime.tasks.task_manager import get_task_manager

KINDS: tuple[str, ...] = ("sessions", "models", "skills", "mcp", "jobs", "tasks", "git")

CatalogItem = dict[str, Any]


@dataclass(frozen=True)
class CatalogContext:
    """provider 需要的全部上下文（当前目录）——不藏宿主对象，方便单测。"""

    cwd: Path


def _item(item_id: str, label: str, detail: str = "", *, current: bool = False) -> CatalogItem:
    entry: CatalogItem = {"id": item_id, "label": label}
    if detail:
        entry["detail"] = detail
    if current:
        entry["current"] = True
    return entry


def sessions(ctx: CatalogContext) -> list[CatalogItem]:
    """历史会话快照（新的在前）；空目录返回空表而不是报错。"""

    snapshots = list_session_snapshots(ctx.cwd)
    items: list[CatalogItem] = []
    for snapshot in snapshots:
        session_id = str(snapshot.get("session_id", "")) or "?"
        stamp = str(snapshot.get("saved_at", "")) or "?"
        count = snapshot.get("message_count")
        detail = stamp if count is None else f"{stamp} · {count} 条"
        items.append(_item(session_id, session_id[:8], detail, current=bool(snapshot.get("current"))))
    return items


def models(ctx: CatalogContext) -> list[CatalogItem]:
    """已配置的认证档位（每档一条），标出当前生效的那条。"""

    del ctx
    manager = AuthManager()
    try:
        active = manager.get_active_profile()
    except Exception:  # noqa: BLE001 - 无凭据时也要能列出空表
        active = None
    items: list[CatalogItem] = []
    raw_profiles: object
    try:
        raw_profiles = manager.list_profiles()
    except Exception:  # noqa: BLE001 - 读取失败按空表处理，面板显示空态
        raw_profiles = []
    profiles: list[object] = list(raw_profiles) if isinstance(raw_profiles, (list, tuple)) else []
    for profile in profiles:
        name = str(getattr(profile, "name", "") or getattr(profile, "id", "") or "")
        if not name:
            continue
        provider = str(getattr(profile, "provider", "") or "")
        model = str(getattr(profile, "model", "") or "")
        detail = " · ".join(part for part in (provider, model) if part)
        items.append(_item(name, name, detail, current=name == str(active or "")))
    return items


def skills(ctx: CatalogContext) -> list[CatalogItem]:
    """随包技能清单（/skills 的数据源同源）。"""

    del ctx
    items: list[CatalogItem] = []
    for skill in get_bundled_skills():
        name = str(getattr(skill, "name", "") or "")
        if not name:
            continue
        items.append(_item(name, name, str(getattr(skill, "description", "") or "")))
    return items


def mcp(ctx: CatalogContext) -> list[CatalogItem]:
    """配置里的 MCP 服务器（连接状态由 /mcp 命令查询，不在这里伪造）。"""

    del ctx
    servers = getattr(load_settings(), "mcp_servers", None)
    if not isinstance(servers, dict):
        return []
    return [_item(str(name), str(name)) for name in servers]


def jobs(ctx: CatalogContext) -> list[CatalogItem]:
    """cron 任务（enabled / 表达式 / 下次运行）。"""

    del ctx
    items: list[CatalogItem] = []
    for job in load_cron_jobs():
        name = str(job.get("name", "")) or "?"
        enabled = "on" if job.get("enabled", True) else "off"
        expression = str(job.get("expression", "") or "")
        detail = " · ".join(part for part in (enabled, expression) if part)
        items.append(_item(name, name, detail))
    return items


def tasks(ctx: CatalogContext) -> list[CatalogItem]:
    """后台任务：进行中的排在前面。"""

    del ctx
    try:
        records = get_task_manager().list_tasks()
    except Exception:  # noqa: BLE001 - 任务管理器未初始化时给空表
        return []
    items: list[CatalogItem] = []
    for record in records:
        task_id = str(getattr(record, "task_id", "") or getattr(record, "id", "") or "")
        status = str(getattr(record, "status", "") or "")
        task_type = str(getattr(record, "task_type", "") or "")
        label = task_id[:8] or status or "task"
        items.append(_item(task_id or label, label, " · ".join(p for p in (task_type, status) if p)))
    return items


def git(ctx: CatalogContext) -> list[CatalogItem]:
    """当前分支与工作区改动数（只读，失败不影响其它 kind）。"""

    import subprocess

    def _run(*args: str) -> str:
        result = subprocess.run(
            ("git", "-C", str(ctx.cwd), *args),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    branch = _run("rev-parse", "--abbrev-ref", "HEAD")
    if not branch:
        return []
    status = _run("status", "--porcelain")
    changed = len([line for line in status.splitlines() if line.strip()])
    return [_item(branch, branch, "工作区干净" if changed == 0 else f"{changed} 个文件改动", current=True)]


PROVIDERS: dict[str, Callable[[CatalogContext], list[CatalogItem]]] = {
    "sessions": sessions,
    "models": models,
    "skills": skills,
    "mcp": mcp,
    "jobs": jobs,
    "tasks": tasks,
    "git": git,
}


def build(kind: str, ctx: CatalogContext) -> list[CatalogItem] | None:
    """未知 kind 返回 None（路由翻成 404，绝不返回空表装成功）。"""

    provider = PROVIDERS.get(kind)
    if provider is None:
        return None
    return provider(ctx)
