"""LLM runtime adapter implementing the tool-facing port."""

from __future__ import annotations

from typing import Any

from questorharness.contracts.domain.message import ConversationMessage, ImageBlock, TextBlock
from questorharness.providers.llm.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiTextDeltaEvent,
)
from questorharness.providers.llm.codex_client import _build_codex_headers, _resolve_codex_url
from questorharness.providers.llm.openai_client import OpenAICompatibleClient, _normalize_openai_base_url


class ProviderLlmToolRuntime:
    """Adapter over provider-level LLM helpers used by tools."""

    def normalize_openai_base_url(self, base_url: str) -> str:
        return _normalize_openai_base_url(base_url)

    def build_codex_headers(self, auth_token: str) -> dict[str, str]:
        return _build_codex_headers(auth_token)

    def resolve_codex_url(self, base_url: str) -> str:
        return _resolve_codex_url(base_url)

    async def describe_image(
        self,
        *,
        image_data: str,
        media_type: str,
        prompt: str,
        model: str,
        api_key: str,
        base_url: str,
        max_tokens: int,
    ) -> str:
        client = OpenAICompatibleClient(api_key=api_key, base_url=base_url or None)
        user_content: list[Any] = [
            TextBlock(text=prompt),
            ImageBlock(media_type=media_type, data=image_data),
        ]
        user_message = ConversationMessage(role="user", content=user_content)

        collected_text = ""
        async for event in client.stream_message(
            ApiMessageRequest(
                model=model,
                messages=[user_message],
                system_prompt="",
                max_tokens=max_tokens,
                tools=[],
            )
        ):
            if isinstance(event, ApiTextDeltaEvent):
                collected_text += event.text
            elif isinstance(event, ApiMessageCompleteEvent):
                text = event.message.text
                if text and text not in collected_text:
                    collected_text = text

        return collected_text.strip() or "(no description returned)"
