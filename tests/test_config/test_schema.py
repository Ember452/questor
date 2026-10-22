"""Schema regressions for questorharness.config.schema channel configs."""

from __future__ import annotations

from questorharness.config.schema import FeishuConfig, QQConfig


class TestFeishuConfig:
    def test_defaults_are_safe_and_stable(self):
        config = FeishuConfig()

        assert config.enabled is False
        assert config.allow_from == []
        assert config.domain == "https://open.feishu.cn"
        assert config.group_policy == "managed_or_mention"
        assert config.bot_names == ["ohmo", "openclaw", "questorharness"]

    def test_extra_fields_are_tolerated(self):
        config = FeishuConfig.model_validate({"app_id": "cli_app", "custom": "value"})

        assert config.app_id == "cli_app"
        assert config.custom == "value"


class TestQQConfig:
    def test_defaults_are_safe_and_stable(self):
        config = QQConfig()

        assert config.enabled is False
        assert config.allow_from == []
        assert config.token == ""
        assert config.app_id == ""
        assert config.app_secret == ""

    def test_credentials_are_loaded(self):
        config = QQConfig.model_validate(
            {"app_id": "qq-app", "token": "qq-token", "app_secret": "qq-secret"}
        )

        assert config.app_id == "qq-app"
        assert config.token == "qq-token"
        assert config.app_secret == "qq-secret"
