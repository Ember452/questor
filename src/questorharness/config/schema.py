"""Compatibility channel config models.

These models keep the synced channel adapters importable while the main
QuestorHarness settings system evolves independently.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _CompatModel(BaseModel):
    """Base model that tolerates adapter-specific extra fields."""

    model_config = ConfigDict(extra="allow")


class ProviderApiKeyConfig(_CompatModel):
    api_key: str = ""


class ProviderConfigs(_CompatModel):
    groq: ProviderApiKeyConfig = Field(default_factory=ProviderApiKeyConfig)


class BaseChannelConfig(_CompatModel):
    enabled: bool = False
    # 安全默认值：启用渠道并不会自动信任所有
    # 远程发送者。运维人员必须显式允许特定身份，或
    # 在需要开放访问时显式设置 ["*"]。
    allow_from: list[str] = Field(default_factory=list)


class FeishuConfig(BaseChannelConfig):
    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    # 群回复策略由 ohmo 网关执行，因为托管群
    # 元数据位于通用飞书渠道适配器之外。
    group_policy: str = "managed_or_mention"
    bot_open_id: str = ""
    bot_names: list[str] = Field(default_factory=lambda: ["ohmo", "openclaw", "questorharness"])
    domain: str = "https://open.feishu.cn"  # Lark 国际版请使用 https://open.larksuite.com


class QQConfig(BaseChannelConfig):
    token: str = ""
    app_id: str = ""
    app_secret: str = ""


class ChannelConfigs(_CompatModel):
    send_progress: bool = True
    send_tool_hints: bool = True
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    qq: QQConfig = Field(default_factory=QQConfig)


class Config(_CompatModel):
    channels: ChannelConfigs = Field(default_factory=ChannelConfigs)
    providers: ProviderConfigs = Field(default_factory=ProviderConfigs)
