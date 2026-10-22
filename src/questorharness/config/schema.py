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


class TelegramConfig(BaseChannelConfig):
    token: str = ""
    chat_id: str | None = None
    proxy: str | None = None
    reply_to_message: bool = True
    bot_name: str = "ohmo"


class SlackConfig(BaseChannelConfig):
    bot_token: str = ""
    app_token: str = ""
    signing_secret: str = ""


class DiscordConfig(BaseChannelConfig):
    token: str = ""


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


class DingTalkConfig(BaseChannelConfig):
    client_id: str = ""
    client_secret: str = ""
    robot_code: str = ""


class EmailConfig(BaseChannelConfig):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    from_address: str = ""


class QQConfig(BaseChannelConfig):
    token: str = ""
    app_id: str = ""
    app_secret: str = ""


class MatrixConfig(BaseChannelConfig):
    homeserver: str = ""
    access_token: str = ""
    user_id: str = ""


class WhatsAppConfig(BaseChannelConfig):
    access_token: str = ""
    phone_number_id: str = ""
    verify_token: str = ""


class MochatConfig(BaseChannelConfig):
    endpoint: str = ""
    token: str = ""


class ChannelConfigs(_CompatModel):
    send_progress: bool = True
    send_tool_hints: bool = True
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    dingtalk: DingTalkConfig = Field(default_factory=DingTalkConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    qq: QQConfig = Field(default_factory=QQConfig)
    matrix: MatrixConfig = Field(default_factory=MatrixConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    mochat: MochatConfig = Field(default_factory=MochatConfig)


class Config(_CompatModel):
    channels: ChannelConfigs = Field(default_factory=ChannelConfigs)
    providers: ProviderConfigs = Field(default_factory=ProviderConfigs)
