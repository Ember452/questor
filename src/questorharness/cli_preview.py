"""Dry-run preview rendering for ``questorharness dry-run``.

Split out of ``cli.py``: these helpers score candidate files, build the preview
payload and format it for the terminal. They do not depend on Typer.
"""

from __future__ import annotations

import re
import shutil
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

_PREVIEW_STOPWORDS = {
    "a",
    "an",
    "and",
    "bug",
    "by",
    "fix",
    "for",
    "get",
    "help",
    "in",
    "of",
    "on",
    "or",
    "please",
    "show",
    "test",
    "that",
    "the",
    "this",
    "to",
    "with",
}


def _safe_short(text: str, *, limit: int = 140) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _schema_argument_preview(tool_schema: dict[str, object]) -> dict[str, object]:
    input_schema = tool_schema.get("input_schema")
    if not isinstance(input_schema, dict):
        return {"required_args": [], "optional_args": []}
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return {"required_args": [], "optional_args": []}
    required_raw = input_schema.get("required")
    required = (
        sorted(str(name) for name in required_raw if isinstance(name, str))
        if isinstance(required_raw, list)
        else []
    )
    optional = sorted(name for name in properties if name not in required)
    return {"required_args": required, "optional_args": optional}


def _mcp_transport_preview(config: object) -> dict[str, str]:
    if hasattr(config, "type"):
        transport = str(getattr(config, "type") or "unknown")
    elif isinstance(config, dict):
        transport = str(config.get("type") or "unknown")
    else:
        transport = "unknown"

    if transport == "stdio":
        command = getattr(config, "command", None) if not isinstance(config, dict) else config.get("command")
        args = getattr(config, "args", None) if not isinstance(config, dict) else config.get("args")
        rendered_args = " ".join(str(item) for item in args) if isinstance(args, list) and args else ""
        target = " ".join(part for part in (str(command or "").strip(), rendered_args.strip()) if part).strip()
        return {"transport": "stdio", "target": target or "configured"}
    if transport in {"http", "ws"}:
        url = getattr(config, "url", None) if not isinstance(config, dict) else config.get("url")
        return {"transport": transport, "target": str(url or "").strip() or "configured"}
    return {"transport": transport, "target": "configured"}


def _validate_mcp_server(name: str, config: object) -> dict[str, object]:
    preview = _mcp_transport_preview(config)
    issues: list[str] = []
    status = "ok"
    transport = preview["transport"]

    if transport == "stdio":
        command = getattr(config, "command", None) if not isinstance(config, dict) else config.get("command")
        raw_cwd = getattr(config, "cwd", None) if not isinstance(config, dict) else config.get("cwd")
        command_text = str(command or "").strip()
        if not command_text:
            issues.append("missing command")
        elif shutil.which(command_text) is None:
            issues.append(f"command not found in PATH: {command_text}")
        if raw_cwd:
            resolved_cwd = Path(str(raw_cwd)).expanduser()
            if not resolved_cwd.exists():
                issues.append(f"cwd does not exist: {resolved_cwd}")
    elif transport in {"http", "ws"}:
        raw_url = getattr(config, "url", None) if not isinstance(config, dict) else config.get("url")
        parsed = urlparse(str(raw_url or "").strip())
        expected = {"http", "https"} if transport == "http" else {"ws", "wss"}
        if parsed.scheme not in expected or not parsed.netloc:
            issues.append(f"invalid {transport} url: {raw_url}")

    if issues:
        status = "error"
    return {
        "name": name,
        **preview,
        "status": status,
        "issues": issues,
    }


def _dry_run_command_behavior(name: str) -> dict[str, str]:
    read_only = {
        "help",
        "version",
        "status",
        "context",
        "cost",
        "usage",
        "stats",
        "hooks",
        "onboarding",
        "skills",
        "mcp",
        "doctor",
        "diff",
        "branch",
        "privacy-settings",
        "rate-limit-options",
        "release-notes",
        "upgrade",
        "keybindings",
        "files",
    }
    mutating = {
        "clear",
        "compact",
        "resume",
        "session",
        "export",
        "share",
        "copy",
        "tag",
        "rewind",
        "init",
        "bridge",
        "login",
        "logout",
        "feedback",
        "config",
        "plugin",
        "reload-plugins",
        "permissions",
        "plan",
        "fast",
        "effort",
        "passes",
        "turns",
        "continue",
        "provider",
        "model",
        "theme",
        "output-style",
        "vim",
        "voice",
        "commit",
        "issue",
        "pr_comments",
        "agents",
        "subagents",
        "tasks",
        "autopilot",
        "ship",
        "memory",
    }
    if name in read_only:
        return {
            "kind": "read_only",
            "detail": "This slash command mainly inspects current state and should not require a model turn.",
        }
    if name in mutating:
        return {
            "kind": "stateful",
            "detail": "This slash command can mutate local state, queue work, or trigger follow-up execution depending on its arguments.",
        }
    return {
        "kind": "unknown",
        "detail": "This slash command comes from a handler or plugin that dry-run cannot classify precisely.",
    }


def _tokenize_preview_text(text: str) -> list[str]:
    lowered = text.lower()
    ascii_tokens = re.findall(r"[a-z0-9_/-]+", lowered)
    cjk_tokens = [char for char in lowered if "\u4e00" <= char <= "\u9fff"]
    seen: set[str] = set()
    ordered: list[str] = []
    for token in [*ascii_tokens, *cjk_tokens]:
        normalized = token.strip("-_/")
        if len(normalized) < 2 and normalized not in cjk_tokens:
            continue
        if normalized in _PREVIEW_STOPWORDS:
            continue
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _score_candidate_match(prompt: str, *fields: str) -> tuple[int, list[str]]:
    prompt_lower = prompt.lower()
    prompt_tokens = _tokenize_preview_text(prompt)
    haystack = " ".join(field.lower() for field in fields if field).strip()
    if not haystack:
        return 0, []

    score = 0
    reasons: list[str] = []
    for token in prompt_tokens:
        if token in haystack:
            score += max(2, min(len(token), 8))
            if len(reasons) < 3:
                reasons.append(token)
    primary_name = fields[0].lower() if fields and fields[0] else ""
    if primary_name and primary_name in prompt_lower:
        score += 10
        if fields[0] not in reasons:
            reasons.insert(0, fields[0])
    return score, reasons[:3]


def _candidate_entry(name: str, description: str, *, score: int, reasons: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "description": description,
        "score": score,
        "reasons": reasons,
    }


def _recommend_preview_candidates(
    prompt: str | None,
    *,
    skills: list[object],
    tool_schemas: list[dict[str, object]],
    command_entries: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    if not prompt:
        return {"skills": [], "tools": [], "commands": []}
    stripped = prompt.strip()
    if not stripped or stripped.startswith("/"):
        return {"skills": [], "tools": [], "commands": []}

    skill_matches: list[dict[str, object]] = []
    for skill in skills:
        score, reasons = _score_candidate_match(
            stripped,
            str(getattr(skill, "name", "")),
            str(getattr(skill, "description", "")),
            str(getattr(skill, "content", ""))[:800],
        )
        if score >= 4:
            skill_matches.append(
                _candidate_entry(
                    str(getattr(skill, "name", "")),
                    str(getattr(skill, "description", "")),
                    score=score,
                    reasons=reasons,
                )
            )

    tool_matches: list[dict[str, object]] = []
    for tool in tool_schemas:
        optional = ", ".join(str(item) for item in tool.get("optional_args") or [])
        required = ", ".join(str(item) for item in tool.get("required_args") or [])
        score, reasons = _score_candidate_match(
            stripped,
            str(tool.get("name") or ""),
            str(tool.get("description") or ""),
            required,
            optional,
        )
        if score >= 4:
            tool_matches.append(
                _candidate_entry(
                    str(tool.get("name") or ""),
                    str(tool.get("description") or ""),
                    score=score,
                    reasons=reasons,
                )
            )

    command_matches: list[dict[str, object]] = []
    for command in command_entries:
        score, reasons = _score_candidate_match(
            stripped,
            str(command.get("name") or ""),
            str(command.get("description") or ""),
            str(command.get("behavior", {}).get("detail") or ""),
        )
        if score >= 8:
            command_matches.append(
                _candidate_entry(
                    str(command.get("name") or ""),
                    str(command.get("description") or ""),
                    score=score,
                    reasons=reasons,
                )
            )

    skill_matches.sort(key=lambda entry: (-int(entry["score"]), str(entry["name"])))
    tool_matches.sort(key=lambda entry: (-int(entry["score"]), str(entry["name"])))
    command_matches.sort(key=lambda entry: (-int(entry["score"]), str(entry["name"])))
    return {
        "skills": skill_matches[:5],
        "tools": tool_matches[:8],
        "commands": command_matches[:5],
    }


def _evaluate_dry_run_readiness(
    *,
    prompt: str | None,
    entrypoint: dict[str, object],
    validation: dict[str, object],
) -> dict[str, object]:
    level = "ready"
    reasons: list[str] = []
    next_actions: list[str] = []

    if entrypoint.get("kind") == "unknown_slash_command":
        level = "blocked"
        reasons.append("The prompt starts with '/' but does not match any registered slash command.")
        next_actions.append("Check the command name and run `oh --dry-run -p \"/help\"` to inspect available slash commands.")

    api_client = validation.get("api_client")
    if isinstance(api_client, dict) and api_client.get("status") == "error":
        if entrypoint.get("kind") == "model_prompt":
            level = "blocked"
            detail = str(api_client.get("detail") or "").strip()
            reasons.append(detail or "Runtime client resolution failed for a prompt that would require a model call.")
            next_actions.append("Fix authentication or provider profile configuration before running this prompt.")
        elif level != "blocked":
            level = "warning"
            reasons.append("Runtime client resolution failed. Interactive commands may still work, but model execution would fail.")
            next_actions.append("If you expect a model call later, fix authentication or provider profile configuration first.")

    mcp_errors = int(validation.get("mcp_errors") or 0)
    if mcp_errors > 0 and level != "blocked":
        level = "warning"
        reasons.append(f"{mcp_errors} configured MCP server(s) have obvious configuration errors.")
        next_actions.append("Fix or disable the broken MCP server configuration before relying on MCP-backed tools.")

    auth_status = str(validation.get("auth_status") or "")
    if auth_status.startswith("missing") and entrypoint.get("kind") in {"interactive_session", "model_prompt"} and level != "blocked":
        level = "warning"
        reasons.append("Authentication is missing, so live model execution would not start successfully.")
        next_actions.append("Run `oh auth login` or configure the active profile credentials before executing.")

    if not prompt and level == "ready":
        reasons.append("No prompt provided; dry-run only validated the session setup path.")
        next_actions.append("Provide `-p/--print` for a single prompt preview, or start `oh` normally to enter an interactive session.")
    elif level == "ready":
        reasons.append("Resolved configuration, prompt assembly, and static discovery checks all look usable.")
        if entrypoint.get("kind") == "slash_command":
            next_actions.append(f"You can run `oh -p \"{prompt}\"` directly.")
        elif entrypoint.get("kind") == "model_prompt":
            next_actions.append("You can run this prompt directly with `oh -p '...'` or open the interactive UI with `oh`.")
        else:
            next_actions.append("You can run QuestorHarness normally with the current configuration.")

    deduped_actions: list[str] = []
    seen_actions: set[str] = set()
    for action in next_actions:
        normalized = action.strip()
        if not normalized or normalized in seen_actions:
            continue
        seen_actions.add(normalized)
        deduped_actions.append(normalized)

    return {"level": level, "reasons": reasons, "next_actions": deduped_actions}


def _build_dry_run_preview(
    *,
    prompt: str | None,
    cwd: str,
    model: str | None,
    max_turns: int | None,
    base_url: str | None,
    system_prompt: str | None,
    append_system_prompt: str | None,
    api_key: str | None,
    api_format: str | None,
    permission_mode: str | None,
    effort: str | None = None,
) -> dict[str, object]:
    from questorharness.bootstrap.runtime import _resolve_api_client_from_settings
    from questorharness.capabilities.context.prompts.context import build_runtime_system_prompt
    from questorharness.capabilities.skills import load_skill_registry
    from questorharness.capabilities.tools import create_default_tool_registry
    from questorharness.commands import create_default_command_registry
    from questorharness.config import load_settings
    from questorharness.platform.paths import get_config_file_path
    from questorharness.plugins import load_plugins
    from questorharness.plugins.source import ensure_plugin_source
    from questorharness.providers.llm.provider import auth_status, detect_provider
    from questorharness.providers.mcp.config import load_mcp_server_configs

    # The preview builds the real prompt, so the plugin port has to be wired here
    # too; ``bootstrap`` only does it when a runtime is assembled.
    ensure_plugin_source()

    resolved_cwd = str(Path(cwd).expanduser().resolve())
    settings = load_settings().merge_cli_overrides(
        model=model,
        max_turns=max_turns,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_format=api_format,
        permission_mode=permission_mode,
        effort=effort,
    )
    provider = detect_provider(settings)
    auth = auth_status(settings)
    profile_name, profile = settings.resolve_profile()

    plugins = load_plugins(settings, resolved_cwd)
    plugin_commands = [
        command
        for plugin in plugins
        if plugin.enabled
        for command in plugin.commands
    ]
    command_registry = create_default_command_registry(plugin_commands=plugin_commands)
    command_match = command_registry.lookup(prompt) if prompt else None
    skill_registry = load_skill_registry(resolved_cwd, settings=settings)
    skills = skill_registry.list_skills()
    mcp_servers = load_mcp_server_configs(settings, plugins)
    tool_registry = create_default_tool_registry()
    tool_schemas = []
    for tool_schema in tool_registry.to_api_schema():
        args_preview = _schema_argument_preview(tool_schema)
        tool_schemas.append(
            {
                "name": str(tool_schema.get("name") or ""),
                "description": str(tool_schema.get("description") or ""),
                **args_preview,
            }
        )

    client_validation = {"status": "ok", "detail": ""}
    try:
        with redirect_stderr(StringIO()):
            _resolve_api_client_from_settings(settings)
    except SystemExit:
        client_validation = {"status": "error", "detail": "runtime client could not be resolved with current auth/config"}
    except Exception as exc:  # pragma: no cover - defensive diagnostic path
        client_validation = {"status": "error", "detail": str(exc)}

    preview_prompt = prompt.strip() if prompt else None
    prompt_seed = preview_prompt
    if append_system_prompt:
        appended = append_system_prompt.strip()
        if appended:
            existing = settings.system_prompt or ""
            settings = settings.model_copy(update={"system_prompt": f"{existing}\n\n{appended}".strip()})
    system_prompt_text = build_runtime_system_prompt(
        settings,
        cwd=resolved_cwd,
        latest_user_prompt=prompt_seed,
    )

    command_entries = []
    for command in command_registry.list_commands():
        behavior = _dry_run_command_behavior(command.name)
        command_entries.append(
            {
                "name": command.name,
                "description": command.description,
                "remote_invocable": command.remote_invocable,
                "remote_admin_opt_in": command.remote_admin_opt_in,
                "behavior": behavior,
            }
        )

    recommendations = _recommend_preview_candidates(
        preview_prompt,
        skills=skills,
        tool_schemas=tool_schemas,
        command_entries=command_entries,
    )

    if preview_prompt:
        if preview_prompt.startswith("/") and command_match is not None:
            matched_command = command_match[0]
            behavior = _dry_run_command_behavior(matched_command.name)
            entrypoint = {
                "kind": "slash_command",
                "command": matched_command.name,
                "args": command_match[1],
                "description": matched_command.description,
                "remote_invocable": matched_command.remote_invocable,
                "remote_admin_opt_in": matched_command.remote_admin_opt_in,
                "behavior": behavior["kind"],
                "detail": (
                    f"Input resolves to /{matched_command.name}. "
                    f"{behavior['detail']} Dry-run does not execute the command handler."
                ),
            }
        elif preview_prompt.startswith("/") and command_match is None:
            entrypoint = {
                "kind": "unknown_slash_command",
                "detail": "Input starts with / but does not match a registered slash command.",
            }
        else:
            entrypoint = {
                "kind": "model_prompt",
                "detail": (
                    "The first live step would be a model request. "
                    "Exact tool calls and parameters are decided by the model at runtime."
                ),
            }
    else:
        entrypoint = {
            "kind": "interactive_session",
            "detail": "QuestorHarness would start and wait for user input. No model or tool call happens until you submit one.",
        }

    preview = {
        "mode": "dry-run",
        "cwd": resolved_cwd,
        "config_path": str(get_config_file_path()),
        "prompt": preview_prompt,
        "prompt_preview": _safe_short(preview_prompt or "", limit=220) if preview_prompt else "",
        "settings": {
            "active_profile": profile_name,
            "profile_label": profile.label,
            "provider": provider.name,
            "api_format": settings.api_format,
            "model": settings.model,
            "base_url": settings.base_url or "",
            "permission_mode": settings.permission.mode.value,
            "max_turns": settings.max_turns,
            "effort": settings.effort,
            "passes": settings.passes,
        },
        "validation": {
            "auth_status": auth,
            "api_client": client_validation,
            "system_prompt_chars": len(system_prompt_text),
            "mcp_validation": "skipped in dry-run (configured only; external servers are not started)",
        },
        "entrypoint": entrypoint,
        "commands": command_entries,
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "source": skill.source,
            }
            for skill in skills
        ],
        "tools": tool_schemas,
        "recommendations": recommendations,
        "plugins": [
            {
                "name": plugin.manifest.name,
                "enabled": plugin.enabled,
                "skills": len(plugin.skills),
                "commands": len(plugin.commands),
                "agents": len(plugin.agents),
                "mcp_servers": len(plugin.mcp_servers),
            }
            for plugin in plugins
        ],
        "mcp_servers": [
            _validate_mcp_server(name, config)
            for name, config in sorted(mcp_servers.items())
        ],
        "system_prompt_preview": _safe_short(system_prompt_text, limit=600),
    }
    mcp_errors = sum(1 for entry in preview["mcp_servers"] if entry.get("status") == "error")
    preview["validation"]["mcp_errors"] = mcp_errors
    preview["readiness"] = _evaluate_dry_run_readiness(
        prompt=preview_prompt,
        entrypoint=preview["entrypoint"],
        validation=preview["validation"],
    )
    return preview


def _format_dry_run_preview(preview: dict[str, object]) -> str:
    settings = preview.get("settings") if isinstance(preview.get("settings"), dict) else {}
    validation = preview.get("validation") if isinstance(preview.get("validation"), dict) else {}
    entrypoint = preview.get("entrypoint") if isinstance(preview.get("entrypoint"), dict) else {}
    readiness = preview.get("readiness") if isinstance(preview.get("readiness"), dict) else {}
    recommendations = preview.get("recommendations") if isinstance(preview.get("recommendations"), dict) else {}
    plugins = preview.get("plugins") if isinstance(preview.get("plugins"), list) else []
    skills = preview.get("skills") if isinstance(preview.get("skills"), list) else []
    commands = preview.get("commands") if isinstance(preview.get("commands"), list) else []
    tools = preview.get("tools") if isinstance(preview.get("tools"), list) else []
    mcp_servers = preview.get("mcp_servers") if isinstance(preview.get("mcp_servers"), list) else []

    lines = [
        "QuestorHarness Dry Run",
        "",
        "Readiness",
        f"- level: {readiness.get('level', 'unknown')}",
    ]
    readiness_reasons = readiness.get("reasons")
    if isinstance(readiness_reasons, list):
        for reason in readiness_reasons[:4]:
            lines.append(f"- {reason}")
    readiness_actions = readiness.get("next_actions")
    if isinstance(readiness_actions, list) and readiness_actions:
        lines.append("- next actions:")
        for action in readiness_actions[:4]:
            lines.append(f"  - {action}")
    lines.extend(
        [
        "",
        "Execution",
        f"- cwd: {preview.get('cwd')}",
        f"- prompt: {preview.get('prompt_preview') or '(none)'}",
        f"- entrypoint: {entrypoint.get('kind', 'unknown')}",
        f"- detail: {entrypoint.get('detail', '')}",
        "",
        "Resolved Settings",
        f"- profile: {settings.get('active_profile')} ({settings.get('profile_label')})",
        f"- provider: {settings.get('provider')}",
        f"- api_format: {settings.get('api_format')}",
        f"- model: {settings.get('model')}",
        f"- base_url: {settings.get('base_url') or '(default)'}",
        f"- permission_mode: {settings.get('permission_mode')}",
        f"- max_turns: {settings.get('max_turns')}",
        f"- effort: {settings.get('effort')} / passes={settings.get('passes')}",
        "",
        "Validation",
        f"- auth: {validation.get('auth_status')}",
        f"- api client: {validation.get('api_client', {}).get('status', 'unknown')}",
        f"- system prompt chars: {validation.get('system_prompt_chars')}",
        f"- mcp: {validation.get('mcp_validation')}",
        f"- mcp config errors: {validation.get('mcp_errors', 0)}",
        "",
        "Discovery",
        f"- plugins: {len(plugins)}",
        f"- skills: {len(skills)}",
        f"- slash commands: {len(commands)}",
        f"- built-in tools: {len(tools)}",
        f"- configured mcp servers: {len(mcp_servers)}",
        ]
    )

    if mcp_servers:
        lines.extend(["", "Configured MCP"])
        for entry in mcp_servers[:8]:
            status = entry.get("status") or "unknown"
            suffix = ""
            issues = entry.get("issues")
            if isinstance(issues, list) and issues:
                suffix = f" [{'; '.join(str(item) for item in issues)}]"
            lines.append(
                f"- {entry.get('name')}: {entry.get('transport')} -> {entry.get('target')} ({status}){suffix}"
            )
        if len(mcp_servers) > 8:
            lines.append(f"- ... (+{len(mcp_servers) - 8} more)")

    if tools:
        lines.extend(["", "Available Tools"])
        for entry in tools[:12]:
            required = entry.get("required_args") or []
            optional = entry.get("optional_args") or []
            signature_parts: list[str] = []
            if required:
                signature_parts.append("required: " + ", ".join(required))
            if optional:
                signature_parts.append("optional: " + ", ".join(optional[:4]))
            suffix = f" ({'; '.join(signature_parts)})" if signature_parts else ""
            lines.append(f"- {entry.get('name')}{suffix}")
        if len(tools) > 12:
            lines.append(f"- ... (+{len(tools) - 12} more)")

    if skills:
        lines.extend(["", "Available Skills"])
        for entry in skills[:8]:
            lines.append(f"- {entry.get('name')}: {_safe_short(str(entry.get('description') or ''), limit=100)}")
        if len(skills) > 8:
            lines.append(f"- ... (+{len(skills) - 8} more)")

    recommended_skills = recommendations.get("skills") if isinstance(recommendations.get("skills"), list) else []
    recommended_tools = recommendations.get("tools") if isinstance(recommendations.get("tools"), list) else []
    recommended_commands = recommendations.get("commands") if isinstance(recommendations.get("commands"), list) else []
    if recommended_skills or recommended_tools or recommended_commands:
        lines.extend(["", "Likely Matches"])
        if recommended_skills:
            lines.append("- skills:")
            for entry in recommended_skills[:4]:
                reasons = ", ".join(str(item) for item in entry.get("reasons") or [])
                suffix = f" [{reasons}]" if reasons else ""
                lines.append(f"  - {entry.get('name')} (score={entry.get('score')}){suffix}")
        if recommended_tools:
            lines.append("- tools:")
            for entry in recommended_tools[:6]:
                reasons = ", ".join(str(item) for item in entry.get("reasons") or [])
                suffix = f" [{reasons}]" if reasons else ""
                lines.append(f"  - {entry.get('name')} (score={entry.get('score')}){suffix}")
        if recommended_commands:
            lines.append("- slash commands:")
            for entry in recommended_commands[:4]:
                reasons = ", ".join(str(item) for item in entry.get("reasons") or [])
                suffix = f" [{reasons}]" if reasons else ""
                lines.append(f"  - /{entry.get('name')} (score={entry.get('score')}){suffix}")

    if entrypoint.get("kind") == "slash_command":
        lines.extend(
            [
                "",
                "Slash Command Detail",
                f"- command: /{entrypoint.get('command')}",
                f"- description: {entrypoint.get('description')}",
                f"- behavior: {entrypoint.get('behavior')}",
                f"- remote_invocable: {entrypoint.get('remote_invocable')}",
                f"- remote_admin_opt_in: {entrypoint.get('remote_admin_opt_in')}",
            ]
        )
        args = str(entrypoint.get("args") or "").strip()
        if args:
            lines.append(f"- args: {args}")

    preview_text = str(preview.get("system_prompt_preview") or "").strip()
    if preview_text:
        lines.extend(["", "System Prompt Preview", preview_text])

    return "\n".join(lines)

# questor: allow R7 -- until W8 adds the mirror test
# questor: allow R8 -- refactor the offenders in W8
