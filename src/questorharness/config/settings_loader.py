"""Settings loading, environment overrides and persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from questorharness.config.settings_models import (
    Settings,
    _profile_from_flat_settings,
    default_auth_source_for_provider,
    resolve_auth_env_value,
    strip_ansi_escape_sequences,
)
from questorharness.platform.io import atomic_write_text
from questorharness.platform.locking import exclusive_file_lock


def _apply_env_overrides(settings: Settings) -> Settings:
    """Apply supported environment variable overrides over loaded settings.

    Provider-scoped env vars (``ANTHROPIC_BASE_URL``, ``ANTHROPIC_MODEL``,
    ``OPENAI_BASE_URL``) only apply when the active profile does *not*
    explicitly configure the corresponding field.  ``QUESTORHARNESS_*`` env vars
    always override (explicit user intent).
    """
    updates: dict[str, Any] = {}

    # 解析当前活动配置档，以检查显式设置。
    _, active_profile = settings.resolve_profile()
    profile_has_base_url = active_profile.base_url is not None
    profile_explicit_model = (active_profile.last_model or "").strip()
    profile_has_explicit_model = bool(profile_explicit_model) and profile_explicit_model.lower() not in {"", "default"}

    # --- 模型 ---
    questorharness_model = os.environ.get("QUESTORHARNESS_MODEL")
    if questorharness_model:
        updates["model"] = strip_ansi_escape_sequences(questorharness_model)
    elif not profile_has_explicit_model:
        anthropic_model = os.environ.get("ANTHROPIC_MODEL")
        if anthropic_model:
            updates["model"] = strip_ansi_escape_sequences(anthropic_model)

    # --- base_url ---
    questorharness_base = os.environ.get("QUESTORHARNESS_BASE_URL")
    if questorharness_base:
        updates["base_url"] = questorharness_base
    elif not profile_has_base_url:
        generic_base = os.environ.get("ANTHROPIC_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        if generic_base:
            updates["base_url"] = generic_base

    max_tokens = os.environ.get("QUESTORHARNESS_MAX_TOKENS")
    if max_tokens:
        updates["max_tokens"] = int(max_tokens)

    timeout = os.environ.get("QUESTORHARNESS_TIMEOUT")
    if timeout:
        updates["timeout"] = float(timeout)

    max_turns = os.environ.get("QUESTORHARNESS_MAX_TURNS")
    if max_turns:
        updates["max_turns"] = int(max_turns)

    context_window_tokens = os.environ.get("QUESTORHARNESS_CONTEXT_WINDOW_TOKENS")
    if context_window_tokens:
        updates["context_window_tokens"] = int(context_window_tokens)

    auto_compact_threshold_tokens = os.environ.get("QUESTORHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS")
    if auto_compact_threshold_tokens:
        updates["auto_compact_threshold_tokens"] = int(auto_compact_threshold_tokens)

    provider = os.environ.get("QUESTORHARNESS_PROVIDER")
    api_format = os.environ.get("QUESTORHARNESS_API_FORMAT")
    env_auth_source = active_profile.auth_source
    if provider or api_format:
        env_auth_source = default_auth_source_for_provider(
            provider or active_profile.provider,
            api_format or active_profile.api_format,
        )

    env_resolved = resolve_auth_env_value(env_auth_source)
    if env_resolved:
        _, api_key = env_resolved
        updates["api_key"] = api_key

    if api_format:
        updates["api_format"] = api_format

    if provider:
        updates["provider"] = provider

    sandbox_enabled = os.environ.get("QUESTORHARNESS_SANDBOX_ENABLED")
    sandbox_fail = os.environ.get("QUESTORHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE")
    sandbox_backend = os.environ.get("QUESTORHARNESS_SANDBOX_BACKEND")
    sandbox_docker_image = os.environ.get("QUESTORHARNESS_SANDBOX_DOCKER_IMAGE")
    sandbox_updates: dict[str, Any] = {}
    if sandbox_enabled is not None:
        sandbox_updates["enabled"] = _parse_bool_env(sandbox_enabled)
    if sandbox_fail is not None:
        sandbox_updates["fail_if_unavailable"] = _parse_bool_env(sandbox_fail)
    if sandbox_backend is not None:
        sandbox_updates["backend"] = sandbox_backend
    if sandbox_docker_image is not None:
        sandbox_updates["docker"] = settings.sandbox.docker.model_copy(
            update={"image": sandbox_docker_image}
        )
    if sandbox_updates:
        updates["sandbox"] = settings.sandbox.model_copy(update=sandbox_updates)

    web_updates: dict[str, Any] = {}
    web_proxy = os.environ.get("QUESTORHARNESS_WEB_PROXY")
    if web_proxy:
        web_updates["proxy"] = web_proxy
    web_resolution_mode = os.environ.get("QUESTORHARNESS_WEB_RESOLUTION_MODE")
    if web_resolution_mode:
        web_updates["resolution_mode"] = web_resolution_mode
    web_synthetic_dns_cidrs = os.environ.get("QUESTORHARNESS_WEB_SYNTHETIC_DNS_CIDRS")
    if web_synthetic_dns_cidrs:
        web_updates["synthetic_dns_cidrs"] = [
            entry.strip()
            for entry in web_synthetic_dns_cidrs.split(",")
            if entry.strip()
        ]
    if web_updates:
        updates["web"] = settings.web.model_copy(update=web_updates)

    if not updates:
        return settings
    return settings.model_copy(update=updates)


def _parse_bool_env(value: str) -> bool:
    """Parse a boolean environment override."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from config file, merging with defaults.

    Args:
        config_path: Path to settings.json. If None, uses the default location.

    Returns:
        Settings instance with file values merged over defaults.
    """
    if config_path is None:
        from questorharness.platform.paths import get_config_file_path

        config_path = get_config_file_path()

    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
        settings = Settings.model_validate(raw)
        env_profile = os.environ.get("QUESTORHARNESS_PROFILE")
        if env_profile:
            settings = settings.model_copy(update={"active_profile": env_profile.strip()})
        if "profiles" not in raw or "active_profile" not in raw:
            profile_name, profile = _profile_from_flat_settings(settings)
            merged_profiles = settings.merged_profiles()
            merged_profiles[profile_name] = profile
            settings = settings.model_copy(
                update={
                    "active_profile": profile_name,
                    "profiles": merged_profiles,
                }
            )
        return _apply_env_overrides(settings.materialize_active_profile())

    settings = Settings()
    env_profile = os.environ.get("QUESTORHARNESS_PROFILE")
    if env_profile:
        settings = settings.model_copy(update={"active_profile": env_profile.strip()})
    return _apply_env_overrides(settings.materialize_active_profile())


def save_settings(settings: Settings, config_path: Path | None = None) -> None:
    """Persist settings to the config file.

    Args:
        settings: Settings instance to save.
        config_path: Path to write. If None, uses the default location.
    """
    if config_path is None:
        from questorharness.platform.paths import get_config_file_path

        config_path = get_config_file_path()

    settings = settings.sync_active_profile_from_flat_fields().materialize_active_profile()
    lock_path = config_path.with_suffix(config_path.suffix + ".lock")
    with exclusive_file_lock(lock_path):
        atomic_write_text(
            config_path,
            settings.model_dump_json(indent=2) + "\n",
        )
