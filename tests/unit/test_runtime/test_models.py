"""Mirror test for ``runtime/bridge/models.py`` (plan 01, R7)."""

from __future__ import annotations

import dataclasses

import pytest

from questorharness.runtime.bridge.models import (
    DEFAULT_SESSION_TIMEOUT_MS,
    BridgeConfig,
    WorkData,
    WorkSecret,
)


def test_work_types_are_immutable_value_objects() -> None:
    work = WorkData(type="session", id="abc")
    secret = WorkSecret(version=1, session_ingress_token="tok", api_base_url="https://x")

    assert (work.type, work.id) == ("session", "abc")
    assert (secret.version, secret.session_ingress_token, secret.api_base_url) == (
        1,
        "tok",
        "https://x",
    )
    for value in (work, secret):
        with pytest.raises(dataclasses.FrozenInstanceError):
            value.id = "other"  # type: ignore[attr-defined]


def test_bridge_config_defaults() -> None:
    config = BridgeConfig(dir="/var/lib/questor", machine_name="laptop")

    assert config.max_sessions == 1
    assert config.verbose is False
    # A day-long default, expressed in milliseconds.
    assert config.session_timeout_ms == DEFAULT_SESSION_TIMEOUT_MS == 24 * 60 * 60 * 1000


def test_bridge_config_keeps_given_values() -> None:
    config = BridgeConfig(dir="/tmp", machine_name="m", max_sessions=3, verbose=True, session_timeout_ms=50)

    assert (config.max_sessions, config.verbose, config.session_timeout_ms) == (3, True, 50)
