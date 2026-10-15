"""L2 permission engine (design/03 §3/§4/§11; HARD C8/C9).

Mechanism, not policy: it *decides* allow/ask/deny (pure), never executes or
prompts. Enforcement points are the loop + tool executor. Evaluation order follows
design/03 §11 (first decisive wins):

  1. sensitive-path denylist  -> DENY (non-overridable; resolved via
     realpath+expanduser so a symlink/relative path can't dodge it — the gap
     DeepCode's ``normpath`` left, per R10 §P-3)
  2. read-only preset upper bound -> DENY mutating tools (rules can't widen)
  3. explicit rule match      -> its action (two-dimensional wildcard, last-wins)
  4. mode default             -> read-only allow / mutating ask
  5. approval_policy=never    -> demote ASK to DENY (fail-closed)

``reason`` is model-readable and hints a legal alternative (errors-as-data).
"""

from __future__ import annotations

import fnmatch
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from questor.contracts.common import JsonObject

#: Credential / secret paths blocked ahead of rules; not overridable by mode/rules.
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
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    FULL_AUTO = "full_auto"


class ApprovalPolicy(StrEnum):
    ON_REQUEST = "on_request"
    NEVER = "never"


class PermissionEngine(ABC):
    """Decides allow/ask/deny for a proposed tool call (+ a readable reason)."""

    @abstractmethod
    def evaluate(self, tool_name: str, arguments: JsonObject | None = None) -> tuple[str, str]:
        """``deny`` never counts as a failed retry (01 §6)."""


def _normalize_path(raw: str, cwd: Path) -> str:
    try:
        p = Path(os.path.expanduser(raw))
        resolved = p if p.is_absolute() else cwd / p
        # realpath resolves symlinks/junctions on both POSIX and Windows.
        return os.path.normcase(os.path.realpath(resolved))
    except OSError:
        return os.path.normcase(raw)


def _hits_sensitive(arguments: Mapping[str, object], cwd: Path) -> str | None:
    for raw in _candidate_paths(arguments):
        probe = _normalize_path(raw, cwd).replace("\\", "/")
        basename = os.path.basename(probe)
        for pattern in SENSITIVE_PATH_PATTERNS:
            if fnmatch.fnmatch(probe, pattern) or fnmatch.fnmatch(basename, pattern):
                return raw
    return None


def _candidate_paths(arguments: Mapping[str, object]) -> list[str]:
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
    """A ``(permission, pattern) -> action`` wildcard; both match via fnmatch."""

    __slots__ = ("action", "pattern", "permission")

    def __init__(self, permission: str, pattern: str, action: PermissionDecision) -> None:
        self.permission = permission
        self.pattern = pattern
        self.action = action

    def matches(self, tool_name: str, argument: str) -> bool:
        return fnmatch.fnmatch(tool_name, self.permission) and fnmatch.fnmatch(argument, self.pattern)


class DefaultPermissionEngine(PermissionEngine):
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
        return tool_name in self.read_only_tools

    def evaluate(self, tool_name: str, arguments: JsonObject | None = None) -> tuple[str, str]:
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
        if decision is PermissionDecision.ASK and self.approval_policy is ApprovalPolicy.NEVER:
            return PermissionDecision.DENY, f"{reason}; approval policy is never -> denied"
        return decision.value, reason
