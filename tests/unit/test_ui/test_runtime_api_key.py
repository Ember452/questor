"""Tests for build_runtime auth failure handling."""

from __future__ import annotations

import pytest

from questorharness.config.settings import load_settings
from questorharness.ui.runtime import _resolve_api_client_from_settings, build_runtime


@pytest.mark.asyncio
async def test_build_runtime_exits_cleanly_when_auth_resolution_fails(monkeypatch):
    """build_runtime should raise SystemExit(1) — not ValueError — when auth resolution fails."""

    def fake_resolve_auth(self):
        raise ValueError("No credentials found")

    monkeypatch.setattr("questorharness.config.settings.Settings.resolve_auth", fake_resolve_auth)

    with pytest.raises(SystemExit, match="1"):
        await build_runtime(active_profile="claude-api")


@pytest.mark.asyncio
async def test_build_runtime_exits_cleanly_for_openai_format(monkeypatch):
    """Same check for the openai-compatible path."""

    def fake_resolve_auth(self):
        raise ValueError("No credentials found")

    monkeypatch.setattr("questorharness.config.settings.Settings.resolve_auth", fake_resolve_auth)

    with pytest.raises(SystemExit, match="1"):
        await build_runtime(active_profile="openai-compatible", api_format="openai")


def test_resolve_api_client_preserves_env_provider_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("QUESTORHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("QUESTORHARNESS_PROVIDER", "openai")
    monkeypatch.setenv("QUESTORHARNESS_API_FORMAT", "openai")
    monkeypatch.setenv("QUESTORHARNESS_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("QUESTORHARNESS_MODEL", "deepseek-chat")
    monkeypatch.setenv("QUESTORHARNESS_OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("QUESTORHARNESS_PROFILE", raising=False)

    client = _resolve_api_client_from_settings(load_settings())

    assert type(client).__name__ == "OpenAICompatibleClient"
    assert "api.deepseek.com" in str(client._client.base_url)


@pytest.mark.asyncio
async def test_build_runtime_reports_subscription_auth_setup(monkeypatch, tmp_path, capsys):
    """Subscription profiles should not be reported as missing API keys."""
    monkeypatch.setenv("QUESTORHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="1"):
        await build_runtime(active_profile="claude-subscription")

    captured = capsys.readouterr()
    assert "subscription auth, not an API key" in captured.err
    assert "oh auth claude-login" in captured.err
    assert "oh provider use claude-subscription" in captured.err
    assert "No API key configured" not in captured.err
