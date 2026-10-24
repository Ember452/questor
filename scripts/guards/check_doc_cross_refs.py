#!/usr/bin/env python3
"""Check relative documentation links and repository paths referenced in docs."""

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
        ]
    return run_self_test(cases)


def _scan(docs: Path, *, fail_on_empty_scan: bool) -> int:
    if not docs.exists():
        print(f"doc-cross-refs guard: docs directory missing: {docs}", file=sys.stderr)
        return EXIT_CONFIG
    files = _markdown_files(docs)
    if fail_on_empty_scan:
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
        violations.extend(check_doc(doc, root=ROOT))
    if fail_on_empty_scan and references == 0:
        print("doc-cross-refs guard: config error: no documentation references found", file=sys.stderr)
        return EXIT_CONFIG

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
    return _scan(args.docs, fail_on_empty_scan=args.fail_on_empty)


if __name__ == "__main__":
    raise SystemExit(main())
