"""Naming helpers for provider profiles used by the CLI."""

from __future__ import annotations

from questorharness.config.settings import auth_source_uses_api_key, builtin_provider_profile_names

__all__ = ["default_credential_slot_for_profile"]


def default_credential_slot_for_profile(name: str, auth_source: str) -> str | None:
    """Return the credential slot a custom profile should default to, if any."""
    if name in builtin_provider_profile_names():
        return None
    if not auth_source_uses_api_key(auth_source):
        return None
    return name
