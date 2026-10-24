"""从磁盘读取 profile bundle。

校验是 fail-closed 的：未知键、错类型、非法能力位都会抛错，避免"写错了
但看起来生效"。空 ``allowed_tools`` 表示"不做 profile 级限制"。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from questorharness.profiles.model import ProfileInfo

_SUFFIX = ".yaml"
_ALLOWED_KEYS = frozenset(
    {
        "name",
        "description",
        "is_default",
        "model",
        "provider",
        "skill_dirs",
        "plugin_roots",
        "allowed_tools",
        "denied_tools",
        "ui",
    }
)
_CAPABILITY_STATES = frozenset({"ready", "declared", "absent"})


class ProfileError(Exception):
    """profile bundle 缺失或非法。"""


def _string_tuple(raw: Any, key: str, path: Path) -> tuple[str, ...]:
    """把 YAML 列表读成字符串元组。"""
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ProfileError(f"{path}: {key} must be a list of strings")
    return tuple(raw)


def _optional_str(raw: Any, key: str, path: Path) -> str | None:
    """可选字符串字段。"""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ProfileError(f"{path}: {key} must be a string")
    return raw


def _capabilities(raw: Any, path: Path) -> dict[str, str]:
    """解析 ui.capabilities；state 必须在三态内。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProfileError(f"{path}: ui must be a mapping")
    unknown = sorted(set(raw) - {"capabilities"})
    if unknown:
        raise ProfileError(f"{path}: ui has unsupported keys: {', '.join(unknown)}")
    capabilities = raw.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ProfileError(f"{path}: ui.capabilities must be a mapping")
    parsed: dict[str, str] = {}
    for page_id, state in capabilities.items():
        if not isinstance(page_id, str) or not isinstance(state, str):
            raise ProfileError(f"{path}: ui.capabilities entries must be string pairs")
        if state not in _CAPABILITY_STATES:
            raise ProfileError(f"{path}: capability {page_id} has invalid state {state!r}")
        parsed[page_id] = state
    return parsed


def _parse(raw: Any, path: Path) -> ProfileInfo:
    """把一份 YAML 文档解析成 ProfileInfo。"""
    if not isinstance(raw, dict):
        raise ProfileError(f"{path}: profile must be a mapping")
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        raise ProfileError(f"{path}: unsupported keys: {', '.join(unknown)}")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ProfileError(f"{path}: name is required")
    is_default = raw.get("is_default", False)
    if not isinstance(is_default, bool):
        raise ProfileError(f"{path}: is_default must be a boolean")
    return ProfileInfo(
        name=name,
        path=path,
        description=_optional_str(raw.get("description"), "description", path) or "",
        model=_optional_str(raw.get("model"), "model", path),
        provider=_optional_str(raw.get("provider"), "provider", path),
        skill_dirs=_string_tuple(raw.get("skill_dirs"), "skill_dirs", path),
        plugin_roots=_string_tuple(raw.get("plugin_roots"), "plugin_roots", path),
        allowed_tools=_string_tuple(raw.get("allowed_tools"), "allowed_tools", path),
        denied_tools=_string_tuple(raw.get("denied_tools"), "denied_tools", path),
        ui_capabilities=_capabilities(raw.get("ui"), path),
        is_default=is_default,
    )


def load_profile(root: Path, name: str) -> ProfileInfo:
    """按名字读取一个 profile；缺失即报错，不回退到默认。"""
    path = root / f"{name}{_SUFFIX}"
    if not path.is_file():
        raise ProfileError(f"unknown profile: {name}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _parse(raw, path)


def list_profiles(root: Path) -> tuple[ProfileInfo, ...]:
    """按文件名排序列出全部 profile。"""
    if not root.is_dir():
        raise ProfileError(f"profile root is not a directory: {root}")
    profiles = [
        _parse(yaml.safe_load(path.read_text(encoding="utf-8")), path)
        for path in sorted(root.glob(f"*{_SUFFIX}"))
    ]
    return tuple(profiles)


def boundary_map(profile: ProfileInfo) -> Mapping[str, str]:
    """便捷只读视图：页面 id → 能力位。"""
    return profile.ui_capabilities
