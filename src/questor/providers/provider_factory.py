"""L5 provider 选择（OPT-6）：把 env 判据收在 providers 层，组合根只决定何时调用。

判据与历史 `surfaces/cli.provider_from_env` **逐字等价**：

- 有 ``QUESTOR_MODEL``（非空）且密钥存在 → :class:`LiteLLMProvider`（可带 preview 预算）；
- 否则 → :class:`EchoProvider`（离线 fail-safe，绝不因缺密钥起不来）。

为什么单独一个文件：组合根守卫（`scripts/check_extension_points.py`）禁止业务分支；
把 env 判据放进 providers 后，``build_app`` 只剩 ``if spec.surface is None`` 这类装配收窄。
本模块不 import surfaces；preview 预算由调用方解析后传入（避免 providers→surfaces 反向依赖）。
"""

from __future__ import annotations

from questor.config.model import load_config
from questor.contracts.ports import ProviderPort
from questor.providers.fake import EchoProvider
from questor.providers.litellm_adapter import LiteLLMProvider


def provider_from_env(*, payload_preview: int | None = None) -> ProviderPort:
    """按 env 选 provider：有 model+key 走 LiteLLM，否则离线 Echo。"""
    cfg = load_config()
    if cfg.llm.model and cfg.llm.has_litellm_key:
        return LiteLLMProvider(cfg.llm.model, payload_preview=payload_preview)
    return EchoProvider()


__all__ = ["provider_from_env"]
