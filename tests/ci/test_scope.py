"""scope 分类器单测：三类命中、横切全跑、纯 docs 全跳、fail-open。"""

from __future__ import annotations

import subprocess

from scripts.ci.scope import _ALL, _changed_paths, classify, main


def test_classify_faces() -> None:
    """单类命中；web 命中同时带出 desktop（desktop 消费 web dist）。"""
    assert classify(["src/questorharness/x.py"]) == {"python"}
    assert classify(["tests/unit/x.py"]) == {"python"}
    assert classify(["apps/web/src/App.tsx"]) == {"web", "desktop"}
    assert classify(["apps/desktop/electron/main.cjs"]) == {"desktop"}
    assert classify(["src/questorharness/bootstrap/hosts/serve/routes.py"]) == {
        "python",
        "desktop",
    }


def test_classify_cross_cutting_forces_all() -> None:
    """门禁/依赖/契约自变时三面全跑；纯文档改动三面全跳。"""
    for path in ("pyproject.toml", "uv.lock", "protocol/app-wire.schema.json",
                 "scripts/codegen/gen_wire_ts.mjs", ".github/workflows/ci.yml",
                 "scripts/check.py"):
        assert classify([path]) == set(_ALL), path
    assert classify(["docs/x.md", "README.md", "AGENTS.md"]) == set()


def test_fail_open_on_git_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """git 失败必须退化为全跑（fail-open），绝不能产出全 false。"""

    def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args, returncode=128, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", broken)
    try:
        _changed_paths("deadbeef", "HEAD")
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    # main 层：--base 给出但 git 失败 → 输出全 true。
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(["--base", "deadbeef", "--head", "HEAD"])
    assert code == 0
    assert "web=true" in buffer.getvalue()
    assert "python=true" in buffer.getvalue()
    assert "desktop=true" in buffer.getvalue()


def test_missing_base_runs_all() -> None:
    """无 --base（非 PR 语义）→ 全跑。"""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main([]) == 0
    assert "desktop=true" in buffer.getvalue()


def test_self_test_passes() -> None:
    """--self-test 可独立判绿（check.py 守卫文化）。"""
    assert main(["--self-test"]) == 0


def test_all_faces_covered() -> None:
    """三布尔词表被锁定（改名即红）。"""
    assert _ALL == ("web", "python", "desktop")
