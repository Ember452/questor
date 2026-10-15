"""L2 权限引擎（design/03 §3/§4/§11；HARD C8/C9）。

机制而非策略：它只*判定* allow/ask/deny（纯），从不执行也不弹窗。执行点在 loop +
工具路由。求值次序按 design/03 §11（先判定者胜）：

  1. 敏感路径 denylist  -> DENY（不可覆盖；经 realpath+expanduser 解析， symlink/相对路径
     不能规避——补上 DeepCode 的 ``normpath`` 缺口，见 R10 §P-3）
  2. 只读上限             -> DENY 变更类工具（rules 不能放宽）
  3. 显式规则匹配         -> 其 action（二维通配，last-match-wins）
  4. mode 默认           -> 只读 allow / 变更 ask
  5. approval_policy=never -> 把 ASK 降为 DENY（fail-closed）

``reason`` 面向模型可读、并提示合法替代（errors-as-data）。
"""

from __future__ import annotations

import fnmatch
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from questor.contracts.common import JsonObject

#: 凭据/密钥路径，先于 rules 拦截；不被 mode/rules 覆盖。
SENSITIVE_PATH_PATTERNS: tuple[str, ...] = (
    "*/.ssh",
    "*/.ssh/*",
    "*/.aws/credentials",
    "*/.aws/config",
    "*/.gnupg/*",
    "*/.docker/config.json",
    "*/.kube/config",
    "*/.netrc",
    "*/.npmrc",
    "*/.pypirc",
    "*/.git-credentials",
    "*/.env",
    "*/.env.*",
    "*.pem",
    "*.key",
    "*id_rsa*",
    "*id_ed25519*",
)

_PATH_ARG_KEYS = ("file_path", "path", "root", "workspace_path", "target", "filename")
_PATCH_PATH_PREFIXES = ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")
_SHELL_TOOL_NAMES = ("bash", "exec", "execute_bash", "execute_commands")


class PermissionDecision(StrEnum):
    """三态权限决策（一等字段，design/01 §6）。"""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionMode(StrEnum):
    """工作模式，决定无规则命中时的隐式默认。"""

    DEFAULT = "default"
    PLAN = "plan"
    FULL_AUTO = "full_auto"


class ApprovalPolicy(StrEnum):
    """是否能将 ask 交给审批人；never 时 ask 降为 deny。"""

    ON_REQUEST = "on_request"
    NEVER = "never"


class PermissionEngine(ABC):
    """Decides allow/ask/deny for a proposed tool call (+ a readable reason)."""

    @abstractmethod
    def evaluate(self, tool_name: str, arguments: JsonObject | None = None) -> tuple[str, str]:
        """``deny`` never counts as a failed retry (01 §6)."""


def _normalize_path(raw: str, cwd: Path) -> str:
    """把路径规范化为绝对、去符号链接的小写形式（供 denylist 匹配）。"""
    try:
        p = Path(os.path.expanduser(raw))
        resolved = p if p.is_absolute() else cwd / p
        # realpath 在 POSIX 与 Windows 上都解符号链接/junction。
        return os.path.normcase(os.path.realpath(resolved))
    except OSError:
        return os.path.normcase(raw)


def _hits_sensitive(arguments: Mapping[str, object], cwd: Path) -> str | None:
    """若任一参数路径命中敏感集，返回那个原始路径（否则 None）。"""
    for raw in _candidate_paths(arguments):
        probe = _normalize_path(raw, cwd).replace("\\", "/")
        basename = os.path.basename(probe)
        for pattern in SENSITIVE_PATH_PATTERNS:
            if fnmatch.fnmatch(probe, pattern) or fnmatch.fnmatch(basename, pattern):
                return raw
    return None


def _candidate_paths(arguments: Mapping[str, object]) -> list[str]:
    """从参数里抽出“路径”候选：path 类键 + apply_patch 的结构化前缀行（03 §11 抽词典）。"""
    paths: list[str] = []
    for key in _PATH_ARG_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value)
        elif isinstance(value, (list, tuple)):
            paths.extend(v for v in value if isinstance(v, str) and v.strip())
    patch = arguments.get("patch")
    if isinstance(patch, str):
        for line in patch.splitlines():
            for prefix in _PATCH_PATH_PREFIXES:
                if line.startswith(prefix):
                    cand = line[len(prefix) :].strip()
                    if cand:
                        paths.append(cand)
                    break
    return paths


def _argument_string(tool_name: str, arguments: Mapping[str, object]) -> str:
    """供 pattern 规则匹配的“参数字符串”：shell 取命令、否则取首个路径类参。"""
    if tool_name in _SHELL_TOOL_NAMES:
        for key in ("command", "cmd", "commands", "script"):
            value = arguments.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, (list, tuple)):
                return " ".join(str(v) for v in value)
    for key in _PATH_ARG_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return " ".join(f"{k}={v}" for k, v in sorted(arguments.items()))


class Rule:
    """ ``(permission, pattern) -> action`` 通配规则；两侧均用 fnmatch 匹配。"""

    __slots__ = ("action", "pattern", "permission")

    def __init__(self, permission: str, pattern: str, action: PermissionDecision) -> None:
        self.permission = permission
        self.pattern = pattern
        self.action = action

    def matches(self, tool_name: str, argument: str) -> bool:
        """工具名与参数串同时匹配才算命中。"""
        return fnmatch.fnmatch(tool_name, self.permission) and fnmatch.fnmatch(argument, self.pattern)


class DefaultPermissionEngine(PermissionEngine):
    """按 design/03 §11 八步次序求值的默认引擎。"""

    def __init__(
        self,
        *,
        mode: PermissionMode = PermissionMode.DEFAULT,
        rules: Sequence[Rule] = (),
        read_only_tools: frozenset[str] = frozenset(),
        approval_policy: ApprovalPolicy = ApprovalPolicy.ON_REQUEST,
        protect_sensitive_paths: bool = True,
        enforce_read_only: bool = False,
        cwd: Path | None = None,
    ) -> None:
        self.mode = mode
        self.rules = list(rules)
        self.read_only_tools = read_only_tools
        self.approval_policy = approval_policy
        self.protect_sensitive_paths = protect_sensitive_paths
        self.enforce_read_only = enforce_read_only
        self.cwd = cwd or Path.cwd()

    def is_read_only(self, tool_name: str) -> bool:
        """工具是否在只读集内（默认允许、plan 不拦）。"""
        return tool_name in self.read_only_tools

    def evaluate(self, tool_name: str, arguments: JsonObject | None = None) -> tuple[str, str]:
        """返回 ``(decision, reason)``；decision 为 allow/ask/deny 之一。"""
        args = arguments or {}

        if self.protect_sensitive_paths:
            offending = _hits_sensitive(args, self.cwd)
            if offending is not None:
                return PermissionDecision.DENY, (
                    f"Access to '{offending}' is blocked: it matches the non-overridable "
                    "sensitive-path denylist (credentials/secrets). Rules/mode cannot override it."
                )

        read_only = self.is_read_only(tool_name)
        if self.enforce_read_only and not read_only:
            return PermissionDecision.DENY, "read-only preset: mutating tools cannot be enabled by rules"

        argument = _argument_string(tool_name, args)
        matched: Rule | None = next((r for r in reversed(self.rules) if r.matches(tool_name, argument)), None)
        if matched is not None:
            return self._apply_policy(matched.action, f"matched rule {matched.permission!r} {matched.pattern!r} -> {matched.action.value}")

        if self.mode is PermissionMode.PLAN:
            if read_only:
                return PermissionDecision.ALLOW, "plan mode: read-only tool allowed"
            return PermissionDecision.DENY, "plan mode: mutating tools are denied until the plan is approved"
        if self.mode is PermissionMode.FULL_AUTO:
            return PermissionDecision.ALLOW, "full_auto mode: no implicit gate"
        if read_only:
            return PermissionDecision.ALLOW, "default mode: read-only tool allowed"
        return self._apply_policy(PermissionDecision.ASK, "default mode: mutating tool requires confirmation")

    def _apply_policy(self, decision: PermissionDecision, reason: str) -> tuple[str, str]:
        """never 时把 ask fail-closed 降为 deny（不自动放行）。"""
        if decision is PermissionDecision.ASK and self.approval_policy is ApprovalPolicy.NEVER:
            return PermissionDecision.DENY, f"{reason}; approval policy is never -> denied"
        return decision.value, reason
