#!/usr/bin/env python3
"""Record and verify the model-visible surface per host (plan 01, W3).

For every host we render the real system prompt and the real ``tools[]`` payload
and store them as diffable text. The rendering inputs are pinned:

* ``EnvironmentInfo`` is injected (cwd, date, python path, hostname, ... fixed);
* ``get_platform`` is stubbed so a Windows laptop and an Ubuntu runner agree;
* user skills, user plugins and local rules are blanked, because they live in the
  developer's home directory and would make the snapshot machine-specific;
* ``CLAUDE_CODE_COORDINATOR_MODE`` is unset, because it switches the whole prompt
  branch (``capabilities/context/coordinator.py``).

The cwd is a throwaway directory under ``.tmp-baseline/`` so ``CLAUDE.md``,
project skills and project memory are all absent.

Usage:
    uv run python scripts/ci/prompt_surface.py --record
    uv run python scripts/ci/prompt_surface.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.baseline_check import _normalize  # noqa: E402

# Diffs contain box-drawing and CJK text; a cp936 console made print() raise
# UnicodeEncodeError and swallow the evidence this command exists to show.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

SNAPSHOT_DIR = REPO_ROOT / "tests" / "fixtures" / "baseline" / "prompt_surface"
SCRATCH = REPO_ROOT / ".tmp-baseline" / "prompt-surface"

ENVIRONMENT_PATCH = "questorharness.capabilities.context.prompts.system_prompt.get_environment_info"
PLATFORM_PATCH = "questorharness.capabilities.context.prompts.context.get_platform"
RULES_PATCH = "questorharness.capabilities.context.prompts.context.load_local_rules"
USER_SKILLS_PATCH = "questorharness.capabilities.skills.loader.get_user_skill_dirs"


@dataclass(frozen=True)
class Host:
    """One rendering profile, traced to the call site it mirrors."""

    name: str
    include_project_memory: bool
    latest_user_prompt: str | None
    gateway_tools: bool
    provenance: str


# The remaining hosts share one assembly function (bootstrap/runtime.py:367); the
# differences below are the inputs each host really passes.
HOSTS: tuple[Host, ...] = (
    Host("cli", True, None, False, "bootstrap/runtime.py:367 with default settings"),
    Host("channel", False, None, True, "questor/gateway/runtime.py:702 include_project_memory=False"),
    Host("cron", True, "Run the scheduled task.", False, "bootstrap/runtime.py:680 with a cron prompt"),
)


def _fixed_environment():  # noqa: ANN202 - dataclass from the app
    from questorharness.capabilities.context.prompts.environment import EnvironmentInfo

    return EnvironmentInfo(
        os_name="Linux",
        os_version="<OS>",
        platform_machine="<ARCH>",
        shell="bash",
        cwd="/workspace",
        home_dir="/home/user",
        date="2026-01-01",
        python_version="3.11.0",
        python_executable="/usr/bin/python3",
        virtual_env=None,
        is_git_repo=True,
        git_branch="main",
        hostname="<HOST>",
    )


def _settings():
    from questorharness.config.settings_models import Settings

    return Settings()


def _tool_payload(host: Host) -> list[dict[str, object]]:
    from questorharness.capabilities.tools.registry import create_default_tool_registry

    registry = create_default_tool_registry(None)
    if host.gateway_tools:
        from questor.gateway.group_tool import QuestorCreateFeishuGroupTool

        # The gateway registers one extra tool on top of the built-ins; the
        # collaborators are inert because only the schema is rendered.
        registry.register(
            QuestorCreateFeishuGroupTool(
                workspace=Path("/workspace"),
                create_group=lambda **_kwargs: None,
            )
        )
    return registry.to_api_schema()


def _machine_independent(text: str) -> str:
    """抹平随机器变化的渲染,让快照在任意平台可比。

    路径分隔符的行级归一化已由 ``baseline_check._normalize`` 统一承担(含
    ``<HOME>``/``<REPO>`` 掩码的行整行统一分隔符);这里只补快照特有的
    一步——各宿主记忆目录的路径哈希(如 ``cli-cda39b73afba``)由当机
    checkout 路径派生,任何机器都不该和别人一致,快照里只留 ``<HASH>``。
    """
    return re.sub(r"\b(cli|desktop|channel|cron)-[0-9a-f]{6,}\b", r"\1-<HASH>", text)


def _render(host: Host) -> str:
    from questorharness.capabilities.context.prompts.context import build_runtime_system_prompt
    from questorharness.capabilities.skills.loader import configure_plugin_source
    from questorharness.plugins.source import NullPluginSource

    workdir = SCRATCH / host.name
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    # Snapshots must not depend on the developer's home directory: no user
    # plugins, no user skills, no local rules.
    configure_plugin_source(NullPluginSource())
    with (
        mock.patch(ENVIRONMENT_PATCH, return_value=_fixed_environment()),
        mock.patch(PLATFORM_PATCH, return_value="linux"),
        mock.patch(RULES_PATCH, return_value=""),
        mock.patch(USER_SKILLS_PATCH, return_value=[]),
    ):
        prompt = build_runtime_system_prompt(
            _settings(),
            cwd=str(workdir),
            latest_user_prompt=host.latest_user_prompt,
            include_project_memory=host.include_project_memory,
        )

    tools = _tool_payload(host)
    return "\n".join(
        [
            f"# host: {host.name}",
            "",
            f"<!-- {host.provenance} -->",
            "",
            "## system_prompt",
            "",
            _machine_independent(_normalize(prompt)).rstrip(),
            "",
            "## tools",
            "",
            json.dumps(tools, indent=2, sort_keys=True),
            "",
        ]
    )


def _target(host: Host) -> Path:
    return SNAPSHOT_DIR / f"{host.name}.txt"


def record() -> int:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for host in HOSTS:
        text = _render(host)
        _target(host).write_text(text, encoding="utf-8", newline="\n")
        print(f"recorded {_target(host).relative_to(REPO_ROOT)} ({len(text.splitlines())} lines)")
    return 0


def check() -> int:
    import difflib

    failures: list[str] = []
    for host in HOSTS:
        target = _target(host)
        if not target.exists():
            failures.append(f"{host.name}: snapshot missing ({target.relative_to(REPO_ROOT)})")
            continue
        expected = target.read_text(encoding="utf-8")
        actual = _render(host)
        if expected == actual:
            continue
        diff = list(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=f"baseline/prompt_surface/{host.name}.txt",
                tofile=f"current/{host.name}.txt",
                lineterm="",
                n=2,
            )
        )
        failures.append(f"--- {host.name} differs ---\n" + "\n".join(diff[:40]))

    if failures:
        print("PROMPT SURFACE CHECK FAILED")
        for failure in failures:
            print(failure)
        return 1
    hosts = ", ".join(host.name for host in HOSTS)
    print(f"prompt surface: OK ({len(HOSTS)} hosts: {hosts}; {len(_tool_payload(HOSTS[0]))} tools)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    os.environ.pop("CLAUDE_CODE_COORDINATOR_MODE", None)
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--record", action="store_true", help="rewrite the snapshots (local only)")
    action.add_argument("--check", action="store_true", help="fail when a snapshot is stale")
    action.add_argument("--list-hosts", action="store_true", help="print the host table")
    args = parser.parse_args(argv)

    if args.list_hosts:
        for host in HOSTS:
            print(f"{host.name}: {host.provenance}")
        return 0
    # 阶段 2 删除刀：desktop（React backend）宿主消失，覆盖数从 4 降到 3。
    assert len(HOSTS) == 3, "host coverage dropped below three"
    return record() if args.record else check()


if __name__ == "__main__":
    raise SystemExit(main())
