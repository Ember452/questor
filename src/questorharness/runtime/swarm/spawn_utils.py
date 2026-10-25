"""Shared utilities for spawning teammate processes."""

from __future__ import annotations

import os
import shlex
import shutil
import sys


# 用于覆盖队友命令的环境变量
TEAMMATE_COMMAND_ENV_VAR = "QUESTORHARNESS_TEAMMATE_COMMAND"


# ---------------------------------------------------------------------------
# 转发给已生成队友的环境变量。
#
# tmux 可能启动一个全新的登录 shell，不会继承父进程
# 环境，因此这里会转发其中已设置的变量。
# ---------------------------------------------------------------------------

_TEAMMATE_ENV_VARS = [
    # --- API 提供商选择 -------------------------------------------
    # 缺少这些变量时，队友会默认使用错误的端点提供商
    # 并导致所有 API 调用失败（类似 TS 源码中的 GitHub issue #23561）。
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    # --- 配置目录覆盖 ----------------------------------------
    # 使运维级配置在队友进程中可见。
    "CLAUDE_CONFIG_DIR",
    # --- 远程 / CCR 标记 ---------------------------------------------
    # CCR 相关代码路径会检查 CLAUDE_CODE_REMOTE。认证会自行
    # 处理；FD 环境变量跨 tmux 边界本来也无效。
    "CLAUDE_CODE_REMOTE",
    # 自动记忆开关检查 REMOTE && !MEMORY_DIR，以在临时
    # CCR 文件系统上禁用记忆。仅转发 REMOTE 会让
    # 父进程开启记忆时队友却关闭记忆。
    "CLAUDE_CODE_REMOTE_MEMORY_DIR",
    # --- 上游代理设置 ------------------------------------------
    # 父进程的 MITM 中继可从同一容器网络中的队友访问。
    # 转发代理变量，使队友将
    # 客户配置的流量经中继转发，以便注入凭据。
    # 缺少这些变量时，队友会完全绕过代理。
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "NO_PROXY",
    "no_proxy",
    # --- CA 证书包覆盖 ----------------------------------------------
    # 使用 TLS 检查时，自定义 CA 证书必须对队友可见；
    # 缺少这些证书会导致 SSL 校验失败。
    "SSL_CERT_FILE",
    "NODE_EXTRA_CA_CERTS",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    # --- QuestorHarness 原生提供商设置 --------------------------------
    # 这些变量由 settings._apply_env_overrides() 读取，必须跨
    # tmux 边界保留，使队友与领导者使用同一提供商。
    "QUESTORHARNESS_CONFIG_DIR",
    "QUESTORHARNESS_DATA_DIR",
    "QUESTORHARNESS_LOGS_DIR",
    "QUESTORHARNESS_PROFILE",
    "QUESTORHARNESS_API_FORMAT",
    "QUESTORHARNESS_PROVIDER",
    "QUESTORHARNESS_BASE_URL",
    "QUESTORHARNESS_MODEL",
    "QUESTORHARNESS_ANTHROPIC_API_KEY",
    "QUESTORHARNESS_OPENAI_API_KEY",
    "QUESTORHARNESS_DASHSCOPE_API_KEY",
    "QUESTORHARNESS_MOONSHOT_API_KEY",
    "QUESTORHARNESS_GEMINI_API_KEY",
    "QUESTORHARNESS_MINIMAX_API_KEY",
    "QUESTORHARNESS_NVIDIA_API_KEY",
    "QUESTORHARNESS_MODELSCOPE_API_KEY",
    "OPENAI_API_KEY",
]


def get_teammate_command() -> str:
    """Return the executable used to spawn teammate processes.

    Resolution order:
    1. ``QUESTORHARNESS_TEAMMATE_COMMAND`` environment variable — allows the
       operator to point at a specific binary or wrapper script.
    2. The current Python interpreter running the ``questorharness`` module.
       This keeps spawned teammates on the same venv/source tree as the
       leader process.
    3. The ``questorharness`` entry-point on PATH (installed package fallback).
    """
    override = os.environ.get(TEAMMATE_COMMAND_ENV_VAR)
    if override:
        return override

    # 优先使用当前解释器，使队友继承相同的运行时和
    # 与父进程相同的可编辑安装源码树。
    if sys.executable:
        return sys.executable

    entry_point = shutil.which("questorharness")
    if entry_point:
        return entry_point
    return "python"


def build_inherited_cli_flags(
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    system_prompt_mode: str | None = None,
    permission_mode: str | None = None,
    plan_mode_required: bool = False,
    settings_path: str | None = None,
    teammate_mode: str | None = None,
    plugin_dirs: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    extra_flags: list[str] | None = None,
) -> list[str]:
    """Build CLI flags to propagate from the current session to spawned teammates.

    Ensures teammates inherit important settings like permission mode, model
    selection, and plugin configuration from their parent.

    All flag values are shell-quoted with :func:`shlex.quote` to prevent
    command injection when the resulting list is later joined into a shell
    command string.

    Args:
        model: Model override to forward (e.g. ``"claude-opus-4-6"``).
        system_prompt: System prompt override to forward to the teammate.
        system_prompt_mode: One of ``"replace"``/``"default"`` or ``"append"``.
            ``append`` maps to ``--append-system-prompt``; anything else uses
            ``--system-prompt``.
        permission_mode: One of ``"bypassPermissions"``, ``"acceptEdits"``, or None.
        plan_mode_required: When True, bypass-permissions flag is suppressed
            (plan mode takes precedence over bypass for safety).
        settings_path: Path to a settings JSON file to propagate via
            ``--settings``.  Shell-quoted for safety.
        teammate_mode: Teammate execution mode (``"auto"``, ``"in_process"``,
            ``"tmux"``).  Forwarded as ``--teammate-mode`` so tmux teammates
            use the same mode as the leader.
        plugin_dirs: List of plugin directory paths.  Each is forwarded as a
            separate ``--plugin-dir <path>`` flag so inline plugins are
            visible inside teammate processes.
        extra_flags: Additional pre-built flag strings to append verbatim.
            Callers are responsible for quoting any values in these strings.

    Returns:
        List of CLI flag strings ready to be passed to :mod:`subprocess`.
    """
    flags: list[str] = []

    # --- 权限模式 ---------------------------------------------------
    # 为安全起见，计划模式优先于绕过权限。
    if not plan_mode_required:
        if permission_mode == "bypassPermissions":
            flags.append("--dangerously-skip-permissions")
        elif permission_mode == "acceptEdits":
            flags.extend(["--permission-mode", "acceptEdits"])

    # --- 模型覆盖 ----------------------------------------------------
    # "inherit" 表示通过 QUESTORHARNESS_MODEL 环境变量使用父进程的模型。
    if model and model != "inherit":
        flags.extend(["--model", shlex.quote(model)])

    # --- 系统提示词覆盖 ------------------------------------------
    # Agent 定义可以携带专用的工作者系统提示词。显式转发它，
    # 使子进程队友保留其角色/个性。
    if system_prompt:
        prompt_flag = "--append-system-prompt" if system_prompt_mode == "append" else "--system-prompt"
        flags.extend([prompt_flag, shlex.quote(system_prompt)])

    # --- 设置路径传递 ----------------------------------------
    # 确保队友加载与领导者进程相同的 settings JSON。
    if settings_path:
        flags.extend(["--settings", shlex.quote(settings_path)])

    # --- 插件目录 -----------------------------------------------
    # 每个启用的插件目录都会单独转发，使通过
    # --plugin-dir 加载的内联插件在队友中可用。
    for plugin_dir in plugin_dirs or []:
        flags.extend(["--plugin-dir", shlex.quote(plugin_dir)])

    # --- 队友模式传递 ----------------------------------------
    # 转发会话级队友模式，避免 tmux 生成的队友
    # 独立重新检测模式并可能选择不同模式。
    if teammate_mode:
        flags.extend(["--teammate-mode", shlex.quote(teammate_mode)])

    # --- 工具面（agent 定义的 tools / disallowed_tools）-----------------
    # 子进程 CLI 支持 --allowed-tools / --disallowed-tools；不下发就等于声明失效。
    if allowed_tools:
        flags.extend(["--allowed-tools", shlex.quote(",".join(allowed_tools))])
    if disallowed_tools:
        flags.extend(["--disallowed-tools", shlex.quote(",".join(disallowed_tools))])

    if extra_flags:
        flags.extend(extra_flags)

    return flags


def build_inherited_env_vars() -> dict[str, str]:
    """Build environment variables to forward to spawned teammates.

    Always includes ``QUESTORHARNESS_AGENT_TEAMS=1`` plus any provider/proxy
    vars that are set in the current process.

    Returns:
        Dict of env var name → value to merge into the subprocess environment.
    """
    env: dict[str, str] = {
        "QUESTORHARNESS_AGENT_TEAMS": "1",
        # 生成的 worker 应表现得像 worker，不应仅因父领导者
        # 设置了标志就递归进入协调器模式。
        "CLAUDE_CODE_COORDINATOR_MODE": "0",
    }

    for key in _TEAMMATE_ENV_VARS:
        value = os.environ.get(key)
        if value:
            env[key] = value

    return env


def is_tmux_available() -> bool:
    """Return True if the ``tmux`` binary is on PATH."""
    return shutil.which("tmux") is not None


def is_inside_tmux() -> bool:
    """Return True if the current process is running inside a tmux session."""
    return bool(os.environ.get("TMUX"))
