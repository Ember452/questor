"""L5 subprocess credential scrub（ADR-0018）。

威胁模型：父进程环境变量 → subprocess stdout/stderr → 下一轮 prompt → 第三方 relay。
默认擦除 credential-shaped names；provider credentials 永不因 declare 而透传。
credential blocklist 纪律在本仓独立实现。
"""

from __future__ import annotations

import os
import re

# 凭据形状：涵盖常见厂商/命名（AWS_ACCESS_KEY_ID、GH_PAT、STRIPE_KEY、*_PRIVATE 等）。
# 均以 `(?:^|_)...(?:S)?(?:$|_)` 边界匹配，不误伤 MONKEY/PATH/REPEAT 等普通词；`(?:S)?` 允许复数
# （如 QUESTOR_OPENAI_API_KEYS 的 KEYS），否则复数键会绕过擦除（W6-003）。
_CREDENTIAL_SHAPE = re.compile(
    r"(?:^|_)(?:API_?KEY|ACCESS_KEY|ACCESS_TOKEN|AUTH_TOKEN|AUTH|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE_KEY|PRIVATE|TOKEN|PAT|KEY)S?(?:$|_)",
    re.IGNORECASE,
)
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

# 值内嵌凭据（URL userinfo `scheme://user:pass@host`）——即便变量名安全（如代理 URL），也一律不透传（#181）。
_URL_USERINFO = re.compile(r"://[^/@:]+:[^/@]+@")


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
        if not _is_safe_name(key) and _is_credential_shape(key):
            removed.append(key)
            continue
        if _URL_USERINFO.search(value or ""):  # 值内嵌 user:pass@ 凭据，名字再安全也不透传（#181）
            removed.append(key)
            continue
        kept[key] = value
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
