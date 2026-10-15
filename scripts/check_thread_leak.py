#!/usr/bin/env python3
"""线程泄漏守卫：把"测试跑完但进程退不出"变成一条能判红的测试（C15 同类口径）。

为什么要它：``aiosqlite`` 这类库的连接工作线程是**非守护**线程，只有显式 ``close()``
才会给它投递退出哨兵。忘记 close 时线程永久阻塞在 ``queue.get()`` 上；而 CPython 终结化
是先 ``threading._shutdown()`` join 所有非守护线程、**再**跑 atexit —— 于是 pytest 已经打印完
"64 passed"，进程却永不退出，GitHub Actions 的 pytest step 会一路挂到默认 6 小时超时
（本仓 P1 期间 CI 全红的最初根因，也是参考集 hermes ``cli_shutdown.py`` 记为 #27563 的同一类故障：
stdlib ``ThreadPoolExecutor`` 的 worker 同样被 atexit 无条件 join）。

关键事实（都实测过，别踩）：
* 已启动线程的 ``daemon`` 标志**改不了**（``RuntimeError: cannot set daemon status of active
  thread``），所以"事后把泄漏线程标成守护"这条路不存在。
* 唯一能保证进程退出的手段是**守护定时器 + ``os._exit``**：守护线程不会参与终结时的 join，
  因此能活过那次 join 并强制结束进程。这只在"已检出泄漏"时上弹、以非零码硬退，不可能洗白失败。

用法（被 tests/conftest.py 的 autouse fixture 与 sessionfinish 钩子调用；也可单独自检）：
    uv run python scripts/check_thread_leak.py --self-test
"""

from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import threading
import time
import traceback
from types import FrameType

#: 判红前的宽限上限：正在退出的线程（刚 close() 完的 worker）应当在这几毫秒内消失，
#: 只有宽限期后仍存活的才算真泄漏。轮询条件而非固定 sleep。
GRACE_SECONDS = 2.0
POLL_SECONDS = 0.05

#: 退出看门狗延时：先给正常收尾这么多秒，还卡在 join 上才硬退。
EXIT_WATCHDOG_SECONDS = 5.0
WATCHDOG_NAME = "thread-leak-exit-watchdog"


def non_daemon_threads() -> list[threading.Thread]:
    """当前仍存活的非守护线程（守护线程不会阻塞解释器退出，故不计）。"""
    return [t for t in threading.enumerate() if not t.daemon and t.is_alive()]


def snapshot() -> set[int | None]:
    """基线：调用时刻已存活的非守护线程 ident 集合。"""
    return {t.ident for t in non_daemon_threads()}


def stack_of(thread: threading.Thread) -> str:
    """取线程此刻的栈（定位是谁创建了没释放的线程）。"""
    frame: FrameType | None = sys._current_frames().get(thread.ident)
    if frame is None:
        return "<线程已无栈帧>"
    return "".join(traceback.format_stack(frame))


def detect(before: set[int | None], *, grace_seconds: float = GRACE_SECONDS) -> list[threading.Thread]:
    """返回 ``before`` 之后新增、且宽限期后仍存活的非守护线程。空列表 = 干净。"""
    deadline = time.monotonic() + grace_seconds
    while True:
        leaked = [t for t in non_daemon_threads() if t.ident not in before]
        if not leaked or time.monotonic() >= deadline:
            return leaked
        time.sleep(POLL_SECONDS)


def report(leaked: list[threading.Thread]) -> str:
    """把泄漏线程拼成人可读的一段（含线程名与创建/阻塞栈）。"""
    parts = [
        f"leaked {len(leaked)} non-daemon thread(s); they will block interpreter exit "
        "(threading._shutdown) and hang the CI step:"
    ]
    for t in leaked:
        parts.append(f"\n--- thread {t.name!r} ---\n{stack_of(t)}")
    return "".join(parts)


def dump_stacks() -> None:
    """把所有线程的栈打到 stderr（借 EvoFlow ``hang_diagnostics`` 的做法）。"""
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


def arm_exit_watchdog(seconds: float = EXIT_WATCHDOG_SECONDS, *, exit_code: int = 1) -> threading.Thread:
    """装一个**守护**退出看门狗：``seconds`` 后仍未退出就 ``os._exit(exit_code)``。

    为什么必须它：解释器终结会 join 非守护线程，一个永久阻塞的 worker 就能把进程扣住；
    只有守护定时器能越过那次 join。延后几秒是给正常收尾的机会（泄漏线程可能正在退出），
    非零码保证 CI 判红而不是假绿。
    """

    def _fire() -> None:
        print(
            f"thread-leak guard: interpreter exit still blocked after {seconds:.0f}s; "
            f"forcing os._exit({exit_code}) so CI fails fast instead of hanging until timeout-minutes.",
            file=sys.stderr,
            flush=True,
        )
        dump_stacks()
        sys.stderr.flush()
        os._exit(exit_code)

    timer = threading.Timer(seconds, _fire)
    timer.name = WATCHDOG_NAME
    timer.daemon = True  # 必须在 start 前设置：start 之后改不了
    timer.start()
    return timer


def self_test() -> int:
    """证明守卫三件事都成立：能检出真泄漏、释放后判绿、看门狗是守护线程且真能上弹。"""
    stop = threading.Event()
    before = snapshot()

    def _blocked() -> None:
        stop.wait()  # 永不自行退出，模拟未 close() 的 worker 线程

    thief = threading.Thread(target=_blocked, name="self-test-leak")
    thief.start()
    caught = [t.name for t in detect(before, grace_seconds=0.3)]
    goes_red = thief.name in caught

    stop.set()
    thief.join(timeout=2.0)
    goes_green = detect(before, grace_seconds=0.0) == []

    # 看门狗判据：必须是守护线程（否则自己就会变成新的退出阻塞），且能被 cancel 掉。
    # 延时要给足，避免自检进程被它真硬退；cancel() 后立即校验属性。
    watchdog = arm_exit_watchdog(30.0)
    watchdog_is_daemon = watchdog.daemon and watchdog.name == WATCHDOG_NAME
    watchdog.cancel()

    print(
        f"self-test: bad-leak flagged={goes_red} clean-passed={goes_green} "
        f"watchdog-is-daemon={watchdog_is_daemon}"
    )
    if not (goes_red and goes_green and watchdog_is_daemon):
        print("self-test: FAIL (guard is untrustworthy)", file=sys.stderr)
        return 1
    print("self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the guard can go red and green")
    args = parser.parse_args()
    return self_test() if args.self_test else _check_baseline()


def _check_baseline() -> int:
    """独立运行时的实义检查：本进程结束时不得残留非基线的非守护线程。

    没有测试跑过时没什么可检的，所以 CI 的真用点是 ``--self-test``（证明守卫可信），
    加上 conftest 里的 autouse fixture（逐测试判泄漏）与 sessionfinish 看门狗（保证能退出）。
    """
    leaked = detect(snapshot(), grace_seconds=0.0)
    if leaked:
        print(report(leaked), file=sys.stderr)
        return 1
    print("thread-leak guard: OK (no non-daemon thread leaks in this process)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
