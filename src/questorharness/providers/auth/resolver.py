"""Credential resolution for the active provider profile.

This lives in ``providers`` because it reads keyring entries, external auth
bindings and credential files. Keeping it on ``Settings`` made ``config``
depend on ``providers``, which in turn made a layered contract impossible.

Callers pass the settings they already hold; nothing here loads configuration
on its own.
"""

from __future__ import annotations

import os

from questorharness.config.settings import (
    ResolvedAuth,
    Settings,
    auth_source_provider_name,
    credential_storage_provider_name,
    default_auth_source_for_provider,
    resolve_auth_env_value,
)
from questorharness.providers.auth.external import (
    is_third_party_anthropic_endpoint,
    load_external_credential,
)
from questorharness.providers.auth.storage import load_credential, load_external_binding

__all__ = ["resolve_api_key", "resolve_auth"]


def resolve_api_key(settings: Settings) -> str:
    """Resolve API key with precedence: instance value > env var > empty.

    For ``copilot`` api_format the key is managed separately via
    ``oh auth copilot-login`` and this function is not called.

    Returns the API key string. Raises ValueError if no key is found.
    """
    profile_name, profile = settings.resolve_profile()
    del profile_name
    if profile.provider == "openai_codex":
        return resolve_auth(settings).value
    if profile.provider == "anthropic_claude":
        raise ValueError(
            "Current provider uses Anthropic auth tokens instead of API keys. "
            "Use resolve_auth() for runtime credential resolution."
        )
    # Copilot 格式自行管理认证；跳过常规密钥解析。
    if profile.api_format == "copilot":
        return "copilot-managed"

    if settings.api_key:
        return settings.api_key

    env_resolved = resolve_auth_env_value(profile.auth_source)
    if env_resolved:
        _, env_value = env_resolved
        return env_value

    raise ValueError(
        "No API key found. Set an QUESTORHARNESS_* provider API key "
        "(preferred) or the matching native provider environment variable, "
        "or configure api_key in ~/.questorharness/settings.json"
    )


def resolve_auth(settings: Settings) -> ResolvedAuth:
    """Resolve auth for the current provider, including subscription bridges."""
    profile_name, profile = settings.resolve_profile()
    provider = profile.provider.strip()
    auth_source = profile.auth_source.strip() or default_auth_source_for_provider(provider, profile.api_format)
    if auth_source in {"codex_subscription", "claude_subscription"}:
        env_auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
        if auth_source == "claude_subscription" and env_auth_token:
            return ResolvedAuth(
                provider=provider,
                auth_kind="oauth",
                value=env_auth_token,
                source="env:ANTHROPIC_AUTH_TOKEN",
                state="configured",
            )

        if auth_source == "claude_subscription" and is_third_party_anthropic_endpoint(profile.base_url):
            raise ValueError(
                "Claude subscription auth only supports direct Anthropic/Claude endpoints. "
                "Use an API-key-backed Anthropic-compatible profile for third-party base URLs."
            )
        binding = load_external_binding(auth_source_provider_name(auth_source))
        if binding is None:
            raise ValueError(
                f"No external auth binding found for {auth_source}. Run 'oh auth "
                f"{'codex-login' if auth_source == 'codex_subscription' else 'claude-login'}' first."
            )
        credential = load_external_credential(
            binding,
            refresh_if_needed=(auth_source == "claude_subscription"),
        )
        return ResolvedAuth(
            provider=provider,
            auth_kind=credential.auth_kind,
            value=credential.value,
            source=f"external:{credential.source_path}",
            state="configured",
        )

    if auth_source == "copilot_oauth":
        return ResolvedAuth(
            provider="copilot",
            auth_kind="oauth_device",
            value="copilot-managed",
            source="copilot",
            state="configured",
        )

    storage_provider = auth_source_provider_name(auth_source)

    if profile.credential_slot:
        scoped_storage_provider = f"profile:{profile.credential_slot}"
        scoped = load_credential(scoped_storage_provider, "api_key", use_keyring=False)
        if scoped is None:
            scoped = load_credential(scoped_storage_provider, "api_key")
        if scoped:
            return ResolvedAuth(
                provider=provider or auth_source_provider_name(auth_source),
                auth_kind="api_key",
                value=scoped,
                source=f"file:{scoped_storage_provider}",
                state="configured",
            )

    storage_provider = credential_storage_provider_name(profile_name, profile)

    env_resolved = resolve_auth_env_value(auth_source)
    if env_resolved:
        env_var, env_value = env_resolved
        return ResolvedAuth(
            provider=provider or storage_provider,
            auth_kind="api_key",
            value=env_value,
            source=f"env:{env_var}",
            state="configured",
        )

    explicit_key = "" if profile.credential_slot else settings.api_key
    if explicit_key:
        return ResolvedAuth(
            provider=provider or storage_provider,
            auth_kind="api_key",
            value=explicit_key,
            source="settings_or_env",
            state="configured",
        )

    stored = load_credential(storage_provider, "api_key")
    if stored:
        return ResolvedAuth(
            provider=provider or auth_source_provider_name(auth_source),
            auth_kind="api_key",
            value=stored,
            source=f"file:{storage_provider}",
            state="configured",
        )

    raise ValueError(
        f"No credentials found for auth source '{auth_source}'. "
        "Configure the matching provider or environment variable first."
    )
