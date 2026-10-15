"""L5 subprocess credential scrub（ADR-0018）。

威胁模型：父进程环境变量 → subprocess stdout/stderr → 下一轮 prompt → 第三方 relay。
默认擦除 credential-shaped names；provider credentials 永不因 declare 而透传。
hermes ``env_passthrough.py:46-92`` 的 credential blocklist 纪律为参照，本仓独立实现。
"""

from __future__ import annotations

import os
import re

_CREDENTIAL_SHAPE = re.compile(r"(?:^|_)(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE_KEY|TOKEN)(?:$|_)", re.IGNORECASE)
_PROVIDER_EXACT = frozenset(
    {
        "LITELLM_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "COHERE_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
    }
)
_SAFE_PREFIXES = ("PATH", "HOME", "USERPROFILE", "LANG", "LC_", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP")


def is_provider_credential(name: str) -> bool:
    """Questor/LiteLLM 管理凭据永远不可透传，大小写不敏感。"""
    key = name.upper()
    return key in _PROVIDER_EXACT or key.startswith("QUESTOR_") and _CREDENTIAL_SHAPE.search(key) is not None or key.startswith("LITELLM_") and _CREDENTIAL_SHAPE.search(key) is not None


def _is_safe_name(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(_SAFE_PREFIXES) or upper in {"PYTHONPATH", "PYTHONHOME", "PYTHONIOENCODING", "SYSTEMDRIVE", "WINDIR"}


def _is_credential_shape(name: str) -> bool:
    return _CREDENTIAL_SHAPE.search(name.upper()) is not None


def scrub_environment(env: dict[str, str] | None = None) -> tuple[dict[str, str], tuple[str, ...]]:
    """返回 ``(保留环境, 被擦除 names)``；names 不含值。"""
    source = os.environ if env is None else env
    kept: dict[str, str] = {}
    removed: list[str] = []
    for key, value in source.items():
        if _is_safe_name(key) or not _is_credential_shape(key):
            kept[key] = value
        else:
            removed.append(key)
    return kept, tuple(sorted(removed))


def build_child_env(
    scrubbed_env: dict[str, str],
    *,
    declared: tuple[str, ...],
    source_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """构造子进程 env；provider credential 即使被 declare 也抛错。"""
    source = os.environ if source_env is None else source_env
    result = dict(scrubbed_env)
    for name in declared:
        if is_provider_credential(name):
            raise PermissionError(f"{name} is a provider credential and cannot be passed through")
        if not _is_credential_shape(name):
            continue
        if name in source:
            result[name] = source[name]
    return result


__all__ = ["build_child_env", "is_provider_credential", "scrub_environment"]
