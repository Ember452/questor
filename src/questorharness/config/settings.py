"""Public settings surface.

Models and pure helpers live in ``settings_models``; environment overrides,
loading and persistence live in ``settings_loader``.
"""

from __future__ import annotations

from questorharness.config.settings_loader import (
    _apply_env_overrides,
    load_settings,
    save_settings,
)
from questorharness.config.settings_models import (
    CLAUDE_MODEL_ALIAS_OPTIONS,
    DockerSandboxSettings,
    ImageGenerationConfig,
    PathRuleConfig,
    PermissionSettings,
    ProviderProfile,
    ResolvedAuth,
    SandboxNetworkSettings,
    SandboxSettings,
    Settings,
    VisionModelConfig,
    WebSettings,
    auth_source_env_var_candidates,
    auth_source_provider_name,
    auth_source_uses_api_key,
    builtin_provider_profile_names,
    credential_storage_provider_name,
    default_auth_source_for_provider,
    default_provider_profiles,
    display_label_for_profile,
    display_model_setting,
    is_claude_family_provider,
    normalize_anthropic_model_name,
    resolve_auth_env_value,
    resolve_model_setting,
    strip_ansi_escape_sequences,
)

__all__ = [
    "CLAUDE_MODEL_ALIAS_OPTIONS",
    "DockerSandboxSettings",
    "ImageGenerationConfig",
    "PathRuleConfig",
    "PermissionSettings",
    "ProviderProfile",
    "ResolvedAuth",
    "SandboxNetworkSettings",
    "SandboxSettings",
    "Settings",
    "VisionModelConfig",
    "WebSettings",
    "_apply_env_overrides",
    "auth_source_env_var_candidates",
    "auth_source_provider_name",
    "auth_source_uses_api_key",
    "builtin_provider_profile_names",
    "credential_storage_provider_name",
    "default_auth_source_for_provider",
    "default_provider_profiles",
    "display_label_for_profile",
    "display_model_setting",
    "is_claude_family_provider",
    "load_settings",
    "normalize_anthropic_model_name",
    "resolve_model_setting",
    "save_settings",
    "strip_ansi_escape_sequences",
]
