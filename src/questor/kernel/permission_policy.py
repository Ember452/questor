"""L2 纯权限求值（ADR-0006/0014；design/03 §11）。

引擎自身没有配置：mode/rules/denylist/approval policy 全从权威 PermissionCtx 读取。
这样 `SetPermissionMode` 改 Domain_State 后，下一次调用必然看到新模式（ADR-0014）。

部分 pattern/argument 语义改造自 DeepCode ``core/harness/permissions.py``，MIT License；
本仓改成 PermissionEvaluation/Outcome，不把完整参数原样外发。
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from questor.contracts.common import JsonObject, thaw
from questor.contracts.sandbox import SandboxDescriptor
from questor.contracts.shell_analysis import ShellAnalysis
from questor.contracts.state_schema import ToolArgsStatus
from questor.contracts.tool import ToolSpec
from questor.contracts.tool_args import PROTECTED_IN_ROOTS
from questor.kernel.tool_arguments import extract_paths, extract_shell_commands
from questor.state.domain_state import PermissionCtx


class PermissionDecision(StrEnum):
    """三态权限决策。"""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PermissionEvaluation:
    """一次工具调用的全部权限事实。"""

    tool_name: str
    tool_spec: ToolSpec
    args_status: ToolArgsStatus
    arguments: JsonObject
    permission: PermissionCtx
    sandbox: SandboxDescriptor
    raw_args_summary: str | None = None
    shell_analysis: ShellAnalysis | None = None

    def __post_init__(self) -> None:
        # 权限对象不能跨 await 被调用方原地改；转成普通 dict 仅供本纯函数读取。
        object.__setattr__(self, "arguments", thaw(self.arguments) if isinstance(self.arguments, dict) else dict(self.arguments))


@dataclass(frozen=True, slots=True)
class PermissionOutcome:
    """权限结果；summary/warnings 均是有界、可展示事实。"""

    decision: PermissionDecision
    reason: str
    args_summary: str
    warnings: tuple[str, ...] = ()
    floor_applied: str | None = None
    candidate_paths: tuple[str, ...] = field(default_factory=tuple)


_SENSITIVE_DIRS = {".ssh", ".aws", ".gnupg", ".docker", ".kube", ".azure", ".config/gcloud"}
_SENSITIVE_BASENAMES = {".env", ".netrc", ".npmrc", ".pypirc", ".git-credentials", "credentials", "config", "id_rsa", "id_ed25519"}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def _path_matches(raw: str, cwd: Path) -> tuple[bool, bool]:
    """返回 ``(sensitive, protected_root)``；realpath 失败时按不安全处理。"""
    candidate = Path(os.path.expandvars(os.path.expanduser(raw)))
    candidate = candidate if candidate.is_absolute() else cwd / candidate
    try:
        resolved = Path(os.path.normcase(os.path.realpath(candidate)))
    except OSError:
        # 坏 symlink/junction/权限错误不能退回 raw 字符串匹配；直接 deny（R04 缺口）。
        return True, False
    normalized = str(resolved).replace("\\", "/").lower()
    parts = [part for part in normalized.split("/") if part]
    basename = parts[-1] if parts else ""
    sensitive = (
        any(part in _SENSITIVE_DIRS for part in parts)
        or basename in _SENSITIVE_BASENAMES
        or basename.startswith(".env.")
        or any(basename.startswith(prefix) for prefix in ("id_rsa", "id_ed25519"))
        or os.path.splitext(basename)[1] in _SENSITIVE_SUFFIXES
    )
    protected_root = any(fnmatch.fnmatch(basename, pattern) for pattern in PROTECTED_IN_ROOTS)
    return sensitive, protected_root


def _candidate_paths(evaluation: PermissionEvaluation) -> tuple[str, ...]:
    """从 args、patch headers 与 shell IR 聚合所有路径候选。"""
    candidates = list(extract_paths(evaluation.arguments))
    if evaluation.shell_analysis is not None:
        candidates.extend(evaluation.shell_analysis.read_paths)
        candidates.extend(evaluation.shell_analysis.write_paths)
    return tuple(dict.fromkeys(item for item in candidates if isinstance(item, str) and item.strip()))


def _argument_string(evaluation: PermissionEvaluation) -> str:
    """给规则匹配的稳定参数字符串；shell 优先用已解析 command。"""
    commands = extract_shell_commands(evaluation.arguments)
    if evaluation.shell_analysis is not None and evaluation.shell_analysis.segments:
        return " ".join(" ".join((segment.program, *segment.args)) for segment in evaluation.shell_analysis.segments)
    if commands:
        return " ".join(commands)
    paths = extract_paths(evaluation.arguments)
    if paths:
        return paths[0]
    return " ".join(f"{key}={value}" for key, value in sorted(evaluation.arguments.items()))


def _matches(rule_pattern: str, value: str) -> bool:
    return fnmatch.fnmatch(value.lower(), rule_pattern.lower())


def _redact_value(key: str, value: Any) -> str:
    lowered = key.lower()
    if any(token in lowered for token in ("key", "token", "secret", "password", "credential")):
        return "[redacted]"
    rendered = str(value)
    return rendered if len(rendered) <= 160 else rendered[:157] + "..."


def _summarize_arguments(evaluation: PermissionEvaluation) -> str:
    """有界且脱敏的 args 摘要，供审批事件/日志使用。"""
    if evaluation.raw_args_summary and evaluation.args_status is not ToolArgsStatus.VALID:
        return evaluation.raw_args_summary[:512]
    parts = [f"{key}={_redact_value(key, value)}" for key, value in sorted(evaluation.arguments.items())]
    return ", ".join(parts)[:512] or evaluation.tool_name


def _never_downgrade(outcome: PermissionOutcome, permission: PermissionCtx) -> PermissionOutcome:
    if outcome.decision is PermissionDecision.ASK and permission.approval_policy == "never":
        return PermissionOutcome(
            decision=PermissionDecision.DENY,
            reason=f"{outcome.reason}; approval policy is never -> denied",
            args_summary=outcome.args_summary,
            warnings=outcome.warnings,
            floor_applied=outcome.floor_applied,
            candidate_paths=outcome.candidate_paths,
        )
    return outcome


def _apply_approval_mode(outcome: PermissionOutcome, spec: ToolSpec, permission: PermissionCtx) -> PermissionOutcome:
    mode = (spec.approval_mode or "").strip().lower()
    if not mode or outcome.decision is PermissionDecision.DENY:
        return outcome
    if mode in {"auto", "approve"}:
        return outcome
    if mode == "prompt":
        if outcome.decision is PermissionDecision.ALLOW:
            outcome = PermissionOutcome(
                decision=PermissionDecision.ASK,
                reason=f"{outcome.reason}; tool policy requires confirmation",
                args_summary=outcome.args_summary,
                warnings=outcome.warnings,
                floor_applied="approval-mode",
                candidate_paths=outcome.candidate_paths,
            )
        return _never_downgrade(outcome, permission)
    if mode == "writes":
        if spec.read_only:
            return outcome
        if outcome.decision is PermissionDecision.ALLOW:
            outcome = PermissionOutcome(
                decision=PermissionDecision.ASK,
                reason=f"{outcome.reason}; non-read-only tool policy requires confirmation",
                args_summary=outcome.args_summary,
                warnings=outcome.warnings,
                floor_applied="approval-mode",
                candidate_paths=outcome.candidate_paths,
            )
        return _never_downgrade(outcome, permission)
    return PermissionOutcome(
        decision=PermissionDecision.DENY,
        reason=f"unknown MCP approval mode {spec.approval_mode!r} (fail-closed)",
        args_summary=outcome.args_summary,
        warnings=outcome.warnings,
        floor_applied="approval-mode",
        candidate_paths=outcome.candidate_paths,
    )


def evaluate_permission(evaluation: PermissionEvaluation) -> PermissionOutcome:
    """执行 design/03 §11 八步；非法参数与敏感路径先于 rules/mode。"""
    summary = _summarize_arguments(evaluation)
    cwd = Path(evaluation.permission.cwd or Path.cwd())
    paths = _candidate_paths(evaluation)

    if evaluation.args_status is not ToolArgsStatus.VALID:
        return PermissionOutcome(
            decision=PermissionDecision.DENY,
            reason=f"invalid or missing tool arguments: {evaluation.raw_args_summary or 'not a JSON object'}",
            args_summary=summary,
            floor_applied="invalid-arguments",
            candidate_paths=paths,
        )

    if evaluation.permission.protect_sensitive_paths:
        sensitive_path = next((path for path in paths if _path_matches(path, cwd)[0]), None)
        if sensitive_path is not None:
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason=f"Access to '{sensitive_path}' is blocked by the non-overridable sensitive-path denylist.",
                args_summary=summary,
                floor_applied="sensitive-path",
                candidate_paths=paths,
            )
        protected_path = next((path for path in paths if _path_matches(path, cwd)[1]), None)
        if protected_path is not None:
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason=f"Access to '{protected_path}' is blocked because it controls Agent capabilities inside the workspace.",
                args_summary=summary,
                floor_applied="protected-root",
                candidate_paths=paths,
            )

    if evaluation.permission.enforce_read_only and not evaluation.tool_spec.read_only:
        return PermissionOutcome(
            decision=PermissionDecision.DENY,
            reason="read-only preset: mutating tools cannot be enabled by rules or mode",
            args_summary=summary,
            floor_applied="read-only-limit",
            candidate_paths=paths,
        )

    argument = _argument_string(evaluation)
    matched = next((rule for rule in reversed(evaluation.permission.rules) if _matches(rule.tool_pattern, evaluation.tool_name) and _matches(rule.argument_pattern, argument)), None)
    if matched is not None:
        decision = PermissionDecision(matched.action)
        reason = f"matched rule {matched.tool_pattern!r} {matched.argument_pattern!r} -> {decision.value}"
        outcome = PermissionOutcome(decision=decision, reason=reason, args_summary=summary, candidate_paths=paths)
        if decision is PermissionDecision.DENY:
            return outcome
        if decision is PermissionDecision.ALLOW:
            return _apply_approval_mode(outcome, evaluation.tool_spec, evaluation.permission)
        return _never_downgrade(_apply_approval_mode(outcome, evaluation.tool_spec, evaluation.permission), evaluation.permission)

    mode = evaluation.permission.mode
    if mode == "plan" and not evaluation.tool_spec.read_only:
        outcome = PermissionOutcome(
            decision=PermissionDecision.DENY,
            reason="plan mode: mutating tools are denied until the plan is approved",
            args_summary=summary,
            floor_applied="plan-mode",
            candidate_paths=paths,
        )
    elif mode == "full_auto" or evaluation.tool_spec.read_only:
        outcome = PermissionOutcome(
            decision=PermissionDecision.ALLOW,
            reason=f"{mode} mode: {evaluation.tool_name} allowed",
            args_summary=summary,
            candidate_paths=paths,
        )
    else:
        outcome = PermissionOutcome(
            decision=PermissionDecision.ASK,
            reason=f"{mode} mode: mutating tool requires confirmation",
            args_summary=summary,
            candidate_paths=paths,
        )
    return _never_downgrade(_apply_approval_mode(outcome, evaluation.tool_spec, evaluation.permission), evaluation.permission)


class DefaultPermissionEngine:
    """无配置权限引擎；实例只是稳定调用点，不拥有 mode/rules。"""

    def evaluate(self, evaluation: PermissionEvaluation) -> PermissionOutcome:
        return evaluate_permission(evaluation)


__all__ = [
    "DefaultPermissionEngine",
    "PermissionDecision",
    "PermissionEvaluation",
    "PermissionOutcome",
    "evaluate_permission",
]
