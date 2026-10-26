#!/usr/bin/env python3
"""Check documentation cross references: dead links and unreachable pages."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

try:
    from ._guard_kit import (
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        GuardConfigError,
        fail_on_empty,
        read_text,
        run_self_test,
    )
except ImportError:  # direct script execution
    from _guard_kit import (
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        GuardConfigError,
        fail_on_empty,
        read_text,
        run_self_test,
    )

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCS = ROOT / "docs"
# 读者入口：docs 目录下每个 md 都必须能从它沿链接走到。
INDEX_NAME = "README.md"
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
CODE_PATH_RE = re.compile(r"`([^`\n]+)`")
PATH_ROOTS = ("src/", "tests/", "scripts/", "docs/", "frontend/", ".github/")
SIMPLE_PATHS = (
    "pyproject.toml",
    "uv.lock",
    ".importlinter",
    ".pre-commit-config.yaml",
    "Makefile",
    "README.md",
)

# 根目录下的活文档：必须一并扫描，否则 README / 贡献指南里的死链会一路绿灯。
# 用显式白名单而不是扫整个仓库根：`apps/*/node_modules` 与 `.venv` 里
# 躺着上千个第三方 README，卷进来只会制造噪音与极慢的扫描。
ROOT_DOC_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "AGENTS.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "CLAUDE.md",
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str


def _markdown_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if "docs-pre-reset-v1" not in path.parts)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _check_target(doc: Path, raw_target: str, *, root: Path) -> str | None:
    target = raw_target.strip().strip("<>").split()[0] if raw_target.strip() else ""
    if not target or target.startswith(("#", "http://", "https://", "mailto:", "tel:", "data:")):
        return None
    path_part = unquote(target.split("#", 1)[0])
    if not path_part:
        return None
    candidate = Path(path_part)
    if candidate.is_absolute():
        return None
    resolved = (doc.parent / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return f"link escapes repository: {target}"
    if not resolved.exists():
        return f"missing link target: {target}"
    return None


def _check_code_paths(doc: Path, text: str, *, root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for match in CODE_PATH_RE.finditer(text):
        token = match.group(1).strip()
        if not token or any(char in token for char in ("*", "<", ">", " ", "~", ":")):
            continue
        if not (token.startswith(PATH_ROOTS) or token in SIMPLE_PATHS):
            continue
        if not (root / token).exists():
            violations.append(Violation(doc, _line_of(text, match.start()), f"missing code path: {token}"))
    return violations


STALE_REFS_RE = re.compile(r"<!--\s*known-stale-refs:\s*([^>]+?)\s*-->")
HEADER_LINES = 30


def _normalize_ref(token: str) -> str:
    return token.strip().lstrip("./")


def _stale_allowance(text: str) -> set[str]:
    """Read a declared stale-reference list, but only from the file header.

    A document may describe this mechanism anywhere in its body; quoting the
    literal marker there must not turn the description into an opt-in.
    """

    header = "\n".join(text.splitlines()[:HEADER_LINES])
    match = STALE_REFS_RE.search(header)
    if not match:
        return set()
    return {_normalize_ref(item) for item in match.group(1).split(",") if item.strip()}


def check_doc(doc: Path, *, root: Path) -> list[Violation]:
    """Report dead references, minus the ones this document declared stale.

    The allowance is a ratchet, not a blanket skip: an entry that no longer
    matches any failing reference is itself reported, so fixing a link must
    shrink the list in the same change.
    """

    text = read_text(doc)
    allowance = _stale_allowance(text)
    used: set[str] = set()
    violations: list[Violation] = []
    for match in LINK_RE.finditer(text):
        problem = _check_target(doc, match.group(1), root=root)
        if problem:
            violation = Violation(doc, _line_of(text, match.start()), problem)
            token = _normalize_ref(problem.rsplit(": ", 1)[-1])
            if token in allowance:
                used.add(token)
            else:
                violations.append(violation)
    for violation in _check_code_paths(doc, text, root=root):
        token = _normalize_ref(violation.message.rsplit(": ", 1)[-1])
        if token in allowance:
            used.add(token)
        else:
            violations.append(violation)
    unused = sorted(allowance - used)
    for token in unused:
        violations.append(
            Violation(
                doc,
                1,
                f"known-stale-refs entry '{token}' no longer matches a dead reference; delete it",
            )
        )
    return violations


def _self_test() -> int:
    import contextlib
    import io
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        docs = root / "docs"
        docs.mkdir()
        (docs / "target.md").write_text("# target\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "pkg").mkdir()
        (root / "src" / "pkg" / "module.py").write_text("", encoding="utf-8")
        valid = docs / "valid.md"
        valid.write_text(
            "[target](target.md)\n\n`src/pkg/module.py`\n",
            encoding="utf-8",
        )
        broken = docs / "broken.md"
        broken.write_text(
            "[target](missing.md)\n\n`src/pkg/missing.py`\n",
            encoding="utf-8",
        )
        declared = docs / "declared.md"
        declared.write_text(
            "<!-- known-stale-refs: missing.md, src/pkg/missing.py -->\n\n"
            "[target](missing.md)\n\n`src/pkg/missing.py`\n",
            encoding="utf-8",
        )
        stale = docs / "stale-allowance.md"
        stale.write_text(
            "<!-- known-stale-refs: src/pkg/fixed.py -->\n\n`src/pkg/module.py`\n",
            encoding="utf-8",
        )
        described = docs / "described.md"
        described.write_text(
            "# prose\n\n"
            + "\n".join(f"padding line {index}" for index in range(HEADER_LINES))
            + "\n\na document may quote `<!-- known-stale-refs: dead.md -->` as text\n\n"
            "[dead](missing2.md)\n",
            encoding="utf-8",
        )
        valid_hits = check_doc(valid, root=root)
        broken_hits = check_doc(broken, root=root)
        declared_hits = check_doc(declared, root=root)
        stale_hits = check_doc(stale, root=root)
        described_hits = check_doc(described, root=root)

        # 根目录文档白名单必须真的生效：README 里的死链要能让整次扫描判红，
        # 而未列入白名单的根文件不应被卷进来。
        def _quiet_scan(docs_dir: Path, scan_root: Path) -> int:
            captured_out = io.StringIO()
            captured_err = io.StringIO()
            with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
                return _scan(docs_dir, root=scan_root, fail_on_empty_scan=False)

        with tempfile.TemporaryDirectory() as tmp2:
            root2 = Path(tmp2)
            docs2 = root2 / "docs"
            docs2.mkdir()
            (docs2 / "ok.md").write_text("# ok\n", encoding="utf-8")
            (docs2 / "README.md").write_text("# index\n\n[ok](ok.md)\n", encoding="utf-8")
            (root2 / "README.md").write_text("[bad](missing-root.md)\n", encoding="utf-8")
            root_doc_red = _quiet_scan(docs2, root2)
            (root2 / "README.md").write_text("# clean\n", encoding="utf-8")
            root_doc_green = _quiet_scan(docs2, root2)
            (root2 / "notes.md").write_text("[bad](missing-notes.md)\n", encoding="utf-8")
            non_allowlisted = _quiet_scan(docs2, root2)

        # 可达性：写了但没人链的页必须判红；全部链上后必须判绿。
        with tempfile.TemporaryDirectory() as tmp3:
            root3 = Path(tmp3)
            docs3 = root3 / "docs"
            docs3.mkdir()
            (docs3 / "leaf.md").write_text("# leaf\n", encoding="utf-8")
            (docs3 / "orphan.md").write_text("# orphan\n", encoding="utf-8")
            (docs3 / "README.md").write_text("# index\n\n[leaf](leaf.md)\n", encoding="utf-8")
            orphan_red = _quiet_scan(docs3, root3)
            (docs3 / "README.md").write_text(
                "# index\n\n[leaf](leaf.md) [orphan](orphan.md)\n", encoding="utf-8"
            )
            no_orphan_green = _quiet_scan(docs3, root3)

        cases = [
            (
                "marker-in-body-is-not-an-opt-in",
                any("missing2.md" in item.message for item in described_hits),
                f"{[item.message for item in described_hits]}",
            ),
            ("declared-stale-allowed", declared_hits == [], f"{[item.message for item in declared_hits]}"),
            (
                "allowance-shrinks-when-fixed",
                any("no longer matches" in item.message for item in stale_hits),
                f"{[item.message for item in stale_hits]}",
            ),
            ("valid-doc", not valid_hits, f"{len(valid_hits)} violations"),
            (
                "missing-link",
                any("missing link target" in item.message for item in broken_hits),
                f"{len(broken_hits)} violations",
            ),
            (
                "missing-code-path",
                any("missing code path" in item.message for item in broken_hits),
                f"{len(broken_hits)} violations",
            ),
            (
                "root-doc-dead-link-goes-red",
                root_doc_red == EXIT_RED,
                f"exit={root_doc_red}",
            ),
            (
                "root-doc-clean-is-green",
                root_doc_green == EXIT_OK,
                f"exit={root_doc_green}",
            ),
            (
                "non-allowlisted-root-file-not-scanned",
                non_allowlisted == EXIT_OK,
                f"exit={non_allowlisted}",
            ),
            (
                "unreachable-doc-goes-red",
                orphan_red == EXIT_RED,
                f"exit={orphan_red}",
            ),
            (
                "all-docs-reachable-is-green",
                no_orphan_green == EXIT_OK,
                f"exit={no_orphan_green}",
            ),
        ]
    return run_self_test(cases)


def _outbound_targets(doc: Path, universe: set[Path]) -> set[Path]:
    """Return the in-scope documents that one page links to."""

    out: set[Path] = set()
    for match in LINK_RE.finditer(read_text(doc)):
        target = match.group(1).strip().strip("<>")
        if not target:
            continue
        raw = target.split()[0]
        if raw.startswith(("#", "http://", "https://", "mailto:", "tel:", "data:")):
            continue
        path_part = unquote(raw.split("#", 1)[0])
        if not path_part:
            continue
        candidate = (doc.parent / path_part).resolve()
        if candidate in universe:
            out.add(candidate)
    return out


def _unreachable_docs(docs: Path, files: list[Path]) -> list[Path]:
    """Documents a reader can never arrive at, measured from the docs index.

    Reachability is transitive: index -> section page -> leaf page. A page nobody
    links is invisible no matter how correct its content is, so a missing index
    entry is a documentation defect rather than a style nit.
    """

    index = (docs / INDEX_NAME).resolve()
    universe = {path.resolve() for path in files}
    if index not in universe:
        return []
    seen = {index}
    stack = [index]
    while stack:
        for target in _outbound_targets(stack.pop(), universe):
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return sorted(path for path in universe if path not in seen)


def _scan(docs: Path, *, root: Path = ROOT, fail_on_empty_scan: bool) -> int:
    if not docs.exists():
        print(f"doc-cross-refs guard: docs directory missing: {docs}", file=sys.stderr)
        return EXIT_CONFIG
    doc_files = _markdown_files(docs)
    files = list(doc_files)
    files.extend(root / name for name in ROOT_DOC_FILES if (root / name).exists())
    files.sort()
    if fail_on_empty_scan:
        if not (docs / INDEX_NAME).exists():
            print(
                f"doc-cross-refs guard: config error: reader index {docs / INDEX_NAME} is missing",
                file=sys.stderr,
            )
            return EXIT_CONFIG
        try:
            fail_on_empty("markdown files", files)
        except GuardConfigError as exc:
            print(f"doc-cross-refs guard: config error: {exc}", file=sys.stderr)
            return EXIT_CONFIG

    violations: list[Violation] = []
    references = 0
    for doc in files:
        text = read_text(doc)
        references += len(LINK_RE.findall(text)) + len(CODE_PATH_RE.findall(text))
        violations.extend(check_doc(doc, root=root))
    if fail_on_empty_scan and references == 0:
        print("doc-cross-refs guard: config error: no documentation references found", file=sys.stderr)
        return EXIT_CONFIG

    for orphan in _unreachable_docs(docs, doc_files):
        violations.append(
            Violation(
                orphan,
                1,
                "document is unreachable from the docs index; link it from an index page",
            )
        )

    for item in violations:
        print(f"{item.path}:{item.line}: {item.message}", file=sys.stderr)
    if violations:
        return EXIT_RED
    print(f"doc-cross-refs guard: OK ({len(files)} markdown files, {references} references)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the guard can go red and green")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat an empty docs set or no references as a configuration error",
    )
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS, help="documentation root")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    return _scan(args.docs, root=ROOT, fail_on_empty_scan=args.fail_on_empty)


if __name__ == "__main__":
    raise SystemExit(main())
