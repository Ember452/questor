"""CI 变更分类器：把 merge-base diff 归类为 web / python / desktop 三布尔。

设计对齐仓外参照（DeepCode `ci-scope` / Reasonix `changes` job）并保留它们的
安全性质：

- **fail-open**：任何无法确定的情况（非 PR/push、缺 SHA、git 报错、diff 为空
  但 head 不存在等）一律输出全 true——宁可多跑，绝不漏跑；
- 只被 `ci.yml` 的 `scope` job 消费；required check（ci-ok）依赖的 job 用
  步骤级 `if` 跳过而不是 workflow 级 paths，避免 required check 卡 pending。

规则（纯函数 `classify`，单测在 tests/ci/test_scope.py）：

- python：src/ tests/ scripts/（Python 侧）
- web：apps/web/
- desktop：apps/desktop/ apps/web/ serve 宿主 契约 codegen
- 全 True（横切）：workflow 自身、check.py、本脚本、pyproject、uv.lock、
  protocol/（契约变两侧都要跑）、scripts/codegen/
"""

from __future__ import annotations

import argparse
import subprocess
import sys

_ALL = ("web", "python", "desktop")

# 横切面：这些路径变化时三面全跑（改门禁自己却按旧规则跳过是最经典的漏跑）。
_FORCE_ALL: tuple[str, ...] = (
    ".github/workflows/",
    "scripts/check.py",
    "scripts/ci/scope.py",
    "pyproject.toml",
    "uv.lock",
    "protocol/",
    "scripts/codegen/",
)

_PYTHON: tuple[str, ...] = ("src/", "tests/", "scripts/")
_WEB: tuple[str, ...] = ("apps/web/",)
_DESKTOP: tuple[str, ...] = (
    "apps/desktop/",
    "apps/web/",
    "src/questorharness/bootstrap/hosts/serve/",
    "protocol/",
    "scripts/codegen/",
)


def _hit(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in prefixes)


def classify(paths: list[str]) -> set[str]:
    """把变更路径集合归类为需要跑的面（空集 = 三面都可跳过）。"""
    faces: set[str] = set()
    for path in paths:
        if _hit(path, _FORCE_ALL):
            return set(_ALL)
        if _hit(path, _PYTHON):
            faces.add("python")
        if _hit(path, _WEB):
            faces.add("web")
        if _hit(path, _DESKTOP):
            faces.add("desktop")
    return faces


def _changed_paths(base: str, head: str, cwd: str | None = None) -> list[str]:
    """base..head 的变更路径；任何 git 失败都抛错（由调用方 fail-open）。"""
    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", base, head],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _self_test() -> None:
    """守卫文化：证明分类规则仍能判出三类与横切。"""
    assert classify(["src/a.py"]) == {"python"}
    assert classify(["apps/web/x.ts"]) == {"web", "desktop"}
    assert classify(["apps/desktop/main.cjs"]) == {"desktop"}
    assert classify(["docs/x.md", "README.md"]) == set()
    assert classify(["pyproject.toml"]) == set(_ALL)
    assert classify([".github/workflows/ci.yml"]) == set(_ALL)
    print("scope self-test: ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="diff 基准（建议传 merge-base）")
    parser.add_argument("--head", default="HEAD", help="diff 终点，默认 HEAD")
    parser.add_argument("--output", default="-", help="GITHUB_OUTPUT 文件，默认 stdout")
    parser.add_argument("--self-test", action="store_true", help="跑规则自证")
    args = parser.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0

    # fail-open：任何不确定 → 全跑。
    faces: set[str] = set(_ALL)
    if not args.base:
        print("scope: no base sha given -> run all", file=sys.stderr)
    else:
        try:
            paths = _changed_paths(args.base, args.head)
            faces = classify(paths)
        except (RuntimeError, OSError) as error:
            print(f"scope: {error} -> run all", file=sys.stderr)

    lines = [f"{name}={'true' if name in faces else 'false'}" for name in _ALL]
    payload = "\n".join(lines) + "\n"
    if args.output == "-":
        sys.stdout.write(payload)
    else:
        with open(args.output, "a", encoding="utf-8") as handle:
            handle.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
