from __future__ import annotations

import logging

from ohmo.gateway.config import build_channel_manager_config
from ohmo.gateway.models import GatewayConfig


def test_build_channel_manager_config_ignores_unsupported_channels(caplog):
    gateway = GatewayConfig(
        enabled_channels=["unsupported"],
        channel_configs={"unsupported": {"enabled": True}},
    )

    with caplog.at_level(logging.WARNING):
        root = build_channel_manager_config(gateway)

    assert root.channels.feishu.enabled is False
    assert root.channels.qq.enabled is False
    assert "Ignoring unsupported channel in gateway config: unsupported" in caplog.text


def test_build_channel_manager_config_enables_retained_channels():
    gateway = GatewayConfig(
        enabled_channels=["feishu", "qq"],
        channel_configs={
            "feishu": {"app_id": "feishu-app", "allow_from": ["ou_user"]},
            "qq": {"app_id": "qq-app", "allow_from": ["qq_user"]},
        },
    )

    root = build_channel_manager_config(gateway)

    assert root.channels.feishu.enabled is True
    assert root.channels.feishu.app_id == "feishu-app"
    assert root.channels.feishu.allow_from == ["ou_user"]
    assert root.channels.qq.enabled is True
    assert root.channels.qq.app_id == "qq-app"
    assert root.channels.qq.allow_from == ["qq_user"]
