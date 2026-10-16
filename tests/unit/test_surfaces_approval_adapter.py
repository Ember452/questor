"""T18：surfaces/approval —— receipt→HTTP 映射 + TTY 审批 pump 生命周期。"""

from __future__ import annotations

import asyncio
import threading
import time

from questor.contracts.inbox import InboxReceipt, InboxStatus
from questor.surfaces import approval
from questor.surfaces.approval import http_status_for_receipt, prompt_approval


def test_http_status_for_every_receipt_state() -> None:
    assert http_status_for_receipt(InboxReceipt(True, InboxStatus.ACCEPTED)) == 202
    assert http_status_for_receipt(InboxReceipt(False, InboxStatus.DUPLICATE, reason="dup")) == 200
    assert http_status_for_receipt(InboxReceipt(False, InboxStatus.UNKNOWN_RUN, reason="gone")) == 404
    assert http_status_for_receipt(InboxReceipt(False, InboxStatus.REJECTED_TERMINAL, reason="terminal")) == 409
    assert http_status_for_receipt(InboxReceipt(False, InboxStatus.QUEUE_FULL, reason="full")) == 429


async def test_prompt_approval_non_tty_denies(monkeypatch) -> None:
    monkeypatch.setattr("questor.surfaces.approval._stdin_is_tty", lambda: False)
    assert await prompt_approval("a", "bash", "r", input_fn=lambda _p: "y") is False


async def test_prompt_approval_yes(monkeypatch) -> None:
    monkeypatch.setattr("questor.surfaces.approval._stdin_is_tty", lambda: True)
    assert await prompt_approval("a", "bash", "r", input_fn=lambda _p: "y") is True


async def test_prompt_approval_no_and_garbage_denies(monkeypatch) -> None:
    monkeypatch.setattr("questor.surfaces.approval._stdin_is_tty", lambda: True)
    assert await prompt_approval("a", "bash", "r", input_fn=lambda _p: "n") is False
    assert await prompt_approval("a", "bash", "r", input_fn=lambda _p: "maybe") is False


async def test_prompt_approval_timeout_denies_without_blocking(monkeypatch) -> None:
    monkeypatch.setattr("questor.surfaces.approval._stdin_is_tty", lambda: True)

    def slow(_prompt: str) -> str:
        time.sleep(0.5)
        return "y"

    started = time.monotonic()
    result = await prompt_approval("a", "bash", "r", timeout=0.05, input_fn=slow)
    elapsed = time.monotonic() - started
    assert result is False
    assert elapsed < 0.4  # 超时即返回，不等慢 reader（daemon 线程被丢弃）


async def test_prompt_approval_reader_error_denies(monkeypatch) -> None:
    monkeypatch.setattr("questor.surfaces.approval._stdin_is_tty", lambda: True)

    def boom(_prompt: str) -> str:
        raise EOFError

    assert await prompt_approval("a", "bash", "r", input_fn=boom) is False
    await asyncio.sleep(0)  # 让回调有机会运行，无残留断言


class _DeadLoop:
    """模拟已关闭的事件循环：`call_soon_threadsafe` 会报 `Event loop is closed`。"""

    def call_soon_threadsafe(self, *_args, **_kwargs) -> None:
        raise RuntimeError("Event loop is closed")


def test_safe_settle_swallows_closed_loop() -> None:
    """超时后迟到的按键不得从 reader 线程抛异常（Linux CI 曾报 PytestUnhandledThreadException）。"""
    approval._safe_settle(_DeadLoop(), object(), True)  # 不得抛出


def test_late_keystroke_after_loop_close_does_not_leak_thread_exception(monkeypatch) -> None:
    """端到端重现：timeout 返回 + loop 已关 + 线程随后送达 → 不能在线程里留未处理异常。"""
    monkeypatch.setattr(approval, "_stdin_is_tty", lambda: True)
    gate = threading.Event()

    def slow(_prompt: str) -> str:
        gate.wait(timeout=2)
        return "y"

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(prompt_approval("a", "bash", "r", timeout=0.01, input_fn=slow)) is False
    finally:
        loop.close()

    records: list[object] = []
    previous = threading.excepthook
    threading.excepthook = lambda args: records.append(args)
    try:
        gate.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            time.sleep(0.02)
            if records:
                break
    finally:
        threading.excepthook = previous

    assert records == []
