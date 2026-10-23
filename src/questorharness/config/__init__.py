"""Configuration system for QuestorHarness.

Provides settings management and API key handling. Path resolution lives in
``questorharness.platform.paths``.
"""

from questorharness.config.settings import (
    ProviderProfile,
    Settings,
    auth_source_provider_name,
    default_auth_source_for_provider,
    default_provider_profiles,
    load_settings,
    save_settings,
)

__all__ = [
    "ProviderProfile",
    "Settings",
    "auth_source_provider_name",
    "default_auth_source_for_provider",
    "default_provider_profiles",
    "load_settings",
    "save_settings",
]
