#!/usr/bin/env python3
"""Detect non-daemon thread leaks and install a fail-fast exit watchdog."""

from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import threading
import time
import traceback
from types import FrameType
from collections.abc import Sequence

try:
    from ._guard_kit import EXIT_OK, EXIT_RED, fail_on_empty, run_self_test
except ImportError:  # direct script execution
    from _guard_kit import EXIT_OK, EXIT_RED, fail_on_empty, run_self_test

GRACE_SECONDS = 2.0
POLL_SECONDS = 0.05
EXIT_WATCHDOG_SECONDS = 5.0
WATCHDOG_NAME = "thread-leak-exit-watchdog"


def non_daemon_threads() -> list[threading.Thread]:
    """Return live non-daemon threads; daemon threads cannot block interpreter exit."""
    return [thread for thread in threading.enumerate() if not thread.daemon and thread.is_alive()]


def snapshot() -> set[int | None]:
    """Return the current non-daemon thread identity baseline."""
    return {thread.ident for thread in non_daemon_threads()}


def stack_of(thread: threading.Thread) -> str:
    frame: FrameType | None = sys._current_frames().get(thread.ident)
    if frame is None:
        return "<thread has no stack>"
    return "".join(traceback.format_stack(frame))


def detect(before: set[int | None], *, grace_seconds: float = GRACE_SECONDS) -> list[threading.Thread]:
    """Return non-daemon threads that appeared after before and survived the grace period."""
    deadline = time.monotonic() + grace_seconds
    while True:
        leaked = [thread for thread in non_daemon_threads() if thread.ident not in before]
        if not leaked or time.monotonic() >= deadline:
            return leaked
        time.sleep(POLL_SECONDS)


def report(leaked: Sequence[threading.Thread]) -> str:
    parts = [
        f"leaked {len(leaked)} non-daemon thread(s); they can block interpreter exit "
        "and hang the CI step:"
    ]
    for thread in leaked:
        parts.append(f"\n--- thread {thread.name!r} ---\n{stack_of(thread)}")
    return "".join(parts)


def dump_stacks() -> None:
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


def arm_exit_watchdog(
    seconds: float = EXIT_WATCHDOG_SECONDS,
    *,
    exit_code: int = EXIT_RED,
) -> threading.Thread:
    """Force a non-zero exit if a leaked non-daemon thread blocks interpreter shutdown."""

    def fire() -> None:
        print(
            f"thread-leak guard: interpreter exit still blocked after {seconds:.0f}s; "
            f"forcing os._exit({exit_code}).",
            file=sys.stderr,
            flush=True,
        )
        dump_stacks()
        sys.stderr.flush()
        os._exit(exit_code)

    timer = threading.Timer(seconds, fire)
    timer.name = WATCHDOG_NAME
    timer.daemon = True
    timer.start()
    return timer


def _self_test() -> int:
    cases: list[tuple[str, bool, str]] = []
    stop = threading.Event()
    before = snapshot()

    def blocked() -> None:
        stop.wait()

    thief = threading.Thread(target=blocked, name="self-test-leak")
    thief.start()
    try:
        caught = [thread.name for thread in detect(before, grace_seconds=0.3)]
        cases.append(("detects-leak", thief.name in caught, f"caught={caught}"))
        stop.set()
        thief.join(timeout=2.0)
        clean = detect(before, grace_seconds=0.0)
        cases.append(("cleans-up", clean == [], f"leaked={[thread.name for thread in clean]}"))
    finally:
        stop.set()
        thief.join(timeout=2.0)

    watchdog = arm_exit_watchdog(30.0)
    cases.append(
        (
            "watchdog-is-daemon",
            watchdog.daemon and watchdog.name == WATCHDOG_NAME,
            f"name={watchdog.name} daemon={watchdog.daemon}",
        )
    )
    watchdog.cancel()

    return run_self_test(cases)


def _check(*, fail_on_empty_scan: bool) -> int:
    current = non_daemon_threads()
    if fail_on_empty_scan:
        try:
            fail_on_empty("non-daemon threads", current)
        except RuntimeError as exc:
            print(f"thread-leak guard: config error: {exc}", file=sys.stderr)
            return 2
    leaked = detect(snapshot(), grace_seconds=0.0)
    if leaked:
        print(report(leaked), file=sys.stderr)
        return EXIT_RED
    print("thread-leak guard: OK (no non-daemon thread leaks in this process)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the guard can go red and green")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat an empty thread baseline as a configuration error",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    return _check(fail_on_empty_scan=args.fail_on_empty)


if __name__ == "__main__":
    raise SystemExit(main())
