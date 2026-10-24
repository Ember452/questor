"""Image preprocessing for models without multimodal input."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from questorharness.capabilities.tools.contract import ToolExecutionContext
from questorharness.contracts.domain.events import StatusEvent, StreamEvent
from questorharness.contracts.domain.message import ConversationMessage, ImageBlock, TextBlock
from questorharness.engine.context import QueryContext
from questorharness.engine.runtimes import TOOL_LLM_RUNTIME
from questorharness.providers.llm.provider import is_model_multimodal


_IMAGE_PREPROCESS_STATUS = "Converting image to text description via vision model…"


async def _preprocess_images_in_messages(
    messages: list[ConversationMessage],
    context: QueryContext,
) -> AsyncIterator[StreamEvent]:
    """Scan messages for ImageBlocks and convert them to text if the active
    model does not support multimodal input.

    Yields status events during conversion so the UI stays responsive.
    """
    if is_model_multimodal(context.model):
        return

    vision_config = context.tool_metadata.get("vision_model_config")
    if not vision_config:
        # 未配置视觉模型 — 跳过预处理。
        return

    # 收集所有 ImageBlocks 及其父消息索引和块索引
    pending: list[tuple[int, int, ImageBlock]] = []
    for msg_idx, msg in enumerate(messages):
        if msg.role != "user":
            continue
        for blk_idx, block in enumerate(msg.content):
            if isinstance(block, ImageBlock):
                pending.append((msg_idx, blk_idx, block))

    if not pending:
        return

    yield StatusEvent(message=_IMAGE_PREPROCESS_STATUS)

    # 并行处理图像
    async def _describe(msg_idx: int, blk_idx: int, block: ImageBlock) -> tuple[int, int, str]:
        tool = context.tool_registry.get("image_to_text")
        if tool is None:
            return msg_idx, blk_idx, "[Image: could not describe — image_to_text tool not available]"

        # 构建工具输入
        tool_input_data: dict[str, object] = {
            "image_data": block.data,
            "media_type": block.media_type,
            "prompt": "Describe this image in detail, including any text, "
                      "UI elements, code, diagrams, or visual information present.",
        }

        try:
            parsed = tool.input_model.model_validate(tool_input_data)
        except Exception:
            return msg_idx, blk_idx, "[Image: could not parse image data]"

        exec_context = ToolExecutionContext(
            cwd=context.cwd,
            metadata={
                "vision_model_config": vision_config,
                **(context.tool_metadata or {}),
            },
            llm=TOOL_LLM_RUNTIME,
        )
        result = await tool.execute(parsed, exec_context)
        if result.is_error:
            return msg_idx, blk_idx, f"[Image description failed: {result.output}]"
        return msg_idx, blk_idx, result.output

    results = await asyncio.gather(*[_describe(mi, bi, blk) for mi, bi, blk in pending])

    # 原地将 ImageBlocks 替换为 TextBlocks
    for msg_idx, blk_idx, description in results:
        msg = messages[msg_idx]
        msg.content[blk_idx] = TextBlock(text=description)

# questor: allow R7 -- until W8 adds the mirror test
