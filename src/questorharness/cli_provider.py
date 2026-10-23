"""``questorharness provider`` command group."""

from __future__ import annotations

import sys

import typer

from questorharness.providers.auth.manager import AuthManager
from questorharness.providers.auth.profile_naming import default_credential_slot_for_profile

provider_app = typer.Typer(name="provider", help="Manage provider profiles")


@provider_app.command("list")
def provider_list() -> None:
    """List configured provider profiles."""
    statuses = AuthManager().get_profile_statuses()
    for name, info in statuses.items():
        marker = "*" if info["active"] else " "
        configured = "ready" if info["configured"] else "missing auth"
        base = info["base_url"] or "(default)"
        print(f"{marker} {name}: {info['label']} [{configured}]")
        print(f"    auth={info['auth_source']} model={info['model']} base_url={base}")


@provider_app.command("use")
def provider_use(
    name: str = typer.Argument(..., help="Provider profile name"),
) -> None:
    """Activate a provider profile."""
    from questorharness.providers.auth.manager import AuthManager

    manager = AuthManager()
    try:
        manager.use_profile(name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(1)
    print(f"Activated provider profile: {name}", flush=True)


@provider_app.command("add")
def provider_add(
    name: str = typer.Argument(..., help="Provider profile name"),
    label: str = typer.Option(..., "--label", help="Display label"),
    provider: str = typer.Option(..., "--provider", help="Runtime provider id"),
    api_format: str = typer.Option(..., "--api-format", help="API format"),
    auth_source: str = typer.Option(..., "--auth-source", help="Auth source name"),
    model: str = typer.Option(..., "--model", help="Default model"),
    base_url: str | None = typer.Option(None, "--base-url", help="Optional base URL"),
    credential_slot: str | None = typer.Option(None, "--credential-slot", help="Optional profile-specific credential slot"),
    api_key: str | None = typer.Option(None, "--api-key", help="Set the profile API key"),
    allowed_models: list[str] | None = typer.Option(None, "--allowed-model", help="Allowed model values for this profile"),
    context_window_tokens: int | None = typer.Option(None, "--context-window-tokens", help="Optional context window override for auto-compact"),
    auto_compact_threshold_tokens: int | None = typer.Option(None, "--auto-compact-threshold-tokens", help="Optional explicit auto-compact threshold override"),
) -> None:
    """Create a provider profile."""
    from questorharness.config.settings import ProviderProfile
    from questorharness.providers.auth.manager import AuthManager

    manager = AuthManager()
    manager.upsert_profile(
        name,
        ProviderProfile(
            label=label,
            provider=provider,
            api_format=api_format,
            auth_source=auth_source,
            default_model=model,
            last_model=model,
            base_url=base_url,
            credential_slot=credential_slot or default_credential_slot_for_profile(name, auth_source),
            allowed_models=allowed_models or ([model] if credential_slot or default_credential_slot_for_profile(name, auth_source) else []),
            context_window_tokens=context_window_tokens,
            auto_compact_threshold_tokens=auto_compact_threshold_tokens,
        ),
    )
    if api_key is not None:
        manager = AuthManager()
        manager.store_profile_credential(name, "api_key", api_key)
        print(f"Saved provider profile: {name} (API key set)", flush=True)
    else:
        print(f"Saved provider profile: {name}", flush=True)


@provider_app.command("edit")
def provider_edit(
    name: str = typer.Argument(..., help="Provider profile name"),
    label: str | None = typer.Option(None, "--label", help="Display label"),
    provider: str | None = typer.Option(None, "--provider", help="Runtime provider id"),
    api_format: str | None = typer.Option(None, "--api-format", help="API format"),
    auth_source: str | None = typer.Option(None, "--auth-source", help="Auth source name"),
    model: str | None = typer.Option(None, "--model", help="Default model"),
    base_url: str | None = typer.Option(None, "--base-url", help="Optional base URL"),
    credential_slot: str | None = typer.Option(None, "--credential-slot", help="Optional profile-specific credential slot"),
    api_key: str | None = typer.Option(None, "--api-key", help="Replace the profile API key"),
    allowed_models: list[str] | None = typer.Option(None, "--allowed-model", help="Allowed model values for this profile"),
    context_window_tokens: int | None = typer.Option(None, "--context-window-tokens", help="Optional context window override for auto-compact"),
    auto_compact_threshold_tokens: int | None = typer.Option(None, "--auto-compact-threshold-tokens", help="Optional explicit auto-compact threshold override"),
) -> None:
    """Edit a provider profile."""
    from questorharness.providers.auth.manager import AuthManager

    manager = AuthManager()
    try:
        manager.update_profile(
            name,
            label=label,
            provider=provider,
            api_format=api_format,
            auth_source=auth_source,
            default_model=model,
            last_model=model,
            base_url=base_url,
            credential_slot=credential_slot,
            allowed_models=allowed_models,
            context_window_tokens=context_window_tokens,
            auto_compact_threshold_tokens=auto_compact_threshold_tokens,
        )
        if api_key is not None:
            manager = AuthManager()
            manager.store_profile_credential(name, "api_key", api_key)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(1)
    if api_key is not None:
        print(f"Updated provider profile: {name} (API key replaced)", flush=True)
    else:
        print(f"Updated provider profile: {name}", flush=True)


@provider_app.command("remove")
def provider_remove(
    name: str = typer.Argument(..., help="Provider profile name"),
) -> None:
    """Remove a provider profile."""
    from questorharness.providers.auth.manager import AuthManager

    manager = AuthManager()
    try:
        manager.remove_profile(name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(1)
    print(f"Removed provider profile: {name}", flush=True)

# questor: allow R7 -- until W8 adds the mirror test
