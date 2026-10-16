"""L6 审批/入队结果适配（design/02 §4/§10；ADR-0013/0016；HARD S6 零业务）。

本模块只放两条纯适配：
- 把 :class:`InboxReceipt` 映射成 HTTP 状态码（surface 不碰 reduce，只据 receipt 说话）；
- 一个 TTY 审批 prompt，保证*唯一*生命周期：超时/取消后 reader 线程必然退出，绝不留下
  非守护线程（本项目历史 CI 挂死根因）。
"""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Callable

from questor.contracts.inbox import InboxReceipt, InboxStatus

#: 审批 y/n 之外的输入一律按拒绝（fail-closed）。
_ACCEPT = {"y", "yes"}


def http_status_for_receipt(receipt: InboxReceipt) -> int:
    """把 Command Inbox receipt 映射成 HTTP 状态码（S6：surface 只做映射，不改状态）。"""
    return {
        InboxStatus.ACCEPTED: 202,  # 已入队，异步生效
        InboxStatus.DUPLICATE: 200,  # 幂等重复 = 无操作但成功
        InboxStatus.UNKNOWN_RUN: 404,  # run 不在活跃注册表
        InboxStatus.REJECTED_TERMINAL: 409,  # 迟到审批：run 已终态
        InboxStatus.QUEUE_FULL: 429,  # 背压：队满
    }[receipt.status]


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (ValueError, OSError):  # 被关闭/不可用的 stdin：按非交互处理（deny）
        return False


async def prompt_approval(args_summary: str, name: str, reason: str, *, timeout: float | None = None, input_fn: Callable[[str], str] | None = None) -> bool:
    """在有 TTY 时把一次审批解析成人决策；非交互/超时/任何异常都返回 ``False``（fail-closed）。

    用 daemon 线程读 stdin：超时后本协程立刻返回，reader 线程随解释器退出而丢弃，不会残留
    一个阻塞退出的非守护线程。``input_fn`` 仅供测试注入；默认走内置 ``input``。
    """
    if not _stdin_is_tty():
        return False

    read = input_fn or (lambda prompt: input(prompt))  # noqa: A005
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()

    def worker() -> None:
        try:
            answer = read(f"[approval] {name}({args_summary}) — {reason}\nallow? [y/n]: ")
            value = answer.strip().lower() in _ACCEPT
        except BaseException:  # noqa: BLE001 - 读 stdin 失败一律视为拒绝
            value = False
        _safe_settle(loop, future, value)

    threading.Thread(target=worker, daemon=True).start()
    if timeout is None:
        return await future
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        return False  # 超时不复活：迟到的按键会被丢弃（daemon 线程），决策已定为 deny


def _safe_settle(loop: asyncio.AbstractEventLoop, future: asyncio.Future[bool], value: bool) -> None:
    """把 reader 线程的结果送回事件循环；**循环已关闭则静默丢弃**。

    超时/取消后本协程已返回，事件循环可能随后关掉。此时迟到的按键不得从 daemon
    线程里抛出未处理异常（会污染进程、并在 pytest 下报 PytestUnhandledThreadException）；
    丢弃它正是“超时即 deny”的设计本身。
    """
    try:
        loop.call_soon_threadsafe(_settle, future, value)
    except RuntimeError:
        return  # loop closed / 已取消：迟到的决策丢弃，fail-closed 已生效


def _settle(future: asyncio.Future[bool], value: bool) -> None:
    if not future.done():
        future.set_result(value)


__all__ = ["http_status_for_receipt", "prompt_approval"]
