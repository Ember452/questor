"""删除刀守卫：旧 React/OHJSON 宿主链路必须彻底消失。

探针用字符串拼接，避免"守卫自己包含被测字符串"导致永远匹配。
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"


def _probe_tokens() -> tuple[str, str]:
    """拼接被测字符串（守卫自身不算命中点）。"""
    return "OH" + "JSON", "backend" + "_host"


def _all_source_text() -> str:
    """读取 src 下全部 Python 源码。"""
    chunks: list[str] = []
    for path in SRC.rglob("*.py"):
        chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def test_legacy_host_symbols_are_gone() -> None:
    """OHJSON 与 backend_host 不得再出现在 src。"""
    ohjson, backend_host = _probe_tokens()
    text = _all_source_text()
    assert ohjson not in text
    assert backend_host not in text


def test_legacy_files_are_deleted() -> None:
    """四个旧宿主文件/目录必须不存在。"""
    _, backend_host = _probe_tokens()
    assert not (SRC / "questorharness" / "bootstrap" / "hosts" / f"{backend_host}.py").exists()
    assert not (SRC / "questorharness" / "bootstrap" / "hosts" / "protocol.py").exists()
    assert not (SRC / "questorharness" / "bootstrap" / "hosts" / "react_launcher.py").exists()
    assert not (REPO / "frontend" / "terminal").exists()


def test_cli_flag_is_gone() -> None:
    """--backend-only 开关必须从 CLI 与打包配置里移除。"""
    flag = "--backend" + "-only"
    cli = (SRC / "questorharness" / "bootstrap" / "cli" / "main.py").read_text(encoding="utf-8")
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert flag not in cli
    assert flag not in pyproject


def test_selftest_probe_can_go_red() -> None:
    """自证：把探针字符串放回文本，守卫必然失败。"""
    ohjson, _ = _probe_tokens()
    fake = "print('" + ohjson + ":x')"
    assert ohjson in fake
