"""T18：surfaces/approval —— receipt→HTTP 映射 + TTY 审批 pump 生命周期。"""

from __future__ import annotations

import asyncio
import time

from questor.contracts.inbox import InboxReceipt, InboxStatus
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
