"""GitHub Copilot API client for QuestorHarness.

Wraps :class:`OpenAICompatibleClient` with Copilot-specific headers.
The Copilot chat endpoint is OpenAI-compatible, so all message/tool
conversion is delegated to the inner client.

Authentication uses the persisted GitHub OAuth token directly
(``Authorization: Bearer <token>``) — no additional token exchange
is required.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from questorharness.providers.llm.client import (
    ApiMessageRequest,
    ApiStreamEvent,
)
from questorharness.providers.llm.copilot_auth import (
    copilot_api_base,
    load_copilot_auth,
)
from questorharness.providers.llm.errors import AuthenticationFailure
from questorharness.providers.llm.openai_client import OpenAICompatibleClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 请求头常量
# ---------------------------------------------------------------------------

_VERSION = "0.1.0"  # 用于 User-Agent 的 QuestorHarness 版本

# 配置模型不在 Copilot 模型目录中时，Copilot 请求使用的
# 默认模型。
COPILOT_DEFAULT_MODEL = "gpt-4o"


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class CopilotClient:
    """Copilot-aware API client implementing ``SupportsStreamingMessages``.

    Uses the GitHub OAuth token directly as a Bearer token for the
    Copilot API.  No token exchange or session management is needed.

    Parameters
    ----------
    github_token:
        GitHub OAuth token (``ghu_...`` / ``gho_...``).  If *None*, the
        token is loaded from ``~/.questorharness/copilot_auth.json``.
    enterprise_url:
        Optional enterprise domain.  If *None*, loaded from the
        persisted auth file (falls back to public GitHub).
    model:
        Default model to request.  Can be overridden per-request via
        ``ApiMessageRequest.model``.
    """

    def __init__(
        self,
        github_token: str | None = None,
        *,
        enterprise_url: str | None = None,
        model: str | None = None,
    ) -> None:
        auth_info = load_copilot_auth()
        token = github_token or (auth_info.github_token if auth_info else None)
        if not token:
            raise AuthenticationFailure(
                "No GitHub Copilot token found. Run 'oh auth copilot-login' first."
            )

        # 解析 enterprise_url：显式参数 > 已持久化认证 > None（公共端点）
        ent_url = enterprise_url or (auth_info.enterprise_url if auth_info else None)

        self._token = token
        self._enterprise_url = ent_url
        self._model = model

        # 只构建一次内部 OpenAI 兼容客户端。
        base_url = copilot_api_base(ent_url)
        default_headers: dict[str, str] = {
            "User-Agent": f"questorharness/{_VERSION}",
            "Openai-Intent": "conversation-edits",
        }
        raw_openai = AsyncOpenAI(
            api_key=token,
            base_url=base_url,
            default_headers=default_headers,
        )
        self._inner = OpenAICompatibleClient(
            api_key=token,
            base_url=base_url,
        )
        # 替换底层 SDK 客户端，以使用 Copilot 请求头。
        self._inner._client = raw_openai  # noqa: SLF001

        log.info(
            "CopilotClient initialised (api_base=%s, enterprise=%s)",
            base_url,
            ent_url or "none",
        )

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Stream a chat completion from the Copilot API.

        Satisfies the ``SupportsStreamingMessages`` protocol expected by
        the QuestorHarness query engine.

        If a *model* was provided at construction time it overrides the
        model in *request*; otherwise the request model is passed through.
        """
        effective_model = self._model or request.model
        patched = ApiMessageRequest(
            model=effective_model,
            messages=request.messages,
            system_prompt=request.system_prompt,
            max_tokens=request.max_tokens,
            tools=request.tools,
        )
        async for event in self._inner.stream_message(patched):
            yield event

    async def close(self) -> None:
        """Close the underlying OpenAI-compatible client."""
        await self._inner.close()
