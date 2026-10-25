"""终端包契约：冷导入、公开面、徽标登记、prompt_toolkit 放行范围。"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]


def _load_layout_guard():
    """按文件路径加载守卫脚本（scripts/ 不是可 import 的包）。"""
    path = REPO_ROOT / "scripts" / "guards" / "check_layout.py"
    guards_dir = str(path.parent)
    added = guards_dir not in sys.path
    if added:
        sys.path.insert(0, guards_dir)
    try:
        spec = importlib.util.spec_from_file_location("check_layout_guard", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if added:
            sys.path.remove(guards_dir)


def test_package_is_cold_importable_and_declares_all() -> None:
    """新包必须能被冷导入，且 __all__ 有序列出真实存在的公开面。"""
    module = importlib.import_module("questorharness.bootstrap.hosts.terminal")
    assert module.__all__ == sorted(module.__all__)
    for name in module.__all__:
        assert hasattr(module, name), name


def test_unsupported_registry_ids_are_the_declared_gaps() -> None:
    """徽标登记表只装计划里登记为 absent 的缺口。"""
    from questorharness.bootstrap.hosts.terminal import unsupported

    assert set(unsupported.UNSUPPORTED) == {"A1", "A2", "A3", "A5", "A6"}


def test_prompt_toolkit_exemption_is_scoped_to_the_terminal_package() -> None:
    """放行范围只能是终端包与门面文件，其他模块仍然判红。"""
    guard = _load_layout_guard()
    assert guard._exempt_modules(
        "src/questorharness/bootstrap/hosts/terminal/input_session.py"
    ) == {"prompt_toolkit"}
    assert guard._exempt_modules(
        "src/questorharness/bootstrap/hosts/terminal_client.py"
    ) == {"prompt_toolkit"}
    assert guard._exempt_modules("src/questorharness/engine/query.py") == set()
    assert guard._exempt_modules(
        "src/questorharness/bootstrap/hosts/terminal_extra.py"
    ) == set()


def test_interactive_writes_go_through_one_patched_channel(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """plan03 §2.4：prompt 活跃时输出必须经 patch_stdout，否则与流式输出互相撕屏。"""

    import contextlib

    from prompt_toolkit import patch_stdout as patch_module

    from questorharness.bootstrap.hosts import terminal_client

    entered: list[bool] = []

    @contextlib.contextmanager
    def spy(*, raw: bool = False) -> Any:
        entered.append(raw)
        yield None

    monkeypatch.setattr(patch_module, "patch_stdout", spy)

    with terminal_client._output_channel(object()):
        pass
    assert entered == [True], "交互模式必须带 raw=True 进入 patch_stdout"

    assert isinstance(terminal_client._output_channel(None), contextlib.nullcontext)
    assert entered == [True], "非 TTY/单次 prompt 不得包裹（没有 prompt 在跑）"


def test_terminal_package_does_not_eagerly_import_prompt_toolkit() -> None:
    """包根不是输入层：全新解释器里冷导入不得把 prompt_toolkit 拉进 sys.modules。"""
    code = (
        "import sys; import questorharness.bootstrap.hosts.terminal as t; "
        "print('prompt_toolkit' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
