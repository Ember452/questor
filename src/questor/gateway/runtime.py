"""Session-aware runtime pool for questor gateway."""

from __future__ import annotations

import logging
from pathlib import Path

from questor.gateway.config import load_gateway_config
from questor.gateway.group_tool import (
    CreateFeishuGroup,
    PublishGroupWelcome,
    QuestorCreateFeishuGroupTool,
)
from questor.gateway.provider_commands import (
    handle_gateway_model_command,
    handle_gateway_provider_command,
)
from questor.group_registry import load_managed_group_record, normalize_cwd
from questor.memory import create_memory_command_backend
from questor.prompts import build_questor_system_prompt
from questor.session_storage import QuestorSessionBackend
from questor.workspace import (
    get_memory_dir,
    get_plugins_dir,
    get_sessions_dir,
    get_skills_dir,
    initialize_workspace,
)
from questorharness.api import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CommandContext,
    CommandResult,
    CompactProgressEvent,
    ConversationMessage,
    ErrorEvent,
    InboundMessage,
    MaxTurnsExceeded,
    RuntimeBundle,
    StatusEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
    build_runtime,
    build_runtime_system_prompt,
    close_runtime,
    last_user_text,
    lookup_skill_slash_command,
    sanitize_conversation_messages,
    start_runtime,
)

logger = logging.getLogger(__name__)

_NO_GROUP_REQUEST = object()
_GROUP_TOOL_NAME = "questor_create_feishu_group"

from questor.gateway.redaction import (
    _build_inbound_user_message,
    _content_snippet,
    _format_channel_progress,
    _sanitize_group_command_metadata,
    _sanitize_group_command_prompts,
    _sanitize_snapshot_messages,
    _should_retry_without_image_input,
    _strip_image_blocks_from_engine_history,
    _summarize_tool_input,
)


class QuestorSessionRuntimePool:
    """Maintain one runtime bundle per chat/thread session."""

    def __init__(
        self,
        *,
        cwd: str | Path,
        workspace: str | Path | None = None,
        provider_profile: str,
        model: str | None = None,
        max_turns: int | None = None,
        create_feishu_group: CreateFeishuGroup | None = None,
        publish_group_welcome: PublishGroupWelcome | None = None,
    ) -> None:
        self._cwd = str(Path(cwd).resolve())
        self._workspace = workspace
        self._provider_profile = provider_profile
        self._model = model
        self._max_turns = max_turns
        self._create_feishu_group = create_feishu_group
        self._publish_group_welcome = publish_group_welcome
        self._workspace = initialize_workspace(workspace)
        self._gateway_config = load_gateway_config(self._workspace)
        self._session_backend = QuestorSessionBackend(self._workspace)
        self._bundles: dict[str, RuntimeBundle] = {}

    @property
    def active_sessions(self) -> int:
        return len(self._bundles)

    def _remote_admin_allowed(self, command) -> bool:
        if not getattr(command, "remote_admin_opt_in", False):
            return False
        if not self._gateway_config.allow_remote_admin_commands:
            return False
        allowed = {
            str(name).strip().lower()
            for name in self._gateway_config.allowed_remote_admin_commands
            if str(name).strip()
        }
        return command.name.lower() in allowed

    def _handle_gateway_scoped_command(self, command_name: str, args: str) -> tuple[str, bool] | None:
        lowered = command_name.lower()
        if lowered == "provider":
            result = handle_gateway_provider_command(args, workspace=self._workspace)
        elif lowered == "model":
            result = handle_gateway_model_command(args, workspace=self._workspace)
        else:
            return None
        if result[1]:
            self._gateway_config = load_gateway_config(self._workspace)
            self._provider_profile = self._gateway_config.provider_profile
        return result

    async def get_bundle(
        self,
        session_key: str,
        latest_user_prompt: str | None = None,
        cwd: str | Path | None = None,
    ) -> RuntimeBundle:
        """Return an existing bundle or create a new one."""
        session_cwd = str(Path(cwd or self._cwd).expanduser().resolve())
        bundle = self._bundles.get(session_key)
        if bundle is not None:
            bundle_cwd = str(Path(getattr(bundle, "cwd", self._cwd)).resolve())
            if bundle_cwd != session_cwd:
                logger.info(
                    "questor runtime recreating session for cwd change session_key=%s old_cwd=%s new_cwd=%s",
                    session_key,
                    bundle_cwd,
                    session_cwd,
                )
                await close_runtime(bundle)
                self._bundles.pop(session_key, None)
            else:
                logger.info(
                    "questor runtime reusing session session_key=%s session_id=%s prompt=%r",
                    session_key,
                    bundle.session_id,
                    _content_snippet(latest_user_prompt or ""),
                )
                bundle.engine.set_system_prompt(self._runtime_system_prompt(bundle, latest_user_prompt))
                return bundle

        snapshot = self._session_backend.load_latest_for_session_key(session_key)
        logger.info(
            "questor runtime creating session session_key=%s restored=%s prompt=%r",
            session_key,
            bool(snapshot),
            _content_snippet(latest_user_prompt or ""),
        )
        bundle = await build_runtime(
            cwd=session_cwd,
            model=self._model,
            max_turns=self._max_turns,
            system_prompt=build_questor_system_prompt(session_cwd, workspace=self._workspace, extra_prompt=None),
            active_profile=self._provider_profile,
            session_backend=self._session_backend,
            enforce_max_turns=self._max_turns is not None,
            restore_messages=_sanitize_snapshot_messages(snapshot.get("messages") if snapshot else None),
            restore_tool_metadata=_sanitize_group_command_metadata(snapshot.get("tool_metadata") if snapshot else None),
            extra_skill_dirs=(str(get_skills_dir(self._workspace)),),
            extra_plugin_roots=(str(get_plugins_dir(self._workspace)),),
            memory_backend=create_memory_command_backend(self._workspace),
            include_project_memory=False,
            autodream_context={
                "memory_dir": str(get_memory_dir(self._workspace)),
                "session_dir": str(get_sessions_dir(self._workspace)),
                "app_label": "questor personal memory",
                "runner_module": "questor",
            },
        )
        if snapshot and snapshot.get("session_id"):
            bundle.session_id = str(snapshot["session_id"])
        self._register_gateway_tools(bundle)
        await start_runtime(bundle)
        bundle.engine.set_system_prompt(self._runtime_system_prompt(bundle, latest_user_prompt))
        logger.info(
            "questor runtime started session_key=%s session_id=%s restored_messages=%s",
            session_key,
            bundle.session_id,
            len(snapshot.get("messages") or []) if snapshot else 0,
        )
        self._bundles[session_key] = bundle
        return bundle

    async def stream_message(self, message: InboundMessage, session_key: str):
        """Submit an inbound channel message and yield progress + final reply updates."""
        user_message = _build_inbound_user_message(message)
        user_prompt = user_message.text
        command_prompt = (message.content or "").strip()
        session_cwd = self._cwd_for_message(message)
        bundle = await self.get_bundle(session_key, latest_user_prompt=user_prompt, cwd=session_cwd)
        logger.info(
            "questor runtime processing start channel=%s chat_id=%s session_key=%s session_id=%s content=%r",
            message.channel,
            message.chat_id,
            session_key,
            bundle.session_id,
            _content_snippet(user_prompt),
        )

        command_context: CommandContext | None = None

        def get_command_context() -> CommandContext:
            nonlocal command_context
            if command_context is None:
                command_context = CommandContext(
                    engine=bundle.engine,
                    hooks_summary=getattr(bundle, "hook_summary", lambda: "")(),
                    mcp_summary=getattr(bundle, "mcp_summary", lambda: "")(),
                    plugin_summary=getattr(bundle, "plugin_summary", lambda: "")(),
                    cwd=getattr(bundle, "cwd", str(self._cwd)),
                    tool_registry=getattr(bundle, "tool_registry", None),
                    app_state=getattr(bundle, "app_state", None),
                    session_backend=getattr(bundle, "session_backend", self._session_backend),
                    session_id=getattr(bundle, "session_id", None),
                    extra_skill_dirs=getattr(bundle, "extra_skill_dirs", ()),
                    extra_plugin_roots=getattr(bundle, "extra_plugin_roots", ()),
                    memory_backend=create_memory_command_backend(self._workspace),
                    include_project_memory=False,
                )
            return command_context

        parsed = bundle.commands.lookup(command_prompt)
        if parsed is None and not message.media:
            parsed = lookup_skill_slash_command(command_prompt, get_command_context())
        if parsed is not None and not message.media:
            command, args = parsed
            command_name = str(getattr(command, "name", "") or "")
            remote_allowed = getattr(command, "remote_invocable", True)
            if not remote_allowed and self._remote_admin_allowed(command):
                remote_allowed = True
                logger.warning(
                    "questor gateway remote administrative command accepted channel=%s chat_id=%s sender_id=%s command=%s",
                    message.channel,
                    message.chat_id,
                    message.sender_id,
                    command_name,
                )
            if not remote_allowed:
                result = CommandResult(
                    message=f"/{command_name} is only available in the local QuestorHarness UI."
                )
                async for update in self._stream_command_result(
                    bundle=bundle,
                    message=message,
                    session_key=session_key,
                    user_prompt=user_prompt,
                    result=result,
                ):
                    yield update
                return
            gateway_result = self._handle_gateway_scoped_command(command_name, args)
            if gateway_result is not None:
                message_text, refresh_runtime = gateway_result
                result = CommandResult(message=message_text, refresh_runtime=refresh_runtime)
                async for update in self._stream_command_result(
                    bundle=bundle,
                    message=message,
                    session_key=session_key,
                    user_prompt=user_prompt,
                    result=result,
                ):
                    yield update
                return
            result = await command.handler(
                args,
                get_command_context(),
            )
            async for update in self._stream_command_result(
                bundle=bundle,
                message=message,
                session_key=session_key,
                user_prompt=user_prompt,
                result=result,
            ):
                yield update
            return

        async for update in self._stream_engine_message(
            bundle=bundle,
            message=message,
            session_key=session_key,
            user_prompt=user_prompt,
            user_message=user_message,
        ):
            yield update

    async def _stream_command_result(
        self,
        *,
        bundle: RuntimeBundle,
        message: InboundMessage,
        session_key: str,
        user_prompt: str,
        result,
    ):
        if result.refresh_runtime:
            bundle = await self._refresh_bundle(session_key, bundle, user_prompt)

        if result.message:
            yield GatewayStreamUpdate(
                kind="final",
                text=result.message,
                metadata={"_session_key": session_key, "_command": True},
            )

        if result.submit_prompt is not None:
            original_model = bundle.engine.model
            if result.submit_model:
                bundle.engine.set_model(result.submit_model)
            try:
                async for update in self._stream_engine_message(
                    bundle=bundle,
                    message=message,
                    session_key=session_key,
                    user_prompt=result.submit_prompt,
                    user_message=result.submit_prompt,
                ):
                    yield update
            finally:
                if result.submit_model:
                    bundle.engine.set_model(original_model)
            return

        if result.continue_pending:
            settings = bundle.current_settings()
            if bundle.enforce_max_turns:
                bundle.engine.set_max_turns(settings.max_turns)
            bundle.engine.set_system_prompt(
                self._runtime_system_prompt(bundle, last_user_text(bundle.engine.messages))
            )
            turns = result.continue_turns if result.continue_turns is not None else bundle.engine.max_turns
            reply_parts: list[str] = []
            try:
                async for event in bundle.engine.continue_pending(max_turns=turns):
                    async for update in self._convert_stream_event(
                        event=event,
                        bundle=bundle,
                        message=message,
                        session_key=session_key,
                        content=user_prompt,
                        reply_parts=reply_parts,
                    ):
                        yield update
            except MaxTurnsExceeded as exc:
                yield GatewayStreamUpdate(
                    kind="error",
                    text=f"Stopped after {exc.max_turns} turns (max_turns).",
                    metadata={"_session_key": session_key},
                )
            await self._save_snapshot(bundle, session_key, user_prompt)
            reply = "".join(reply_parts).strip()
            if reply:
                yield GatewayStreamUpdate(
                    kind="final",
                    text=reply,
                    metadata={"_session_key": session_key},
                )
            return

        await self._save_snapshot(bundle, session_key, user_prompt)

    async def _stream_engine_message(
        self,
        *,
        bundle: RuntimeBundle,
        message: InboundMessage,
        session_key: str,
        user_prompt: str,
        user_message: ConversationMessage | str,
    ):
        bundle.engine.set_system_prompt(self._runtime_system_prompt(bundle, user_prompt))
        reply_parts: list[str] = []
        emitted_media: set[str] = set()
        yield GatewayStreamUpdate(
            kind="progress",
            text=_format_channel_progress(
                channel=message.channel,
                kind="thinking",
                text="Thinking...",
                session_key=session_key,
                content=user_prompt,
            ),
            metadata={"_progress": True, "_session_key": session_key},
        )
        previous_group_request = self._set_group_request_context(bundle, message, session_key)
        try:
            async for event in bundle.engine.submit_message(user_message):
                if isinstance(event, ErrorEvent) and _should_retry_without_image_input(
                    event.message,
                    bundle.engine.messages,
                ):
                    logger.warning(
                        "questor runtime image input rejected; retrying without image blocks session_key=%s session_id=%s message=%r",
                        session_key,
                        bundle.session_id,
                        _content_snippet(event.message),
                    )
                    _strip_image_blocks_from_engine_history(bundle.engine)
                    yield GatewayStreamUpdate(
                        kind="progress",
                        text=_format_channel_progress(
                            channel=message.channel,
                            kind="image_fallback",
                            text=event.message,
                            session_key=session_key,
                            content=user_prompt,
                        ),
                        metadata={"_progress": True, "_session_key": session_key, "_image_fallback": True},
                    )
                    async for retry_event in bundle.engine.continue_pending(max_turns=bundle.engine.max_turns):
                        async for update in self._convert_stream_event(
                            event=retry_event,
                            bundle=bundle,
                            message=message,
                            session_key=session_key,
                            content=user_prompt,
                            reply_parts=reply_parts,
                        ):
                            _remember_update_media(emitted_media, update)
                            yield update
                    break
                async for update in self._convert_stream_event(
                    event=event,
                    bundle=bundle,
                    message=message,
                    session_key=session_key,
                    content=user_prompt,
                    reply_parts=reply_parts,
                ):
                    _remember_update_media(emitted_media, update)
                    yield update
        except MaxTurnsExceeded as exc:
            yield GatewayStreamUpdate(
                kind="error",
                text=f"Stopped after {exc.max_turns} turns (max_turns).",
                metadata={"_session_key": session_key},
            )
            self._restore_group_request_context(bundle, previous_group_request)
            await self._save_snapshot(bundle, session_key, user_prompt)
            return
        except Exception:
            self._restore_group_request_context(bundle, previous_group_request)
            raise
        self._restore_group_request_context(bundle, previous_group_request)
        await self._save_snapshot(bundle, session_key, user_prompt)
        reply = "".join(reply_parts).strip()
        if reply:
            logger.info(
                "questor runtime processing complete session_key=%s session_id=%s reply=%r",
                session_key,
                bundle.session_id,
                _content_snippet(reply),
            )
            final_media = _extract_final_reply_media(reply, emitted_media)
            metadata: dict[str, object] = {"_session_key": session_key}
            if final_media:
                metadata.update({"_media": final_media, "_final_media_fallback": True})
            yield GatewayStreamUpdate(
                kind="final",
                text=reply,
                metadata=metadata,
                media=final_media or None,
            )

    async def _convert_stream_event(
        self,
        *,
        event,
        bundle: RuntimeBundle,
        message: InboundMessage,
        session_key: str,
        content: str,
        reply_parts: list[str],
    ):
        if isinstance(event, AssistantTextDelta):
            reply_parts.append(event.text)
            return
        if isinstance(event, CompactProgressEvent):
            logger.info(
                "questor runtime compact progress session_key=%s session_id=%s phase=%s trigger=%s attempt=%s",
                session_key,
                bundle.session_id,
                event.phase,
                event.trigger,
                event.attempt,
            )
            rendered = _format_channel_progress(
                channel=message.channel,
                kind="compact_progress",
                text=event.message or "",
                session_key=session_key,
                content=content,
                compact_phase=event.phase,
                compact_trigger=event.trigger,
                attempt=event.attempt,
            )
            if rendered:
                yield GatewayStreamUpdate(
                    kind="progress",
                    text=rendered,
                    metadata={"_progress": True, "_session_key": session_key, "_compact": True},
                )
            return
        if isinstance(event, StatusEvent):
            logger.info(
                "questor runtime status session_key=%s session_id=%s message=%r",
                session_key,
                bundle.session_id,
                _content_snippet(event.message),
            )
            yield GatewayStreamUpdate(
                kind="progress",
                text=_format_channel_progress(
                    channel=message.channel,
                    kind="status",
                    text=event.message,
                    session_key=session_key,
                    content=content,
                ),
                metadata={"_progress": True, "_session_key": session_key},
            )
            return
        if isinstance(event, ToolExecutionStarted):
            summary = _summarize_tool_input(event.tool_name, event.tool_input)
            logger.info(
                "questor runtime tool start session_key=%s session_id=%s tool=%s summary=%r",
                session_key,
                bundle.session_id,
                event.tool_name,
                summary,
            )
            hint = f"Using {event.tool_name}"
            if summary:
                hint = f"{hint}: {summary}"
            yield GatewayStreamUpdate(
                kind="tool_hint",
                text=_format_channel_progress(
                    channel=message.channel,
                    kind="tool_hint",
                    text=hint,
                    session_key=session_key,
                    content=content,
                ),
                metadata={
                    "_progress": True,
                    "_tool_hint": True,
                    "_session_key": session_key,
                },
            )
            return
        if isinstance(event, ToolExecutionCompleted):
            logger.info(
                "questor runtime tool complete session_key=%s session_id=%s tool=%s",
                session_key,
                bundle.session_id,
                event.tool_name,
            )
            media = _extract_tool_media(event)
            if media:
                yield GatewayStreamUpdate(
                    kind="media",
                    text=_format_tool_media_caption(event, media),
                    metadata={"_session_key": session_key, "_media": media, "_tool_media": True},
                    media=media,
                )
            return
        if isinstance(event, ErrorEvent):
            logger.error(
                "questor runtime error session_key=%s session_id=%s message=%r",
                session_key,
                bundle.session_id,
                _content_snippet(event.message),
            )
            yield GatewayStreamUpdate(
                kind="error",
                text=event.message,
                metadata={"_session_key": session_key},
            )
            return
        if isinstance(event, AssistantTurnComplete) and not reply_parts:
            reply_parts.append(event.message.text.strip())

    async def _save_snapshot(self, bundle: RuntimeBundle, session_key: str, user_prompt: str) -> None:
        tool_metadata = _sanitize_group_command_metadata(getattr(bundle.engine, "tool_metadata", {}) or {})
        if isinstance(getattr(bundle.engine, "tool_metadata", None), dict) and isinstance(tool_metadata, dict):
            bundle.engine.tool_metadata.update(tool_metadata)
        messages = _sanitize_group_command_prompts(list(bundle.engine.messages))
        if messages != list(bundle.engine.messages):
            if hasattr(bundle.engine, "load_messages"):
                bundle.engine.load_messages(messages)
            else:
                bundle.engine.messages = messages
        self._session_backend.save_snapshot(
            cwd=getattr(bundle, "cwd", self._cwd),
            model=bundle.current_settings().model,
            system_prompt=self._runtime_system_prompt(bundle, user_prompt),
            messages=messages,
            usage=bundle.engine.total_usage,
            session_id=bundle.session_id,
            session_key=session_key,
            tool_metadata=tool_metadata,
        )
        logger.info(
            "questor runtime saved snapshot session_key=%s session_id=%s message_count=%s",
            session_key,
            bundle.session_id,
            len(bundle.engine.messages),
        )

    async def _refresh_bundle(
        self,
        session_key: str,
        bundle: RuntimeBundle,
        latest_user_prompt: str | None,
    ) -> RuntimeBundle:
        snapshot = sanitize_conversation_messages(list(bundle.engine.messages))
        prior_session_id = bundle.session_id
        bundle_cwd = str(Path(getattr(bundle, "cwd", self._cwd)).resolve())
        await close_runtime(bundle)
        refreshed = await build_runtime(
            cwd=bundle_cwd,
            model=self._model,
            max_turns=self._max_turns,
            system_prompt=build_questor_system_prompt(bundle_cwd, workspace=self._workspace, extra_prompt=None),
            active_profile=self._provider_profile,
            session_backend=self._session_backend,
            enforce_max_turns=self._max_turns is not None,
            restore_messages=[message.model_dump(mode="json") for message in _sanitize_group_command_prompts(snapshot)],
            restore_tool_metadata=_sanitize_group_command_metadata(getattr(bundle.engine, "tool_metadata", {}) or {}),
            extra_skill_dirs=(str(get_skills_dir(self._workspace)),),
            extra_plugin_roots=(str(get_plugins_dir(self._workspace)),),
            memory_backend=create_memory_command_backend(self._workspace),
            include_project_memory=False,
            autodream_context={
                "memory_dir": str(get_memory_dir(self._workspace)),
                "session_dir": str(get_sessions_dir(self._workspace)),
                "app_label": "questor personal memory",
                "runner_module": "questor",
            },
        )
        refreshed.session_id = prior_session_id
        self._register_gateway_tools(refreshed)
        await start_runtime(refreshed)
        refreshed.engine.set_system_prompt(self._runtime_system_prompt(refreshed, latest_user_prompt))
        self._bundles[session_key] = refreshed
        logger.info(
            "questor runtime refreshed session_key=%s session_id=%s message_count=%s",
            session_key,
            refreshed.session_id,
            len(refreshed.engine.messages),
        )
        return refreshed

    def _runtime_system_prompt(self, bundle: RuntimeBundle, latest_user_prompt: str | None) -> str:
        bundle_cwd = str(Path(getattr(bundle, "cwd", self._cwd)).resolve())
        if not hasattr(bundle, "current_settings"):
            return build_questor_system_prompt(bundle_cwd, workspace=self._workspace, extra_prompt=None)
        settings = bundle.current_settings()
        if not hasattr(settings, "system_prompt"):
            return build_questor_system_prompt(bundle_cwd, workspace=self._workspace, extra_prompt=None)
        return build_runtime_system_prompt(
            settings,
            cwd=bundle_cwd,
            latest_user_prompt=latest_user_prompt,
            extra_skill_dirs=getattr(bundle, "extra_skill_dirs", ()),
            extra_plugin_roots=getattr(bundle, "extra_plugin_roots", ()),
            include_project_memory=False,
        )

    def _cwd_for_message(self, message: InboundMessage) -> str:
        record = load_managed_group_record(
            workspace=self._workspace,
            channel=message.channel,
            chat_id=message.chat_id,
        )
        cwd = record.get("cwd") if record else None
        if not cwd:
            return self._cwd
        normalized = normalize_cwd(str(cwd))
        if not Path(normalized).is_dir():
            logger.warning(
                "questor managed group cwd does not exist channel=%s chat_id=%s cwd=%s",
                message.channel,
                message.chat_id,
                normalized,
            )
            return self._cwd
        return normalized

    def _register_gateway_tools(self, bundle: RuntimeBundle) -> None:
        self._unregister_group_tool(bundle)

    def _register_group_tool(self, bundle: RuntimeBundle) -> None:
        if self._create_feishu_group is None or not hasattr(bundle, "tool_registry"):
            return
        if bundle.tool_registry is None or bundle.tool_registry.get(_GROUP_TOOL_NAME) is not None:
            return
        bundle.tool_registry.register(
            QuestorCreateFeishuGroupTool(
                workspace=self._workspace,
                create_group=self._create_feishu_group,
                publish_group_welcome=self._publish_group_welcome,
            )
        )

    @staticmethod
    def _unregister_group_tool(bundle: RuntimeBundle) -> None:
        registry = getattr(bundle, "tool_registry", None)
        tools = getattr(registry, "_tools", None)
        if isinstance(tools, dict):
            tools.pop(_GROUP_TOOL_NAME, None)

    def _set_group_request_context(
        self,
        bundle: RuntimeBundle,
        message: InboundMessage,
        session_key: str,
    ) -> object:
        metadata = getattr(bundle.engine, "tool_metadata", {})
        previous = metadata.get("questor_group_request", _NO_GROUP_REQUEST)
        if not message.metadata.get("_questor_group_command"):
            metadata.pop("questor_group_request", None)
            metadata.pop("_suppress_next_user_goal", None)
            self._unregister_group_tool(bundle)
            return _NO_GROUP_REQUEST
        self._register_group_tool(bundle)
        metadata["_suppress_next_user_goal"] = True
        metadata["questor_group_request"] = {
            "channel": message.channel,
            "chat_type": str(message.metadata.get("chat_type") or "").strip().lower(),
            "sender_id": str(message.sender_id),
            "source_chat_id": str(message.chat_id),
            "source_session_key": session_key,
            "sender_display_name": message.metadata.get("sender_display_name"),
            "raw_request": message.metadata.get("_questor_group_raw_request") or "",
            "used": False,
        }
        return previous

    @staticmethod
    def _restore_group_request_context(bundle: RuntimeBundle, previous: object) -> None:
        metadata = getattr(bundle.engine, "tool_metadata", {})
        del previous
        metadata.pop("questor_group_request", None)
        metadata.pop("_suppress_next_user_goal", None)
        QuestorSessionRuntimePool._unregister_group_tool(bundle)

from questor.gateway.media import (  # noqa: F401
    _build_attachment_notes,
    _decode_text_preview,
    _describe_media_path,
    _extract_final_reply_media,
    _extract_tool_media,
    _format_tool_media_caption,
    _is_image_attachment,
    _remember_update_media,
    _summarize_attachment,
)
from questor.gateway.stream_update import GatewayStreamUpdate

# questor: allow R7 -- until W8 adds the mirror test
