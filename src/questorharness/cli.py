"""CLI entry point using typer."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

__version__ = "0.1.0"


from questorharness.cli_preview import (
    _build_dry_run_preview,
    _format_dry_run_preview,
)
from questorharness.providers.auth.profile_naming import default_credential_slot_for_profile


def _version_callback(value: bool) -> None:
    if value:
        print(f"questorharness {__version__}")
        raise typer.Exit()


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
# 子命令
# ---------------------------------------------------------------------------

auth_app = typer.Typer(name="auth", help="Manage authentication")

from questorharness.cli_autopilot import autopilot_app
from questorharness.cli_cron import cron_app
from questorharness.cli_mcp import mcp_app
from questorharness.cli_plugin import plugin_app

app.add_typer(mcp_app)
app.add_typer(plugin_app)
from questorharness.cli_config import config_app
from questorharness.cli_provider import provider_app

app.add_typer(auth_app)
app.add_typer(provider_app)
app.add_typer(config_app)
app.add_typer(cron_app)
app.add_typer(autopilot_app)


# ---- mcp 子命令 ----


# ---- 插件子命令 ----


# ---- 定时任务子命令 ----


# ---- 自动驾驶子命令 ----


# ---- 认证子命令 ----

# 提供商名称到交互提示可读标签的映射。
_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic (Claude API)",
    "anthropic_claude": "Claude subscription (Claude CLI)",
    "openai": "OpenAI / compatible",
    "openai_codex": "OpenAI Codex subscription (Codex CLI)",
    "copilot": "GitHub Copilot",
    "dashscope": "Alibaba DashScope",
    "bedrock": "AWS Bedrock",
    "vertex": "Google Vertex AI",
    "moonshot": "Moonshot (Kimi)",
    "gemini": "Google Gemini",
    "minimax": "MiniMax",
    "modelscope": "ModelScope",
}

_AUTH_SOURCE_LABELS: dict[str, str] = {
    "anthropic_api_key": "Anthropic API key",
    "openai_api_key": "OpenAI API key",
    "codex_subscription": "Codex subscription",
    "claude_subscription": "Claude subscription",
    "copilot_oauth": "GitHub Copilot OAuth",
    "dashscope_api_key": "DashScope API key",
    "bedrock_api_key": "Bedrock credentials",
    "vertex_api_key": "Vertex credentials",
    "moonshot_api_key": "Moonshot API key",
    "gemini_api_key": "Gemini API key",
    "minimax_api_key": "MiniMax API key",
    "modelscope_api_key": "ModelScope API key",
}


def _can_use_questionary() -> bool:
    """Return True when a real interactive terminal is available."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if sys.stdin is not sys.__stdin__ or sys.stdout is not sys.__stdout__:
        return False
    try:
        import questionary  # noqa: F401
    except ImportError:
        return False
    return True


def _select_with_questionary(
    title: str,
    options: list[tuple[str, str]],
    *,
    default_value: str | None = None,
) -> str:
    import questionary

    choices = [
        questionary.Choice(
            title=label,
            value=value,
            checked=(value == default_value),
        )
        for value, label in options
    ]
    result = questionary.select(title, choices=choices, default=default_value).ask()
    if result is None:
        raise typer.Abort()
    return str(result)


def _text_prompt(message: str, *, default: str = "") -> str:
    """Prompt for text input, preferring questionary in a real TTY."""
    if _can_use_questionary():
        import questionary

        result = questionary.text(message, default=default).ask()
        if result is None:
            raise typer.Abort()
        return str(result)
    return typer.prompt(message, default=default)


def _secret_prompt(message: str) -> str:
    """Prompt for secret text, preferring questionary in a real TTY."""
    if _can_use_questionary():
        import questionary

        result = questionary.password(message).ask()
        if result is None:
            raise typer.Abort()
        return str(result)
    return typer.prompt(message, hide_input=True)


def _confirm_prompt(message: str, *, default: bool = False) -> bool:
    """Prompt for a yes/no confirmation, preferring questionary in a real TTY."""
    if _can_use_questionary():
        import questionary

        result = questionary.confirm(message, default=default).ask()
        if result is None:
            raise typer.Abort()
        return bool(result)
    return bool(typer.confirm(message, default=default))


def _select_from_menu(
    title: str,
    options: list[tuple[str, str]],
    *,
    default_value: str | None = None,
) -> str:
    """Render a simple numbered picker and return the selected value."""
    if _can_use_questionary():
        return _select_with_questionary(title, options, default_value=default_value)
    print(title, flush=True)
    default_index = 1
    for index, (value, label) in enumerate(options, 1):
        marker = " (default)" if value == default_value else ""
        if value == default_value:
            default_index = index
        print(f"  {index}. {label}{marker}", flush=True)
    raw = typer.prompt("Choose", default=str(default_index))
    try:
        selected = options[int(raw) - 1]
    except (ValueError, IndexError):
        raise typer.BadParameter(f"Invalid selection: {raw}") from None
    return selected[0]


def _prompt_model_for_profile(profile) -> str:
    from questorharness.config.settings import (
        CLAUDE_MODEL_ALIAS_OPTIONS,
        display_model_setting,
        is_claude_family_provider,
    )

    current = display_model_setting(profile)
    if profile.allowed_models:
        if len(profile.allowed_models) == 1:
            return profile.allowed_models[0]
        options = [(value, value) for value in profile.allowed_models]
        return _select_from_menu("Choose a model setting:", options, default_value=current if current in profile.allowed_models else profile.allowed_models[0])
    if is_claude_family_provider(profile.provider):
        options = [(value, f"{label} - {description}") for value, label, description in CLAUDE_MODEL_ALIAS_OPTIONS]
        options.append(("__custom__", "Custom model ID"))
        selection = _select_from_menu(
            "Choose a model setting:",
            options,
            default_value=current if any(value == current for value, _, _ in CLAUDE_MODEL_ALIAS_OPTIONS) else "__custom__",
        )
        if selection != "__custom__":
            return selection
    return _text_prompt("Model", default=current).strip() or current


def _format_profile_choice_label(info: dict[str, object]) -> str:
    """Render a user-facing workflow label without leaking internal provider ids."""
    label = str(info["label"])
    state = "" if bool(info["configured"]) else f" ({info['auth_state']})"
    return f"{label}{state}"


def _styled_missing_suffix(info: dict[str, object]) -> tuple[str, str] | None:
    """Return a soft red missing-auth suffix for questionary titles."""
    if bool(info["configured"]):
        return None
    return (f" ({info['auth_state']})", "fg:#d3869b")


def _select_setup_workflow(
    statuses: dict[str, dict[str, object]],
    *,
    default_value: str | None = None,
) -> str:
    """Render the top-level `oh setup` workflow picker with richer hints."""
    hints = {
        "claude-api": ("Claude / Kimi / GLM / MiniMax", "fg:#7aa2f7"),
        "openai-compatible": ("OpenAI / OpenRouter", "fg:#9ece6a"),
    }

    if _can_use_questionary():
        import questionary

        choices = []
        for name, info in statuses.items():
            label = str(info["label"])
            hint = hints.get(name)
            missing = _styled_missing_suffix(info)
            if hint is None:
                if missing is None:
                    title = label
                else:
                    suffix, suffix_style = missing
                    title = [("", label), (suffix_style, suffix)]
            else:
                hint_text, hint_style = hint
                if missing is None:
                    title = [
                        ("", f"{label}  "),
                        (hint_style, hint_text),
                    ]
                else:
                    suffix, suffix_style = missing
                    title = [
                        ("", f"{label}  "),
                        (hint_style, hint_text),
                        ("", "  "),
                        (suffix_style, suffix.strip()),
                    ]
            choices.append(questionary.Choice(title=title, value=name, checked=(name == default_value)))

        result = questionary.select("Choose a provider workflow:", choices=choices, default=default_value).ask()
        if result is None:
            raise typer.Abort()
        return str(result)

    options: list[tuple[str, str]] = []
    for name, info in statuses.items():
        label = _format_profile_choice_label(info)
        hint = hints.get(name)
        if hint is not None:
            label = f"{label} ({hint[0]})"
        options.append((name, label))
    return _select_from_menu("Choose a provider workflow:", options, default_value=default_value)


def _prompt_api_key_for_profile(label: str) -> str:
    key = _secret_prompt(f"Enter API key for {label}").strip()
    if not key:
        raise typer.BadParameter("API key cannot be empty.")
    return key


def _configure_custom_profile_via_setup(manager) -> str:
    from questorharness.config.settings import ProviderProfile, default_auth_source_for_provider

    family = _select_from_menu(
        "Choose a compatible API family:",
        [
            ("anthropic", "Anthropic-compatible"),
            ("openai", "OpenAI-compatible"),
        ],
        default_value="anthropic",
    )
    default_name = f"custom-{family}"
    name = _text_prompt("Profile name", default=default_name).strip()
    if not name:
        raise typer.BadParameter("Profile name cannot be empty.")
    label = _text_prompt("Display label", default=name).strip() or name
    base_url = _text_prompt("Base URL", default="").strip()
    if not base_url:
        raise typer.BadParameter("Base URL cannot be empty.")

    auth_source = default_auth_source_for_provider(family, family)
    model = _text_prompt("Default model", default="").strip()
    if not model:
        raise typer.BadParameter("Default model cannot be empty.")

    profile = ProviderProfile(
        label=label,
        provider=family,
        api_format=family,
        auth_source=auth_source,
        default_model=model,
        last_model=model,
        base_url=base_url,
        credential_slot=default_credential_slot_for_profile(name, auth_source),
        allowed_models=[model],
    )
    manager.upsert_profile(name, profile)
    manager.store_profile_credential(name, "api_key", _prompt_api_key_for_profile(label))
    return name


def _ensure_preset_profile(
    manager,
    *,
    name: str,
    label: str,
    provider: str,
    api_format: str,
    auth_source: str,
    base_url: str | None,
    model: str,
    lock_model: bool,
) -> str:
    from questorharness.config.settings import ProviderProfile

    existing = manager.list_profiles().get(name)
    profile = ProviderProfile(
        label=label,
        provider=provider,
        api_format=api_format,
        auth_source=auth_source,
        default_model=model,
        last_model=model,
        base_url=base_url,
        credential_slot=default_credential_slot_for_profile(name, auth_source),
        allowed_models=[model] if lock_model else (existing.allowed_models if existing else []),
    )
    manager.upsert_profile(name, profile)
    return name


def _specialize_setup_target(manager, target: str) -> str:
    """Expand a top-level family choice into a concrete workflow profile."""
    from questorharness.config.settings import default_auth_source_for_provider

    if target == "claude-api":
        choice = _select_from_menu(
            "Choose an Anthropic-compatible provider:",
            [
                ("claude-api", "Claude official"),
                ("kimi-anthropic", "Moonshot Kimi"),
                ("glm-anthropic", "Zhipu GLM"),
                ("minimax-anthropic", "MiniMax"),
            ],
            default_value="claude-api",
        )
        if choice == "claude-api":
            return choice
        defaults = {
            "kimi-anthropic": ("Kimi (Anthropic-compatible)", "https://api.moonshot.cn/anthropic", "kimi-k2.5"),
            "glm-anthropic": ("GLM (Anthropic-compatible)", "", "glm-4.5"),
            "minimax-anthropic": ("MiniMax (Anthropic-compatible)", "", "MiniMax-M2.7"),
        }
        label, suggested_base_url, suggested_model = defaults[choice]
        base_url = _text_prompt("Base URL", default=suggested_base_url).strip()
        if not base_url:
            raise typer.BadParameter("Base URL cannot be empty.")
        model = _text_prompt("Model", default=suggested_model).strip()
        if not model:
            raise typer.BadParameter("Model cannot be empty.")
        return _ensure_preset_profile(
            manager,
            name=choice,
            label=label,
            provider="anthropic",
            api_format="anthropic",
            auth_source=default_auth_source_for_provider("anthropic", "anthropic"),
            base_url=base_url,
            model=model,
            lock_model=True,
        )

    if target == "openai-compatible":
        choice = _select_from_menu(
            "Choose an OpenAI-compatible provider:",
            [
                ("openai-compatible", "OpenAI official"),
                ("openrouter", "OpenRouter"),
            ],
            default_value="openai-compatible",
        )
        if choice == "openai-compatible":
            return choice
        base_url = _text_prompt("Base URL", default="https://openrouter.ai/api/v1").strip()
        if not base_url:
            raise typer.BadParameter("Base URL cannot be empty.")
        model = _text_prompt("Default model", default="").strip()
        if not model:
            raise typer.BadParameter("Default model cannot be empty.")
        return _ensure_preset_profile(
            manager,
            name="openrouter",
            label="OpenRouter",
            provider="openai",
            api_format="openai",
            auth_source=default_auth_source_for_provider("openai", "openai"),
            base_url=base_url,
            model=model,
            lock_model=False,
        )

    return target


def _ensure_profile_auth(manager, profile_name: str) -> None:
    from questorharness.config.settings import auth_source_provider_name, auth_source_uses_api_key
    from questorharness.providers.auth.flows import ApiKeyFlow

    profile = manager.list_profiles()[profile_name]
    if not auth_source_uses_api_key(profile.auth_source):
        _login_provider(auth_source_provider_name(profile.auth_source))
        return

    flow = ApiKeyFlow(
        provider=profile.provider,
        prompt_text=f"Enter API key for {profile.label}",
    )
    try:
        key = flow.run()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(1)
    manager.store_profile_credential(profile_name, "api_key", key)
    print(f"{profile.label} API key saved.", flush=True)


def _maybe_update_profile_auth(manager, profile_name: str) -> bool:
    """Ask whether to replace an already configured profile API key."""
    from questorharness.config.settings import auth_source_uses_api_key

    profile = manager.list_profiles()[profile_name]
    if not auth_source_uses_api_key(profile.auth_source):
        return False
    if not _confirm_prompt(f"Update API key for {profile.label}?", default=False):
        return False
    _ensure_profile_auth(manager, profile_name)
    return True


def _maybe_update_default_model_for_provider(provider: str) -> None:
    """Keep the active model in-family after switching auth providers."""
    from questorharness.providers.auth.auth_manager import AuthManager

    manager = AuthManager()
    profile_name = {
        "openai_codex": "codex",
        "anthropic_claude": "claude-subscription",
    }.get(provider)
    if profile_name is None:
        return
    profile = manager.list_profiles()[profile_name]
    model = profile.resolved_model.lower()
    target_model = None
    if provider == "openai_codex" and not model.startswith(("gpt-", "o1", "o3", "o4")):
        target_model = "gpt-5.4"
    elif provider == "anthropic_claude" and not model.startswith("claude-"):
        target_model = "sonnet"
    if not target_model:
        return
    manager.update_profile(profile_name, default_model=target_model, last_model=target_model)


def _bind_external_provider(provider: str) -> None:
    """Bind a provider to credentials managed by an external CLI."""
    from questorharness.providers.auth.external import (
        default_binding_for_provider,
        load_external_credential,
    )
    from questorharness.providers.auth.storage import store_external_binding

    binding = default_binding_for_provider(provider)
    try:
        credential = load_external_credential(
            binding,
            refresh_if_needed=(provider == "anthropic_claude"),
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        raise typer.Exit(1)

    profile_label = credential.profile_label or binding.profile_label
    store_external_binding(
        binding.__class__(
            provider=binding.provider,
            source_path=binding.source_path,
            source_kind=binding.source_kind,
            managed_by=binding.managed_by,
            profile_label=profile_label,
        )
    )

    _maybe_update_default_model_for_provider(provider)
    label = _PROVIDER_LABELS.get(provider, provider)
    profile_name = {
        "openai_codex": "codex",
        "anthropic_claude": "claude-subscription",
    }[provider]
    print(f"{label} bound from {credential.source_path}.", flush=True)
    print(f"Use `oh provider use {profile_name}` to activate it.", flush=True)


def _login_provider(provider: str) -> None:
    """Authenticate or bind the given provider."""
    from questorharness.providers.auth.flows import ApiKeyFlow
    from questorharness.providers.auth.auth_manager import AuthManager
    from questorharness.providers.auth.storage import store_credential

    manager = AuthManager()

    if provider == "copilot":
        _run_copilot_login()
        return

    if provider in ("openai_codex", "anthropic_claude"):
        _bind_external_provider(provider)
        return

    if provider in ("anthropic", "openai", "dashscope", "bedrock", "vertex", "moonshot", "gemini", "minimax", "modelscope"):
        label = _PROVIDER_LABELS.get(provider, provider)
        flow = ApiKeyFlow(provider=provider, prompt_text=f"Enter your {label} API key")
        try:
            key = flow.run()
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise typer.Exit(1)
        store_credential(provider, "api_key", key)
        try:
            manager.store_credential(provider, "api_key", key)
        except Exception:
            pass
        print(f"{label} API key saved.", flush=True)
        return

    print(f"Unknown provider: {provider!r}. Known: {', '.join(_PROVIDER_LABELS)}", file=sys.stderr)
    raise typer.Exit(1)


@app.command("setup")
def setup_cmd(
    profile: str | None = typer.Argument(None, help="Provider profile name to configure"),
) -> None:
    """Unified setup flow: choose workflow, authenticate if needed, then set the model."""
    from questorharness.config.settings import display_model_setting
    from questorharness.providers.auth.auth_manager import AuthManager

    manager = AuthManager()
    statuses = manager.get_profile_statuses()
    if not statuses:
        print("No provider profiles available.", file=sys.stderr)
        raise typer.Exit(1)

    target = profile
    if target is None:
        target = _select_setup_workflow(
            statuses,
            default_value=manager.get_active_profile(),
        )

    target = _specialize_setup_target(manager, target)
    manager = AuthManager()
    statuses = manager.get_profile_statuses()

    if target not in statuses:
        print(f"Unknown provider profile: {target!r}", file=sys.stderr)
        raise typer.Exit(1)

    info = statuses[target]
    if not info["configured"]:
        source_label = _AUTH_SOURCE_LABELS.get(info["auth_source"], info["auth_source"])
        print(f"{info['label']} requires {source_label}.", flush=True)
        _ensure_profile_auth(manager, target)
        manager = AuthManager()
    else:
        if _maybe_update_profile_auth(manager, target):
            manager = AuthManager()

    profile_obj = manager.list_profiles()[target]
    model_setting = _prompt_model_for_profile(profile_obj)
    if model_setting.lower() == "default":
        manager.update_profile(target, last_model="")
    else:
        manager.update_profile(target, last_model=model_setting)
    manager.use_profile(target)

    updated = manager.list_profiles()[target]
    print(
        "Setup complete:\n"
        f"- profile: {target}\n"
        f"- provider: {updated.provider}\n"
        f"- auth_source: {updated.auth_source}\n"
        f"- model: {display_model_setting(updated)}",
        flush=True,
    )


@auth_app.command("login")
def auth_login(
    provider: Optional[str] = typer.Argument(None, help="Provider name (anthropic, openai, copilot, …)"),
) -> None:
    """Interactively authenticate with a provider.

    Run without arguments to choose a provider from a menu.
    Supported providers: anthropic, anthropic_claude, openai, openai_codex, copilot, dashscope, bedrock, vertex, moonshot, minimax, modelscope.
    """
    if provider is None:
        print("Select a provider to authenticate:", flush=True)
        labels = list(_PROVIDER_LABELS.items())
        for i, (name, label) in enumerate(labels, 1):
            print(f"  {i}. {label} [{name}]", flush=True)
        raw = typer.prompt("Enter number or provider name", default="1")
        try:
            idx = int(raw.strip()) - 1
            if 0 <= idx < len(labels):
                provider = labels[idx][0]
            else:
                print("Invalid selection.", file=sys.stderr)
                raise typer.Exit(1)
        except ValueError:
            provider = raw.strip()

    provider = provider.lower()
    _login_provider(provider)


@auth_app.command("status")
def auth_status_cmd() -> None:
    """Show authentication source and provider profile status."""
    from questorharness.providers.auth.auth_manager import AuthManager

    manager = AuthManager()
    auth_sources = manager.get_auth_source_statuses()
    profiles = manager.get_profile_statuses()

    print("Auth sources:")
    print(f"{'Source':<24} {'State':<14} {'Origin':<10} Active")
    print("-" * 60)
    for name, info in auth_sources.items():
        label = _AUTH_SOURCE_LABELS.get(name, name)
        active_str = "<-- active" if info["active"] else ""
        print(f"{label:<24} {info['state']:<14} {info['source']:<10} {active_str}")
        if info.get("detail"):
            print(f"  detail: {info['detail']}")

    print()
    print("Provider profiles:")
    print(f"{'Profile':<20} {'Provider':<18} {'Auth source':<22} {'State':<12} Active")
    print("-" * 92)
    for name, info in profiles.items():
        status_str = "ready" if info["configured"] else info.get("auth_state", "missing auth")
        active_str = "<-- active" if info["active"] else ""
        print(f"{name:<20} {info['provider']:<18} {info['auth_source']:<22} {status_str:<12} {active_str}")


@auth_app.command("logout")
def auth_logout(
    provider: Optional[str] = typer.Argument(None, help="Provider to log out (default: active provider)"),
) -> None:
    """Clear stored authentication for a provider."""
    from questorharness.providers.auth.auth_manager import AuthManager

    manager = AuthManager()
    if provider is None:
        target = manager.get_active_profile()
        manager.clear_profile_credential(target)
        print(f"Authentication cleared for profile: {target}", flush=True)
        return
    manager.clear_credential(provider)
    print(f"Authentication cleared for provider: {provider}", flush=True)


@auth_app.command("switch")
def auth_switch(
    provider: str = typer.Argument(..., help="Auth source or profile to activate"),
) -> None:
    """Switch the auth source for the active profile, or use a profile by name."""
    from questorharness.providers.auth.auth_manager import AuthManager

    manager = AuthManager()
    try:
        manager.switch_provider(provider)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(1)
    print(f"Switched auth/profile to: {provider}", flush=True)


# ---------------------------------------------------------------------------
# Copilot 登录辅助函数（保留为具名函数以复用并兼容旧代码）
# ---------------------------------------------------------------------------


def _run_copilot_login() -> None:
    """Run the GitHub Copilot device-code flow and persist the result."""
    from questorharness.providers.auth.flows import DeviceCodeFlow
    from questorharness.providers.llm.copilot_auth import save_copilot_auth

    print("Select GitHub deployment type:", flush=True)
    print("  1. GitHub.com (public)", flush=True)
    print("  2. GitHub Enterprise (data residency / self-hosted)", flush=True)
    choice = typer.prompt("Enter choice", default="1")

    enterprise_url: str | None = None
    github_domain = "github.com"

    if choice.strip() == "2":
        raw_url = typer.prompt("Enter your GitHub Enterprise URL or domain (e.g. company.ghe.com)")
        domain = raw_url.replace("https://", "").replace("http://", "").rstrip("/")
        if not domain:
            print("Error: domain cannot be empty.", file=sys.stderr, flush=True)
            raise typer.Exit(1)
        enterprise_url = domain
        github_domain = domain

    print(flush=True)
    flow = DeviceCodeFlow(github_domain=github_domain, enterprise_url=enterprise_url)
    try:
        token = flow.run()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        raise typer.Exit(1)

    save_copilot_auth(token, enterprise_url=enterprise_url)
    print("GitHub Copilot authenticated successfully.", flush=True)
    if enterprise_url:
        print(f"  Enterprise domain: {enterprise_url}", flush=True)
    print(flush=True)
    print("To use Copilot as the provider, run:", flush=True)
    print("  oh provider use copilot", flush=True)


@auth_app.command("copilot-login")
def auth_copilot_login() -> None:
    """Authenticate with GitHub Copilot via device flow (alias for 'oh auth login copilot')."""
    _run_copilot_login()


@auth_app.command("codex-login")
def auth_codex_login() -> None:
    """Bind QuestorHarness to a local Codex CLI subscription session."""
    _bind_external_provider("openai_codex")


@auth_app.command("claude-login")
def auth_claude_login() -> None:
    """Bind QuestorHarness to a local Claude CLI subscription session."""
    _bind_external_provider("anthropic_claude")


@auth_app.command("copilot-logout")
def auth_copilot_logout() -> None:
    """Remove stored GitHub Copilot authentication."""
    from questorharness.providers.llm.copilot_auth import clear_github_token

    clear_github_token()
    print("Copilot authentication cleared.")


# ---- 配置子命令 ----


# ---- 提供商子命令 ----


# ---------------------------------------------------------------------------
# 主命令
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
    allowed_tools: Optional[list[str]] = typer.Option(
        None,
        "--allowed-tools",
        help="Comma or space-separated list of tool names to allow",
        rich_help_panel="Permissions",
    ),
    disallowed_tools: Optional[list[str]] = typer.Option(
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
    mcp_config: Optional[list[str]] = typer.Option(
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
    backend_only: bool = typer.Option(
        False,
        "--backend-only",
        help="Run the structured backend host for the React terminal UI",
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
        logging.basicConfig(level=lvl, format="%(asctime)s [%(name)s] %(levelname)s %(message)s", stream=sys.stderr)

    if dangerously_skip_permissions:
        permission_mode = "full_auto"

    # 将 --theme 覆盖项应用到设置
    if theme:
        from questorharness.config.settings import load_settings, save_settings

        settings = load_settings()
        settings.theme = theme
        save_settings(settings)

    from questorharness.bootstrap.hosts.app import run_print_mode, run_repl, run_task_worker

    if dry_run and (continue_session or resume is not None):
        print("Error: --dry-run does not support --continue/--resume yet.", file=sys.stderr)
        raise typer.Exit(1)

    if dry_run:
        prompt = print_mode.strip() if print_mode is not None else None
        if print_mode is not None and not prompt:
            print("Error: -p/--print requires a prompt value, e.g. -p 'your prompt'", file=sys.stderr)
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
                print(f"  {i}. [{s['session_id']}] {s.get('summary', '?')[:50]} ({s['message_count']} msgs)")
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
                backend_only=backend_only,
                base_url=base_url,
                system_prompt=system_prompt,
                api_key=api_key,
                restore_messages=session_data.get("messages"),
                restore_tool_metadata=session_data.get("tool_metadata"),
                permission_mode=permission_mode,
                api_format=api_format,
                effort=effort,
            )
        )
        return

    if print_mode is not None:
        prompt = print_mode.strip()
        if not prompt:
            print("Error: -p/--print requires a prompt value, e.g. -p 'your prompt'", file=sys.stderr)
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
            )
        )
        return

    asyncio.run(
        run_repl(
            prompt=None,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            backend_only=backend_only,
            base_url=base_url,
            system_prompt=system_prompt,
            api_key=api_key,
            api_format=api_format,
            permission_mode=permission_mode,
            effort=effort,
        )
    )

# questor: allow R2 -- 1190 lines until W8 splits this file
# questor: allow R8 -- refactor the offenders in W8
