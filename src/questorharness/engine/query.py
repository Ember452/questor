"""Core tool-aware query loop."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from questorharness.contracts.domain.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from questorharness.contracts.domain.message import ConversationMessage, ToolResultBlock
from questorharness.contracts.hooks import HookEvent
from questorharness.contracts.usage import UsageSnapshot
from questorharness.engine.context import COORDINATOR_CONTEXT_MARKER, QueryContext
from questorharness.engine.model_errors import (
    MaxTurnsExceeded,
    _bounded_completion_tokens,
    _extract_completion_token_limit,
    _is_completion_token_limit_error,
    _is_prompt_too_long_error,
)
from questorharness.engine.tool_execution import _execute_tool_call
from questorharness.engine.vision import _preprocess_images_in_messages
from questorharness.providers.llm.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiRetryEvent,
    ApiTextDeltaEvent,
)

AUTO_COMPACT_STATUS_MESSAGE = "Auto-compacting conversation memory to keep things fast and focused."
REACTIVE_COMPACT_STATUS_MESSAGE = "Prompt too long; compacting conversation memory and retrying."

log = logging.getLogger(__name__)


async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]:
    """Run the conversation loop until the model stops requesting tools.

    Auto-compaction is checked at the start of each turn.  When the
    estimated token count exceeds the model's auto-compact threshold,
    the engine first tries a cheap microcompact (clearing old tool result
    content) and, if that is not enough, performs a full LLM-based
    summarization of older messages.
    """
    from questorharness.capabilities.context.compact import (
        AutoCompactState,
        auto_compact_if_needed,
    )

    compact_state = AutoCompactState()
    reactive_compact_attempted = False
    last_compaction_result: tuple[list[ConversationMessage], bool] = (messages, False)
    effective_max_tokens = _bounded_completion_tokens(
        context.max_tokens,
        context.context_window_tokens,
    )
    reported_token_clamp = False

    async def _stream_compaction(
        *,
        trigger: str,
        force: bool = False,
    ) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]:
        nonlocal last_compaction_result
        progress_queue: asyncio.Queue[CompactProgressEvent] = asyncio.Queue()

        async def _progress(event: CompactProgressEvent) -> None:
            await progress_queue.put(event)

        task = asyncio.create_task(
            auto_compact_if_needed(
                messages,
                api_client=context.api_client,
                model=context.model,
                system_prompt=context.system_prompt,
                state=compact_state,
                progress_callback=_progress,
                force=force,
                trigger=trigger,
                hook_executor=context.hook_executor,
                carryover_metadata=context.tool_metadata,
                context_window_tokens=context.context_window_tokens,
                auto_compact_threshold_tokens=context.auto_compact_threshold_tokens,
            )
        )
        while True:
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.05)
                yield event, None
            except asyncio.TimeoutError:
                if task.done():
                    break
                continue
        while not progress_queue.empty():
            yield progress_queue.get_nowait(), None
        last_compaction_result = await task
        return

    turn_count = 0
    while context.max_turns is None or turn_count < context.max_turns:
        turn_count += 1
        if effective_max_tokens != context.max_tokens and not reported_token_clamp:
            reported_token_clamp = True
            yield StatusEvent(
                message=(
                    "Requested max_tokens="
                    f"{context.max_tokens} exceeds the safe per-request output cap; "
                    f"using {effective_max_tokens}."
                )
            ), None
        # --- 调用模型前的自动压缩检查 ---------------
        async for event, usage in _stream_compaction(trigger="auto"):
            yield event, usage
        compacted_messages, was_compacted = last_compaction_result
        if compacted_messages is not messages:
            messages[:] = compacted_messages
        # ---------------------------------------------------------------

        # --- 图像预处理：为非视觉模型将 ImageBlocks 转为文本 ---
        async for event in _preprocess_images_in_messages(messages, context):
            yield event, None
        # -----------------------------------------------------------------------------

        final_message: ConversationMessage | None = None
        usage = UsageSnapshot()

        try:
            async for event in context.api_client.stream_message(
                ApiMessageRequest(
                    model=context.model,
                    messages=messages,
                    system_prompt=context.system_prompt,
                    max_tokens=effective_max_tokens,
                    tools=context.tool_registry.to_api_schema(),
                    effort=context.effort,
                )
            ):
                if isinstance(event, ApiTextDeltaEvent):
                    yield AssistantTextDelta(text=event.text), None
                    continue
                if isinstance(event, ApiRetryEvent):
                    yield StatusEvent(
                        message=(
                            f"Request failed; retrying in {event.delay_seconds:.1f}s "
                            f"(attempt {event.attempt + 1} of {event.max_attempts}): {event.message}"
                        )
                    ), None
                    continue

                if isinstance(event, ApiMessageCompleteEvent):
                    final_message = event.message
                    usage = event.usage
        except Exception as exc:
            error_msg = str(exc)
            if _is_completion_token_limit_error(exc):
                supported_limit = _extract_completion_token_limit(exc)
                if supported_limit is not None and effective_max_tokens > supported_limit:
                    previous_max_tokens = effective_max_tokens
                    effective_max_tokens = supported_limit
                    yield StatusEvent(
                        message=(
                            f"Model rejected max_tokens={previous_max_tokens}; "
                            f"retrying with provider limit {effective_max_tokens}."
                        )
                    ), None
                    turn_count = max(0, turn_count - 1)
                    continue
            if not reactive_compact_attempted and _is_prompt_too_long_error(exc):
                reactive_compact_attempted = True
                yield StatusEvent(message=REACTIVE_COMPACT_STATUS_MESSAGE), None
                async for event, usage in _stream_compaction(trigger="reactive", force=True):
                    yield event, usage
                compacted_messages, was_compacted = last_compaction_result
                if compacted_messages is not messages:
                    messages[:] = compacted_messages
                if was_compacted:
                    continue
            if "connect" in error_msg.lower() or "timeout" in error_msg.lower() or "network" in error_msg.lower():
                yield ErrorEvent(message=f"Network error: {error_msg}. Check your internet connection and try again."), None
            else:
                yield ErrorEvent(message=f"API error: {error_msg}"), None
            return

        if final_message is None:
            raise RuntimeError("Model stream finished without a final message")

        coordinator_context_message: ConversationMessage | None = None
        if context.coordinator_mode:
            if messages and messages[-1].role == "user" and messages[-1].text.startswith(COORDINATOR_CONTEXT_MARKER):
                coordinator_context_message = messages.pop()

        if final_message.role == "assistant" and final_message.is_effectively_empty():
            log.warning("dropping empty assistant message from provider response")
            yield ErrorEvent(
                message=(
                    "Model returned an empty assistant message. "
                    "The turn was ignored to keep the session healthy."
                )
            ), usage
            return

        messages.append(final_message)
        yield AssistantTurnComplete(message=final_message, usage=usage), usage

        if coordinator_context_message is not None:
            messages.append(coordinator_context_message)

        if not final_message.tool_uses:
            if context.hook_executor is not None:
                await context.hook_executor.execute(
                    HookEvent.STOP,
                    {
                        "event": HookEvent.STOP.value,
                        "stop_reason": "tool_uses_empty",
                    },
                )
            return

        tool_calls = final_message.tool_uses

        if len(tool_calls) == 1:
            # 单个工具：串行执行（立即流式发送事件）
            tc = tool_calls[0]
            yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None
            try:
                result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
            except Exception as exc:
                log.exception("tool execution raised: name=%s id=%s", tc.name, tc.id)
                result = ToolResultBlock(
                    tool_use_id=tc.id,
                    content=f"Tool {tc.name} failed: {type(exc).__name__}: {exc}",
                    is_error=True,
                )
            yield ToolExecutionCompleted(
                tool_name=tc.name,
                output=result.content,
                is_error=result.is_error,
                metadata=result.result_metadata,
            ), None
            tool_results = [result]
        else:
            # 多个工具：并发执行，完成后发送事件
            for tc in tool_calls:
                yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None

            async def _run(tc):
                return await _execute_tool_call(context, tc.name, tc.id, tc.input)

            # 使用 return_exceptions=True，避免单个工具失败导致
            # 其他兄弟协程被取消，并使对话留下
            # 未回复的 tool_use 块（Anthropic API 会拒绝会话上的
            # 下一次请求，只要有 tool_use 缺少匹配的 tool_result）。
            raw_results = await asyncio.gather(
                *[_run(tc) for tc in tool_calls], return_exceptions=True
            )
            tool_results = []
            for tc, result in zip(tool_calls, raw_results):
                if isinstance(result, BaseException):
                    log.exception(
                        "tool execution raised: name=%s id=%s",
                        tc.name,
                        tc.id,
                        exc_info=result,
                    )
                    result = ToolResultBlock(
                        tool_use_id=tc.id,
                        content=f"Tool {tc.name} failed: {type(result).__name__}: {result}",
                        is_error=True,
                    )
                tool_results.append(result)

            for tc, result in zip(tool_calls, tool_results):
                yield ToolExecutionCompleted(
                    tool_name=tc.name,
                    output=result.content,
                    is_error=result.is_error,
                    metadata=result.result_metadata,
                ), None

        messages.append(ConversationMessage(role="user", content=tool_results))

    if context.max_turns is not None:
        raise MaxTurnsExceeded(context.max_turns)
    raise RuntimeError("Query loop exited without a max_turns limit or final response")

# questor: allow R7 -- until W8 adds the mirror test
# questor: allow R8 -- refactor the offenders in W8
