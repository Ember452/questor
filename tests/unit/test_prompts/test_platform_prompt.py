from __future__ import annotations

from pathlib import Path

from questorharness.config.settings import Settings
from questorharness.platform import get_platform
from questorharness.prompts.context import build_runtime_system_prompt


def test_runtime_prompt_includes_windows_guidance_on_windows(tmp_path: Path) -> None:
    prompt = build_runtime_system_prompt(Settings(), cwd=tmp_path)

    if get_platform() == "windows":
        assert "# Host Platform" in prompt
        assert "running on Windows" in prompt
        assert "sed" in prompt
    else:
        assert "# Host Platform" not in prompt
