"""The ``auth`` subcommand group and the provider binding it drives.

Login, logout, status and switch are thin; the weight here is binding an external
provider and running the subscription logins, which the setup wizard also calls.
"""

from __future__ import annotations

import sys

import typer

from questorharness.bootstrap.cli.cli_prompts import (
    _AUTH_SOURCE_LABELS,
    _PROVIDER_LABELS,
)

auth_app = typer.Typer(name="auth", help="Manage authentication")


@auth_app.command("login")
def auth_login(
    provider: str | None = typer.Argument(None, help="Provider name (anthropic, openai, copilot, …)"),
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
    provider: str | None = typer.Argument(None, help="Provider to log out (default: active provider)"),
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
    from questorharness.providers.auth.auth_manager import AuthManager
    from questorharness.providers.auth.flows import ApiKeyFlow
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
