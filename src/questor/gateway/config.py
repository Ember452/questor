"""Config IO for questor gateway."""

from __future__ import annotations

import logging
from pathlib import Path

from questor.gateway.models import GatewayConfig
from questor.workspace import get_gateway_config_path
from questorharness.api import Config

logger = logging.getLogger(__name__)


def load_gateway_config(workspace: str | Path | None = None) -> GatewayConfig:
    """Load ``gateway.json`` from the questor workspace."""
    path = get_gateway_config_path(workspace)
    if path.exists():
        return GatewayConfig.model_validate_json(path.read_text(encoding="utf-8"))
    return GatewayConfig()


def save_gateway_config(config: GatewayConfig, workspace: str | Path | None = None) -> Path:
    """Persist ``gateway.json`` in the questor workspace."""
    path = get_gateway_config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def build_channel_manager_config(config: GatewayConfig) -> Config:
    """Project gateway settings into the channel compatibility models."""
    root = Config()
    root.channels.send_progress = config.send_progress
    root.channels.send_tool_hints = config.send_tool_hints
    for name in config.enabled_channels:
        if not hasattr(root.channels, name):
            logger.warning("Ignoring unsupported channel in gateway config: %s", name)
            continue
        channel_config = getattr(root.channels, name).model_copy(
            update={"enabled": True, **config.channel_configs.get(name, {})}
        )
        setattr(root.channels, name, channel_config)
    return root
