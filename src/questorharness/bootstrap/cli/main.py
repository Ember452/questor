"""CLI entry point using typer."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

__version__ = "0.1.0"


from questorharness.bootstrap.cli.preview import (
    _build_dry_run_preview,
    _format_dry_run_preview,
)
from questorharness.platform.io import sanitize_text


def _version_callback(value: bool) -> None:
    if value:
        print(f"questorharness {__version__}")
        raise typer.Exit()


def _clean_arg(value: str | None) -> str | None:
    """argv 可能带孤立代理对（非 UTF-8 代码页解码残留）；进引擎前先归一。"""

    return None if value is None else sanitize_text(value)


app = typer.Typer(
    name="questorharness",
    help=(
        "QuestorHarness: a local-first AI coding assistant.\n\n"
        "Starts an interactive session by default, use -p/--print for non-interactive output."
    ),
    add_completion=False,
    rich_markup_mode="rich",
    invoke_without_command=True,
)


# ---------------------------------------------------------------------------
# 子命令装配：命令组在这里挂到 app 上，具体实现各自成模块。
# ---------------------------------------------------------------------------

from questorharness.bootstrap.cli.auth_commands import auth_app
from questorharness.bootstrap.cli.autopilot_commands import autopilot_app
from questorharness.bootstrap.cli.config_commands import config_app
from questorharness.bootstrap.cli.cron_commands import cron_app
from questorharness.bootstrap.cli.mcp_commands import mcp_app
from questorharness.bootstrap.cli.plugin_commands import plugin_app
from questorharness.bootstrap.cli.provider_commands import provider_app
from questorharness.bootstrap.cli.setup import setup_cmd

app.add_typer(mcp_app)
app.add_typer(plugin_app)
app.add_typer(auth_app)
app.add_typer(provider_app)
app.add_typer(config_app)
app.add_typer(cron_app)
app.add_typer(autopilot_app)

# setup 向导的实现住在 setup.py；在这里注册，app 的命令面仍然只有一个出处。
# 注册顺序决定 --help 里命令表的顺序，改动它会改变用户可见输出（基线会报红）。
app.command("setup")(setup_cmd)


# ---------------------------------------------------------------------------
# 入口：交互式会话或 --print 单次运行
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
    # --- 会话 ---
    continue_session: bool = typer.Option(
        False,
        "--continue",
        "-c",
        help="Continue the most recent conversation in the current directory",
        rich_help_panel="Session",
    ),
    resume: str | None = typer.Option(
        None,
        "--resume",
        "-r",
        help="Resume a conversation by session ID, or open picker",
        rich_help_panel="Session",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Set a display name for this session",
        rich_help_panel="Session",
    ),
    # --- 模型与投入等级 ---
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model alias (e.g. 'sonnet', 'opus') or full model ID",
        rich_help_panel="Model & Effort",
    ),
    effort: str | None = typer.Option(
        None,
        "--effort",
        help="Effort level for the session (low, medium, high, xhigh/max)",
        rich_help_panel="Model & Effort",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Override verbose mode setting from config",
        rich_help_panel="Model & Effort",
    ),
    max_turns: int | None = typer.Option(
        None,
        "--max-turns",
        help="Maximum number of agentic turns (enforced by default in --print; optional cap for interactive mode)",
        rich_help_panel="Model & Effort",
    ),
    # --- 输出 ---
    print_mode: str | None = typer.Option(
        None,
        "--print",
        "-p",
        help="Print response and exit. Pass your prompt as the value: -p 'your prompt'",
        rich_help_panel="Output",
    ),
    output_format: str | None = typer.Option(
        None,
        "--output-format",
        help="Output format with --print: text (default), json, or stream-json",
        rich_help_panel="Output",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview resolved runtime config, skills, commands, and tools without executing the model or tools",
        rich_help_panel="Output",
    ),
    # --- 权限 ---
    permission_mode: str | None = typer.Option(
        None,
        "--permission-mode",
        help="Permission mode: default, plan, or full_auto",
        rich_help_panel="Permissions",
    ),
    dangerously_skip_permissions: bool = typer.Option(
        False,
        "--dangerously-skip-permissions",
        help="Bypass all permission checks (only for sandboxed environments)",
        rich_help_panel="Permissions",
    ),
    allowed_tools: list[str] | None = typer.Option(
        None,
        "--allowed-tools",
        help="Comma or space-separated list of tool names to allow",
        rich_help_panel="Permissions",
    ),
    disallowed_tools: list[str] | None = typer.Option(
        None,
        "--disallowed-tools",
        help="Comma or space-separated list of tool names to deny",
        rich_help_panel="Permissions",
    ),
    # --- 系统与上下文 ---
    system_prompt: str | None = typer.Option(
        None,
        "--system-prompt",
        "-s",
        help="Override the default system prompt",
        rich_help_panel="System & Context",
    ),
    append_system_prompt: str | None = typer.Option(
        None,
        "--append-system-prompt",
        help="Append text to the default system prompt",
        rich_help_panel="System & Context",
    ),
    settings_file: str | None = typer.Option(
        None,
        "--settings",
        help="Path to a JSON settings file or inline JSON string",
        rich_help_panel="System & Context",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="Anthropic-compatible API base URL",
        rich_help_panel="System & Context",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "-k",
        help="API key (overrides config and environment)",
        rich_help_panel="System & Context",
    ),
    bare: bool = typer.Option(
        False,
        "--bare",
        help="Minimal mode: skip hooks, plugins, MCP, and auto-discovery",
        rich_help_panel="System & Context",
    ),
    plain: bool = typer.Option(
        False,
        "--plain",
        help="Line-mode REPL instead of the full-screen terminal UI",
        rich_help_panel="System & Context",
    ),
    api_format: str | None = typer.Option(
        None,
        "--api-format",
        help="API format: 'anthropic' (default), 'openai' (DashScope, GitHub Models, etc.), or 'copilot' (GitHub Copilot)",
        rich_help_panel="System & Context",
    ),
    theme: str | None = typer.Option(
        None,
        "--theme",
        help="TUI theme: default, dark, minimal, cyberpunk, solarized, or custom name",
        rich_help_panel="System & Context",
    ),
    # --- 高级 ---
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Enable debug logging",
        rich_help_panel="Advanced",
    ),
    mcp_config: list[str] | None = typer.Option(
        None,
        "--mcp-config",
        help="Load MCP servers from JSON files or strings",
        rich_help_panel="Advanced",
    ),
    cwd: str = typer.Option(
        str(Path.cwd()),
        "--cwd",
        help="Working directory for the session",
        hidden=True,
    ),
    studio_host: bool = typer.Option(
        False,
        "--studio-host",
        help="Run the loopback studio host (handshake line on stdout)",
        hidden=True,
    ),
    serve_no_auth: bool = typer.Option(
        False,
        "--serve-no-auth",
        help="DEV ONLY: skip the launch credential checks on the loopback host",
        hidden=True,
    ),
    task_worker: bool = typer.Option(
        False,
        "--task-worker",
        help="Run the stdin-driven headless worker loop used for background agent tasks",
        hidden=True,
    ),
) -> None:
    """Start an interactive session or run a single prompt."""
    if ctx.invoked_subcommand is not None:
        return

    # Windows 控制台代码页会把中文 argv 解成孤立代理对；先归一，别让它一路
    # 走到 session memory 写入再炸（子智能体派发实跑撞过）。
    print_mode = _clean_arg(print_mode)
    system_prompt = _clean_arg(system_prompt)
    append_system_prompt = _clean_arg(append_system_prompt)

    import asyncio
    import logging

    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
            stream=sys.stderr,
        )
        logging.getLogger("questorharness").setLevel(logging.DEBUG)
    elif os.environ.get("QUESTORHARNESS_LOG_LEVEL"):
        lvl = getattr(logging, os.environ["QUESTORHARNESS_LOG_LEVEL"].upper(), logging.WARNING)
        logging.basicConfig(
            level=lvl, format="%(asctime)s [%(name)s] %(levelname)s %(message)s", stream=sys.stderr
        )

    if dangerously_skip_permissions:
        permission_mode = "full_auto"

    # 全屏 TUI 需要真终端；管道/CI/`--plain` 走行式 REPL（脚本化调用不能断）。
    use_tui = not plain and sys.stdin.isatty() and sys.stdout.isatty()

    # 将 --theme 覆盖项应用到设置
    if theme:
        from questorharness.config.settings import load_settings, save_settings

        settings = load_settings()
        settings.theme = theme
        save_settings(settings)

    from questorharness.bootstrap.hosts.app import run_print_mode, run_repl, run_task_worker
    from questorharness.bootstrap.hosts.serve.studio import run_studio_host
    from questorharness.bootstrap.hosts.tool_policy import ToolPolicyError, resolve_tool_policy

    try:
        tool_allowed, tool_denied = resolve_tool_policy(allowed_tools, disallowed_tools)
    except ToolPolicyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(2) from exc
    tool_overrides: dict[str, object] | None = (
        {"allowed_tools": tool_allowed, "denied_tools": tool_denied}
        if tool_allowed is not None or tool_denied is not None
        else None
    )

    if dry_run and (continue_session or resume is not None):
        print("Error: --dry-run does not support --continue/--resume yet.", file=sys.stderr)
        raise typer.Exit(1)

    if dry_run:
        prompt = print_mode.strip() if print_mode is not None else None
        if print_mode is not None and not prompt:
            print(
                "Error: -p/--print requires a prompt value, e.g. -p 'your prompt'", file=sys.stderr
            )
            raise typer.Exit(1)
        preview = _build_dry_run_preview(
            prompt=prompt,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            base_url=base_url,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
            api_key=api_key,
            api_format=api_format,
            permission_mode=permission_mode,
            effort=effort,
        )
        effective_output_format = output_format or "text"
        if effective_output_format == "text":
            print(_format_dry_run_preview(preview))
        elif effective_output_format == "json":
            print(json.dumps(preview, ensure_ascii=False, indent=2))
        elif effective_output_format == "stream-json":
            print(json.dumps(preview, ensure_ascii=False))
        else:
            print(
                "Error: --dry-run only supports --output-format text, json, or stream-json",
                file=sys.stderr,
            )
            raise typer.Exit(1)
        return

    # 处理 --continue 和 --resume 标志
    if continue_session or resume is not None:
        from questorharness.platform.session_storage import (
            list_session_snapshots,
            load_session_by_id,
            load_session_snapshot,
        )

        session_data = None
        if continue_session:
            session_data = load_session_snapshot(cwd)
            if session_data is None:
                print("No previous session found in this directory.", file=sys.stderr)
                raise typer.Exit(1)
            print(f"Continuing session: {session_data.get('summary', '(untitled)')[:60]}")
        elif resume == "" or resume is None:
            # --resume 未带值时显示会话选择器
            sessions = list_session_snapshots(cwd, limit=10)
            if not sessions:
                print("No saved sessions found.", file=sys.stderr)
                raise typer.Exit(1)
            print("Saved sessions:")
            for i, s in enumerate(sessions, 1):
                print(
                    f"  {i}. [{s['session_id']}] {s.get('summary', '?')[:50]} ({s['message_count']} msgs)"
                )
            choice = typer.prompt("Enter session number or ID")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(sessions):
                    session_data = load_session_by_id(cwd, sessions[idx]["session_id"])
                else:
                    print("Invalid selection.", file=sys.stderr)
                    raise typer.Exit(1)
            except ValueError:
                session_data = load_session_by_id(cwd, choice)
            if session_data is None:
                print(f"Session not found: {choice}", file=sys.stderr)
                raise typer.Exit(1)
        else:
            session_data = load_session_by_id(cwd, resume)
            if session_data is None:
                print(f"Session not found: {resume}", file=sys.stderr)
                raise typer.Exit(1)

        # 将恢复的会话传给 REPL
        asyncio.run(
            run_repl(
                prompt=None,
                cwd=cwd,
                model=session_data.get("model") or model,
                base_url=base_url,
                system_prompt=system_prompt,
                api_key=api_key,
                restore_messages=session_data.get("messages"),
                restore_tool_metadata=session_data.get("tool_metadata"),
                permission_mode=permission_mode,
                api_format=api_format,
                effort=effort,
                overrides=tool_overrides,
                tui=use_tui,
                replay=True,
            )
        )
        return

    if print_mode is not None:
        prompt = print_mode.strip()
        if not prompt:
            print(
                "Error: -p/--print requires a prompt value, e.g. -p 'your prompt'", file=sys.stderr
            )
            raise typer.Exit(1)
        asyncio.run(
            run_print_mode(
                prompt=prompt,
                output_format=output_format or "text",
                cwd=cwd,
                model=model,
                base_url=base_url,
                system_prompt=system_prompt,
                append_system_prompt=append_system_prompt,
                api_key=api_key,
                api_format=api_format,
                permission_mode=permission_mode,
                max_turns=max_turns,
                effort=effort,
                allowed_tools=tool_allowed,
                denied_tools=tool_denied,
            )
        )
        return

    if task_worker:
        asyncio.run(
            run_task_worker(
                cwd=cwd,
                model=model,
                max_turns=max_turns,
                base_url=base_url,
                system_prompt=system_prompt,
                api_key=api_key,
                api_format=api_format,
                permission_mode=permission_mode,
                effort=effort,
                allowed_tools=tool_allowed,
                denied_tools=tool_denied,
            )
        )
        return

    if studio_host:
        asyncio.run(
            run_studio_host(
                cwd=cwd,
                model=model,
                max_turns=max_turns,
                base_url=base_url,
                system_prompt=system_prompt,
                api_key=api_key,
                api_format=api_format,
                permission_mode=permission_mode,
                effort=effort,
                allow_no_auth=serve_no_auth,
                overrides=tool_overrides,
            )
        )
        return

    asyncio.run(
        run_repl(
            prompt=None,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            base_url=base_url,
            system_prompt=system_prompt,
            api_key=api_key,
            api_format=api_format,
            permission_mode=permission_mode,
            effort=effort,
            overrides=tool_overrides,
            tui=use_tui,
        )
    )


# questor: allow R8 -- refactor the offenders in W8
