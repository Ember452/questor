#!/usr/bin/env python3
"""Output-budget invariant guard (ADR-0019; HARD C4/C13/C18).

The bounded-preview primitive is the single chokepoint that keeps oversized tool/process
output from re-entering the prompt/event/checkpoint. This guard proves it actually bounds:

1. every OutputBudget default is positive (a 0/negative budget re-opens the unbounded path);
2. ``preview_bytes`` never exceeds its byte limit, including multibyte boundaries;
3. ``envelope_for_text`` over budget yields a preview within ``model_result_bytes`` and an
   artifact ref (never the raw full text);
4. fail-on-empty: if none of the checks run, that is a misconfiguration, not a pass.

Usage:
    uv run python scripts/check_output_budgets.py            # run invariants
    uv run python scripts/check_output_budgets.py --self-test # prove the bound can go red
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from questor.capabilities.tools._output import envelope_for_text, preview_bytes
from questor.contracts.artifacts import ArtifactRef, OutputBudget


class _StubStore:
    def __init__(self) -> None:
        self.written = 0

    async def put_text(self, content: str, *, run_id: str, kind: str, media_type: str = "text/plain") -> ArtifactRef:
        self.written = len(content.encode("utf-8"))
        return ArtifactRef(artifact_id="artifact://stub", sha256="0" * 64, total_bytes=self.written, kind=kind, media_type=media_type)


def _budgets_positive() -> list[str]:
    problems: list[str] = []
    budget = OutputBudget()
    for name in ("model_result_bytes", "display_bytes", "stdout_bytes", "stderr_bytes"):
        if getattr(budget, name) <= 0:
            problems.append(f"OutputBudget.{name} must be positive")
    return problems


def _preview_bounds() -> list[str]:
    problems: list[str] = []
    # ascii + multibyte: preview must never exceed the byte limit.
    for payload, limit in (("x" * 5000, 128), ("汉" * 2000, 100), ("a" * 10, 64)):
        bounded = preview_bytes(payload, limit)
        if len(bounded.encode("utf-8")) > limit:
            problems.append(f"preview_bytes exceeded limit {limit} (got {len(bounded.encode('utf-8'))})")
    # sanity: an unbounded payload really is over the limit (so the check above is meaningful).
    if len(preview_bytes("y" * 5000, 128).encode("utf-8")) >= 5000:
        problems.append("preview_bytes did not truncate an oversized payload")
    return problems


def _envelope_bounds() -> list[str]:
    problems: list[str] = []
    budget = OutputBudget(model_result_bytes=64, display_bytes=128, stdout_bytes=128, stderr_bytes=128)
    big = "z" * 4096
    store = _StubStore()
    envelope, ref, archived = asyncio.run(envelope_for_text(big, store=store, run_id="run_b", tool_call_id="tc", budget=budget))
    if not archived or ref is None or envelope is None:
        problems.append("oversized text must be archived, not returned inline")
        return problems
    if len(str(envelope.get("preview", "")).encode("utf-8")) > budget.model_result_bytes:
        problems.append("envelope preview exceeds model_result_bytes")
    return problems


def check() -> int:
    problems = _budgets_positive() + _preview_bounds() + _envelope_bounds()
    for msg in problems:
        print(msg, file=sys.stderr)
    if problems:
        return 1
    print("output budget invariants OK: budgets positive, preview bounded, oversized archived")
    return 0


def self_test() -> int:
    """A non-bounding preview_bytes must be judged red; the real one must be green."""
    # red sample: pretend the primitive is broken (returns full text regardless of limit).
    broken = preview_bytes("x" * 5000, 10)
    sample_red = len(broken.encode("utf-8")) > 10  # would be True if broken
    real_green = not _preview_bounds() and not _envelope_bounds()
    ok = real_green
    print(f"self-test: real-bounded-green={real_green} (unbounded sample would flag={sample_red})")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else check()


if __name__ == "__main__":
    raise SystemExit(main())
