"""T15：文件工具共享的路径 containment helper（realpath/expandvars/normcase + 越界/错误拒绝）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from questor.capabilities.tools._paths import resolve_in_workspace


def test_relative_path_resolves_inside_root(tmp_path: Path) -> None:
    res = resolve_in_workspace("a/b.txt", root=tmp_path)
    assert res.ok
    assert res.path is not None
    assert res.path == (tmp_path / "a" / "b.txt")


def test_absolute_inside_root_allowed(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    res = resolve_in_workspace(str(target), root=tmp_path)
    assert res.ok
    assert res.path == target


def test_parent_traversal_outside_root_denied(tmp_path: Path) -> None:
    res = resolve_in_workspace("../../etc/passwd", root=tmp_path)
    assert not res.ok
    assert "escapes workspace root" in res.error


def test_absolute_outside_root_denied(tmp_path: Path) -> None:
    outside = Path(os.sep + "outside_dir_marker_xyz")
    res = resolve_in_workspace(str(outside), root=tmp_path)
    assert not res.ok


def test_expandvars_and_user_applied(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QROOT_SUB", "sub")
    res = resolve_in_workspace("$QROOT_SUB/f.txt", root=tmp_path)
    assert res.ok
    assert res.path.parts[-2:] == ("sub", "f.txt")


def test_existing_required_missing_denied(tmp_path: Path) -> None:
    res = resolve_in_workspace("nope.txt", root=tmp_path, must_exist=True)
    assert not res.ok
    assert res.error in ("path does not exist",)


def _make_escape_link(root: Path, outside_dir: Path) -> tuple[str, str | None]:
    """在 root 内造一条通往 root 外的链，返回（待解析的相对路径, 跳过原因）。

    Windows 用 junction（`mklink /J` 只接受**目录**目标，不需要开发者模式/管理员权限），
    POSIX 用 symlink。造不出来时把原因返回给测试去 skip，而不是静默 return——
    静默 return 等于该用例从未存在（审计就是这样标为 UNVERIFIED-on-Windows 的）。
    """
    if os.name == "nt":
        import subprocess

        link = root / "linkdir"
        # 不用 text=True：cmd/mklink 的输出走 OEM 代码页（zh-CN=cp936），UTF-8 模式下会解码崩。
        # 取字节；仅在失败分支需人读 detail 时才带 errors="replace" 解码（成功分支不解码）。
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside_dir)], capture_output=True)
        if result.returncode != 0 or not link.is_dir():
            detail = ((result.stdout or b"") + (result.stderr or b"")).decode("utf-8", errors="replace")
            return "", f"Windows 无法创建 junction：{detail.strip()[:160]}"
        return "linkdir/secret.txt", None
    link = root / "link.txt"
    try:
        link.symlink_to(outside_dir / "secret.txt")
    except OSError as exc:  # pragma: no cover - CI 上通常可用
        return "", f"无法创建 symlink：{exc}"
    return "link.txt", None


def test_symlink_or_junction_escape_denied(tmp_path: Path) -> None:
    """containment 必须看 realpath：经链走到 root 外就不得放行（两平台都真建链验证）。"""
    outside = tmp_path.parent / "outside_dir_for_escape"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("x", encoding="utf-8")

    rel, skip_reason = _make_escape_link(tmp_path, outside)
    if skip_reason:
        pytest.skip(skip_reason)
    res = resolve_in_workspace(rel, root=tmp_path)
    assert not res.ok, f"链解析后仍在 root 内？res={res}"
    assert "escapes workspace root" in res.error
