"""Interactive terminal prompts and the labels they show.

Leaf module: it knows how to ask a human a question and how to render a provider
name. It never touches settings, auth or the filesystem.
"""

from __future__ import annotations

import sys

import typer

# 提供商名称到交互提示可读标签的映射。
_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic (Claude API)",
    "anthropic_claude": "Claude subscription (Claude CLI)",
    "openai": "OpenAI / compatible",
    "openai_codex": "OpenAI Codex subscription (Codex CLI)",
    "copilot": "GitHub Copilot",
    "dashscope": "Alibaba DashScope",
    "bedrock": "AWS Bedrock",
    "vertex": "Google Vertex AI",
    "moonshot": "Moonshot (Kimi)",
    "gemini": "Google Gemini",
    "minimax": "MiniMax",
    "modelscope": "ModelScope",
}

_AUTH_SOURCE_LABELS: dict[str, str] = {
    "anthropic_api_key": "Anthropic API key",
    "openai_api_key": "OpenAI API key",
    "codex_subscription": "Codex subscription",
    "claude_subscription": "Claude subscription",
    "copilot_oauth": "GitHub Copilot OAuth",
    "dashscope_api_key": "DashScope API key",
    "bedrock_api_key": "Bedrock credentials",
    "vertex_api_key": "Vertex credentials",
    "moonshot_api_key": "Moonshot API key",
    "gemini_api_key": "Gemini API key",
    "minimax_api_key": "MiniMax API key",
    "modelscope_api_key": "ModelScope API key",
}


def _can_use_questionary() -> bool:
    """Return True when a real interactive terminal is available."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if sys.stdin is not sys.__stdin__ or sys.stdout is not sys.__stdout__:
        return False
    try:
        import questionary  # noqa: F401
    except ImportError:
        return False
    return True


def _select_with_questionary(
    title: str,
    options: list[tuple[str, str]],
    *,
    default_value: str | None = None,
) -> str:
    import questionary

    choices = [
        questionary.Choice(
            title=label,
            value=value,
            checked=(value == default_value),
        )
        for value, label in options
    ]
    result = questionary.select(title, choices=choices, default=default_value).ask()
    if result is None:
        raise typer.Abort()
    return str(result)


def _text_prompt(message: str, *, default: str = "") -> str:
    """Prompt for text input, preferring questionary in a real TTY."""
    if _can_use_questionary():
        import questionary

        result = questionary.text(message, default=default).ask()
        if result is None:
            raise typer.Abort()
        return str(result)
    # ``typer.prompt`` is typed as returning Any upstream; str() matches the questionary
    # branch above and keeps this function's declared ``str`` honest.
    return str(typer.prompt(message, default=default))


def _secret_prompt(message: str) -> str:
    """Prompt for secret text, preferring questionary in a real TTY."""
    if _can_use_questionary():
        import questionary

        result = questionary.password(message).ask()
        if result is None:
            raise typer.Abort()
        return str(result)
    return str(typer.prompt(message, hide_input=True))


def _confirm_prompt(message: str, *, default: bool = False) -> bool:
    """Prompt for a yes/no confirmation, preferring questionary in a real TTY."""
    if _can_use_questionary():
        import questionary

        result = questionary.confirm(message, default=default).ask()
        if result is None:
            raise typer.Abort()
        return bool(result)
    return bool(typer.confirm(message, default=default))


def _select_from_menu(
    title: str,
    options: list[tuple[str, str]],
    *,
    default_value: str | None = None,
) -> str:
    """Render a simple numbered picker and return the selected value."""
    if _can_use_questionary():
        return _select_with_questionary(title, options, default_value=default_value)
    print(title, flush=True)
    default_index = 1
    for index, (value, label) in enumerate(options, 1):
        marker = " (default)" if value == default_value else ""
        if value == default_value:
            default_index = index
        print(f"  {index}. {label}{marker}", flush=True)
    raw = typer.prompt("Choose", default=str(default_index))
    try:
        selected = options[int(raw) - 1]
    except (ValueError, IndexError):
        raise typer.BadParameter(f"Invalid selection: {raw}") from None
    return selected[0]
