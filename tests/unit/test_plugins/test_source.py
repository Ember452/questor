"""The plugin discovery port: the null source and the idempotent wiring."""

from __future__ import annotations

import pytest

from questorharness.capabilities.skills import loader
from questorharness.plugins.source import NullPluginSource, ensure_plugin_source


def test_null_source_finds_nothing(tmp_path) -> None:
    source = NullPluginSource()
    assert source.load(object(), tmp_path, extra_roots=None) == []


def test_ensure_plugin_source_is_idempotent_and_wires_once() -> None:
    first = loader._plugin_source
    ensure_plugin_source()
    wired = loader._plugin_source
    assert wired is not None
    ensure_plugin_source()
    assert loader._plugin_source is wired
    # Restore whatever the session fixture had wired so ordering never matters.
    loader._plugin_source = first


def test_project_skill_load_fails_fast_without_a_source(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(loader, "_plugin_source", None)
    with pytest.raises(loader.PluginSourceNotConfigured):
        loader.load_skill_registry(tmp_path)
