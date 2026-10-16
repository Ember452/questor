"""T15：文件工具共享的路径 containment helper（realpath/expandvars/normcase + 越界/错误拒绝）。"""

from __future__ import annotations

import os
from pathlib import Path

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


def test_symlink_escape_denied(tmp_path: Path) -> None:
    if os.name != "posix":
        # Windows 无符号权限时跳过 symlink 真建；用目录 junction 语义等价由 containment 覆盖。
        return
    secret = tmp_path.parent / "secret_target.txt"
    secret.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(secret)
    res = resolve_in_workspace("link.txt", root=tmp_path)
    assert not res.ok  # realpath 解析后指向 root 之外
