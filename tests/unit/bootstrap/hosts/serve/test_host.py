"""host 模块镜像测试：构造期接线与不变式。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from questorharness.bootstrap.hosts.serve import ServeHost
from questorharness.bootstrap.hosts.serve.authority import Authority


def test_host_wires_notifier_and_keeps_injected_runtime(tmp_path: Path) -> None:
    """宿主收注入的 runtime，并把提示回调接到 authority（不自己建 runtime）。"""
    authority = Authority()
    runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
    host = ServeHost(runtime, authority=authority, profile_root=tmp_path)  # type: ignore[arg-type]
    assert host.runtime is runtime
    assert authority._on_prompt is not None
    assert host.profile_id == "coding"
    assert host.router is not None
