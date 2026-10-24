"""Register session-file, clipboard and workspace commands."""

from __future__ import annotations

import json
import pyperclip
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from questorharness.capabilities.context.prompts import build_runtime_system_prompt
from questorharness.config.settings import load_settings
from questorharness.contracts.domain.message import ConversationMessage, sanitize_conversation_messages
from questorharness.platform.paths import get_data_dir, get_project_config_dir
from questorharness.runtime.bridge import get_bridge_manager
from questorharness.runtime.bridge.models import WorkSecret
from questorharness.runtime.bridge.work_secret import build_sdk_url, decode_work_secret, encode_work_secret

from questorharness.commands.models import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def _copy_to_clipboard(text: str) -> tuple[bool, str]:
    try:
        pyperclip.copy(text)
        return True, "clipboard"
    except Exception:
        for command in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard"]):
            try:
                subprocess.run(command, input=text, text=True, check=True, capture_output=True)
                return True, "clipboard"
            except Exception:
                continue
    fallback = get_data_dir() / "last_copy.txt"
    fallback.write_text(text, encoding="utf-8")
    return False, str(fallback)


def _last_message_text(messages: list[ConversationMessage]) -> str:
    for message in reversed(messages):
        if message.text.strip():
            return message.text.strip()
    return ""


def _rewind_turns(messages: list[ConversationMessage], turns: int) -> list[ConversationMessage]:
    updated = list(messages)
    for _ in range(max(0, turns)):
        if not updated:
            break
        while updated:
            popped = updated.pop()
            if popped.role == "user" and popped.text.strip():
                break
    return updated


def register_workspace_commands(registry: CommandRegistry) -> None:
    """Register session-file, clipboard and workspace commands."""

    async def _resume_handler(args: str, context: CommandContext) -> CommandResult:
        tokens = args.strip().split()

        # /resume <session_id> — 加载指定会话
        if tokens:
            sid = tokens[0]
            snapshot = context.session_backend.load_by_id(context.cwd, sid)
            if snapshot is None:
                return CommandResult(message=f"Session not found: {sid}")
            messages = sanitize_conversation_messages(
                [ConversationMessage.model_validate(item) for item in snapshot.get("messages", [])]
            )
            context.engine.load_messages(messages)
            summary = snapshot.get("summary", "")[:60]
            return CommandResult(
                message=f"Restored {len(messages)} messages from session {sid}"
                + (f" ({summary})" if summary else ""),
                replay_messages=messages,
            )

        # /resume — 列出会话（供 TUI 显示选择器）
        sessions = context.session_backend.list_snapshots(context.cwd, limit=10)
        if not sessions:
            # 回退到 latest.json
            snapshot = context.session_backend.load_latest(context.cwd)
            if snapshot is None:
                return CommandResult(message="No saved sessions found for this project.")
            messages = sanitize_conversation_messages(
                [ConversationMessage.model_validate(item) for item in snapshot.get("messages", [])]
            )
            context.engine.load_messages(messages)
            return CommandResult(
                message=f"Restored {len(messages)} messages from the latest session.",
                replay_messages=messages,
            )

        # 格式化会话列表以用于显示/选择器
        import time
        lines = ["Saved sessions:"]
        for s in sessions:
            ts = time.strftime("%m/%d %H:%M", time.localtime(s["created_at"]))
            summary = s["summary"][:50] or "(no summary)"
            lines.append(f"  {s['session_id']}  {ts}  {s['message_count']}msg  {summary}")
        lines.append("")
        lines.append("Use /resume <session_id> to restore a specific session.")
        return CommandResult(message="\n".join(lines))

    async def _export_handler(_: str, context: CommandContext) -> CommandResult:
        path = context.session_backend.export_markdown(cwd=context.cwd, messages=context.engine.messages)
        return CommandResult(message=f"Exported transcript to {path}")

    async def _share_handler(_: str, context: CommandContext) -> CommandResult:
        path = context.session_backend.export_markdown(cwd=context.cwd, messages=context.engine.messages)
        return CommandResult(message=f"Created shareable transcript snapshot at {path}")

    async def _copy_handler(args: str, context: CommandContext) -> CommandResult:
        text = args.strip() or _last_message_text(context.engine.messages)
        if not text:
            return CommandResult(message="Nothing to copy.")
        copied, target = _copy_to_clipboard(text)
        if copied:
            return CommandResult(message=f"Copied {len(text)} characters to the clipboard.")
        return CommandResult(message=f"Clipboard unavailable. Saved copied text to {target}")

    async def _session_handler(args: str, context: CommandContext) -> CommandResult:
        session_dir = context.session_backend.get_session_dir(context.cwd)
        tokens = args.split()
        if not tokens or tokens[0] == "show":
            latest = session_dir / "latest.json"
            transcript = session_dir / "transcript.md"
            lines = [
                f"Session ID: {context.session_id or '(none)'}",
                f"Session directory: {session_dir}",
                f"Latest snapshot: {'present' if latest.exists() else 'missing'}",
                f"Transcript export: {'present' if transcript.exists() else 'missing'}",
                f"Message count: {len(context.engine.messages)}",
            ]
            return CommandResult(message="\n".join(lines))
        if tokens[0] == "ls":
            files = sorted(path.name for path in session_dir.iterdir())
            return CommandResult(message="\n".join(files) if files else "(empty)")
        if tokens[0] == "path":
            return CommandResult(message=str(session_dir))
        if tokens[0] == "tag" and len(tokens) == 2:
            safe_name = "".join(character for character in tokens[1] if character.isalnum() or character in {"-", "_"})
            if not safe_name:
                return CommandResult(message="Usage: /session tag NAME")
            snapshot_path = context.session_backend.save_snapshot(
                cwd=context.cwd,
                model=context.app_state.get().model if context.app_state is not None else load_settings().model,
                system_prompt=build_runtime_system_prompt(
                    load_settings(),
                    cwd=context.cwd,
                    include_project_memory=context.include_project_memory,
                ),
                messages=context.engine.messages,
                usage=context.engine.total_usage,
            )
            export_path = context.session_backend.export_markdown(cwd=context.cwd, messages=context.engine.messages)
            tagged_json = session_dir / f"{safe_name}.json"
            tagged_md = session_dir / f"{safe_name}.md"
            shutil.copy2(snapshot_path, tagged_json)
            shutil.copy2(export_path, tagged_md)
            return CommandResult(message=f"Tagged session as {safe_name}:\n- {tagged_json}\n- {tagged_md}")
        if tokens[0] == "clear":
            if session_dir.exists():
                shutil.rmtree(session_dir)
            session_dir.mkdir(parents=True, exist_ok=True)
            return CommandResult(message=f"Cleared session storage at {session_dir}")
        return CommandResult(message="Usage: /session [show|ls|path|tag NAME|clear]")

    async def _rewind_handler(args: str, context: CommandContext) -> CommandResult:
        turns = 1
        if args.strip():
            try:
                turns = max(1, int(args.strip()))
            except ValueError:
                return CommandResult(message="Usage: /rewind [TURNS]")
        before = len(context.engine.messages)
        updated = _rewind_turns(context.engine.messages, turns)
        context.engine.load_messages(updated)
        removed = before - len(updated)
        return CommandResult(message=f"Rewound {turns} turn(s); removed {removed} message(s).")

    async def _tag_handler(args: str, context: CommandContext) -> CommandResult:
        name = args.strip()
        if not name:
            return CommandResult(message="Usage: /tag NAME")
        return await _session_handler(f"tag {name}", context)

    async def _files_handler(args: str, context: CommandContext) -> CommandResult:
        raw = args.strip()
        root = Path(context.cwd)
        max_items = 30
        tokens = raw.split(maxsplit=1)
        if tokens and tokens[0] == "dirs":
            dirs = [
                path
                for path in sorted(root.rglob("*"))
                if path.is_dir() and ".git" not in path.parts and ".venv" not in path.parts
            ]
            lines = [str(path.relative_to(root)) for path in dirs[:max_items]]
            if len(dirs) > max_items:
                lines.append(f"... {len(dirs) - max_items} more")
            return CommandResult(message="\n".join(lines) if lines else "(no directories)")
        if tokens and tokens[0].isdigit():
            max_items = max(1, min(int(tokens[0]), 200))
            raw = tokens[1] if len(tokens) == 2 else ""
        needle = raw.lower()
        files = [
            path
            for path in sorted(root.rglob("*"))
            if path.is_file() and ".git" not in path.parts and ".venv" not in path.parts
        ]
        if needle:
            files = [path for path in files if needle in str(path.relative_to(root)).lower()]
        lines = [str(path.relative_to(root)) for path in files[:max_items]]
        if len(files) > max_items:
            lines.append(f"... {len(files) - max_items} more")
        return CommandResult(
            message="\n".join(lines) if lines else "(no matching files)"
        )

    async def _init_handler(args: str, context: CommandContext) -> CommandResult:
        del args
        project_dir = get_project_config_dir(context.cwd)
        created: list[str] = []

        claudemd = Path(context.cwd) / "CLAUDE.md"
        if not claudemd.exists():
            claudemd.write_text(
                "# Project Instructions\n\n"
                "- Use QuestorHarness tools deliberately.\n"
                "- Keep changes minimal and verify with tests when possible.\n",
                encoding="utf-8",
            )
            created.append(str(claudemd.relative_to(Path(context.cwd))))

        for relative, content in (
            (
                project_dir / "README.md",
                "# Project QuestorHarness Config\n\nThis directory stores project-specific QuestorHarness state.\n",
            ),
            (
                project_dir / "memory" / "MEMORY.md",
                "# Project Memory\n\nAdd reusable project knowledge here.\n",
            ),
            (
                project_dir / "plugins" / ".gitkeep",
                "",
            ),
            (
                project_dir / "skills" / ".gitkeep",
                "",
            ),
        ):
            relative.parent.mkdir(parents=True, exist_ok=True)
            if not relative.exists():
                relative.write_text(content, encoding="utf-8")
                created.append(str(relative.relative_to(Path(context.cwd))))

        if not created:
            return CommandResult(message="Project already initialized for QuestorHarness.")
        return CommandResult(message="Initialized project files:\n" + "\n".join(f"- {item}" for item in created))

    async def _bridge_handler(args: str, context: CommandContext) -> CommandResult:
        tokens = args.split()
        if not tokens or tokens[0] == "show":
            sessions = get_bridge_manager().list_sessions()
            lines = [
                "Bridge summary:",
                "- backend host: available",
                f"- cwd: {context.cwd}",
                f"- sessions: {len(sessions)}",
                "- utilities: encode, decode, sdk, spawn, list, output, stop",
            ]
            return CommandResult(message="\n".join(lines))
        if tokens[0] == "encode" and len(tokens) == 3:
            encoded = encode_work_secret(
                WorkSecret(version=1, session_ingress_token=tokens[2], api_base_url=tokens[1])
            )
            return CommandResult(message=encoded)
        if tokens[0] == "decode" and len(tokens) == 2:
            secret = decode_work_secret(tokens[1])
            return CommandResult(message=json.dumps(secret.__dict__, indent=2))
        if tokens[0] == "sdk" and len(tokens) == 3:
            return CommandResult(message=build_sdk_url(tokens[1], tokens[2]))
        if tokens[0] == "spawn" and len(tokens) >= 2:
            command = args[len("spawn ") :]
            handle = await get_bridge_manager().spawn(
                session_id=f"bridge-{datetime.now(timezone.utc).strftime('%H%M%S')}",
                command=command,
                cwd=context.cwd,
            )
            return CommandResult(
                message=f"Spawned bridge session {handle.session_id} pid={handle.process.pid}"
            )
        if tokens[0] == "list":
            sessions = get_bridge_manager().list_sessions()
            if not sessions:
                return CommandResult(message="No bridge sessions.")
            return CommandResult(
                message="\n".join(
                    f"{item.session_id} [{item.status}] pid={item.pid} {item.command}"
                    for item in sessions
                )
            )
        if tokens[0] == "output" and len(tokens) == 2:
            return CommandResult(message=get_bridge_manager().read_output(tokens[1]) or "(no output)")
        if tokens[0] == "stop" and len(tokens) == 2:
            try:
                await get_bridge_manager().stop(tokens[1])
            except ValueError as exc:
                return CommandResult(message=str(exc))
            return CommandResult(message=f"Stopped bridge session {tokens[1]}")
        return CommandResult(
            message="Usage: /bridge [show|encode API_BASE_URL TOKEN|decode SECRET|sdk API_BASE_URL SESSION_ID|spawn CMD|list|output SESSION_ID|stop SESSION_ID]"
        )

    registry.register(
        SlashCommand(
            "resume",
            "Restore the latest saved session",
            _resume_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(SlashCommand("session", "Inspect the current session storage", _session_handler))

    registry.register(SlashCommand("export", "Export the current transcript", _export_handler))

    registry.register(SlashCommand("share", "Create a shareable transcript snapshot", _share_handler))

    registry.register(SlashCommand("copy", "Copy the latest response or provided text", _copy_handler))

    registry.register(SlashCommand("tag", "Create a named snapshot of the current session", _tag_handler))

    registry.register(SlashCommand("rewind", "Remove the latest conversation turn(s)", _rewind_handler))

    registry.register(SlashCommand("files", "List files in the current workspace", _files_handler))

    registry.register(SlashCommand("init", "Initialize project QuestorHarness files", _init_handler))

    registry.register(
        SlashCommand(
            "bridge",
            "Inspect bridge helpers and spawn bridge sessions",
            _bridge_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )
