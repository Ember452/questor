"""终端瘦客户端的门面：装配 runtime + serve 宿主，其余实现都在 `terminal/`。

REPL 与 Studio 走同一套端点（submit / cancel / approve / ask / events / commands），
只是 transport 换成进程内实现、渲染器换成 rich（plan03 §2.1）。
本模块只保留**装配**与对产品暴露的符号；会话循环、渲染、输入、覆盖层、键位
分别位于 `terminal/app.py`、`renderer.py`、`input_session.py`、`overlay.py`、`keymap.py`。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.terminal import app as terminal_app
from questorharness.bootstrap.hosts.terminal.renderer import TerminalRenderer
from questorharness.bootstrap.hosts.terminal.renderer import frame_from_sse as _frame_from_sse
from questorharness.bootstrap.runtime import build_runtime
from questorharness.profiles import ProfileError, list_profiles, load_profile

# 私有别名：保持既有导入方（宿主/测试）零改动。
SubmitResult = terminal_app.SubmitResult
_submit = terminal_app.submit
_open_panel = terminal_app.open_panel
_output_channel = terminal_app.output_channel
_build_prompt_session = terminal_app.build_prompt_session
completion_catalog = terminal_app.completion_catalog
_read_line = terminal_app.read_line

__all__ = [
    "SubmitResult",
    "TerminalRenderer",
    "_build_prompt_session",
    "_frame_from_sse",
    "_open_panel",
    "_output_channel",
    "_read_line",
    "_submit",
    "build_serve_host",
    "completion_catalog",
    "default_profile_root",
    "merge_tool_overrides",
    "run_terminal_client",
    "run_terminal_repl",
]


def default_profile_id(root: Path) -> str:
    """形态 bundle 里标了 `is_default` 的那一个；没有就报错（不隐式兼容某个名字）。"""

    for profile in list_profiles(root):
        if profile.is_default:
            return profile.name
    raise ProfileError(f"{root}: no profile is marked is_default")


def default_profile_root() -> Path:
    """默认形态目录：优先环境变量，其次产品侧 bundle 目录。"""
    override = os.environ.get("QUESTOR_PROFILE_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "questor" / "profiles"


async def run_terminal_client(
    host: ServeHost,
    *,
    prompt: str | None = None,
    console: Any = None,
) -> int:
    """跑交互循环（或单次 prompt）；实现在 `terminal/app.py`。"""
    return await terminal_app.run_terminal_client(host, prompt=prompt, console=console)


def merge_tool_overrides(
    profile: Any, overrides: Mapping[str, object] | None
) -> dict[str, Any]:
    """合并工具面：覆盖只许收窄；None 或缺省 → 用 profile 值。"""
    extra: dict[str, Any] = dict(overrides or {})
    if extra.get("allowed_tools") is None:
        extra["allowed_tools"] = list(profile.allowed_tools)
    if extra.get("denied_tools") is None:
        extra["denied_tools"] = list(profile.denied_tools)
    return extra


async def build_serve_host(
    *,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    api_client: Any = None,
    restore_messages: list[dict[str, Any]] | None = None,
    restore_tool_metadata: dict[str, object] | None = None,
    permission_mode: str | None = None,
    profile_root: Path | None = None,
    profile_id: str | None = None,
    overrides: Mapping[str, object] | None = None,
) -> ServeHost:
    """装配 runtime 与 serve 宿主（REPL 与 Studio 共用）。"""
    authority = Authority()
    root = profile_root or default_profile_root()
    # 形态是数据不是分支（plan03 §2.3）：默认取值也来自 bundle 的 is_default，不写死名字。
    resolved_id = profile_id or default_profile_id(root)
    profile = load_profile(root, resolved_id)
    extra = merge_tool_overrides(profile, overrides)
    runtime = await build_runtime(
        cwd=cwd,
        model=model,
        max_turns=max_turns,
        effort=effort,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_format=api_format,
        api_client=api_client,
        restore_messages=restore_messages,
        restore_tool_metadata=restore_tool_metadata,
        enforce_max_turns=max_turns is not None,
        permission_mode=permission_mode,
        permission_prompt=authority.permission_prompt,
        ask_user_prompt=authority.ask_user_prompt,
        edit_approval_prompt=authority.edit_approval_prompt,
        **extra,
    )
    return ServeHost(
        runtime,
        authority=authority,
        profile_root=root,
        profile_id=resolved_id,
    )


async def run_terminal_repl(
    *,
    prompt: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    api_client: Any = None,
    restore_messages: list[dict[str, Any]] | None = None,
    restore_tool_metadata: dict[str, object] | None = None,
    permission_mode: str | None = None,
    profile_root: Path | None = None,
    overrides: Mapping[str, object] | None = None,
    tui: bool = False,
) -> int:
    """装配 runtime + serve 宿主，然后进入终端（默认全屏 TUI，`tui=False` 回退行式 REPL）。"""
    host = await build_serve_host(
        cwd=cwd,
        model=model,
        max_turns=max_turns,
        effort=effort,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_format=api_format,
        api_client=api_client,
        restore_messages=restore_messages,
        restore_tool_metadata=restore_tool_metadata,
        permission_mode=permission_mode,
        profile_root=profile_root,
        overrides=overrides,
    )
    await host.start()
    try:
        if tui:
            from questorharness.bootstrap.hosts.tui import run_tui

            return await run_tui(host)
        return await run_terminal_client(host, prompt=prompt)
    finally:
        await host.close()
