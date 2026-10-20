"""L1 checkpoint 写门（design/01 §5；R03 C-1）。

纯函数，用来决定"**什么才安全落库**"：durable 绝不能存半截 tool call，故只刷到
「每个 ``tool_use`` 都已配 ``tool_result``」的最长前缀。这是我按本项目不变式自写的
实现（非照搬任何参考代码）。"""

from __future__ import annotations

from collections.abc import Sequence

from questor.contracts.state_schema import ContentBlock, Message


def closed_prefix(messages: tuple[Message, ...]) -> int:
    """返回「其中每个 tool_use 都已被应答」的最长前缀长度。

    按序扫描、跟踪未闭合的 tool_use id 集合；每当前缀内集合空（全部闭合）就把 cut
    推进到该位置。尾部未应答的 tool_use 会被扣住、留到下一步再刷（调用方下一 turn 补）。
    """
    open_ids: set[str] = set()
    cut = 0
    for index, message in enumerate(messages):
        for block in message.content:
            _track(block, open_ids)
        if not open_ids:
            cut = index + 1
    return cut


def _track(block: ContentBlock, open_ids: set[str]) -> None:
    """更新未闭合集合：tool_use 入集，对应 tool_result 出集。"""
    if block.type == "tool_use" and block.tool_use_id:
        open_ids.add(block.tool_use_id)
    elif block.type == "tool_result" and block.tool_use_id:
        open_ids.discard(block.tool_use_id)


def tool_result_pairing(messages: Sequence[Message]) -> tuple[set[str], set[str]]:
    """返回 ``(被声明的 tool_use id 集合, 出现过的 tool_result id 集合)``（B10/§7.2）。

    为什么需要两个集合而不是一个：:func:`closed_prefix` 只回答“有没有 use 无 result”（**单向**），
    而压缩/seed 从**头部**切一刀时，真正致命的是反向：**一个没有 use 的 result**（头部孤儿）。
    两个集合交给调用方做双向判定，本函数不改任何现有语义（与 `_track` 互补不重复）。
    """
    used: set[str] = set()
    produced: set[str] = set()
    for message in messages:
        for block in message.content:
            if not block.tool_use_id:
                continue
            if block.type == "tool_use":
                used.add(block.tool_use_id)
            elif block.type == "tool_result":
                produced.add(block.tool_use_id)
    return used, produced


def orphan_tool_result_ids(messages: Sequence[Message]) -> tuple[str, ...]:
    """“未知 result id”的可观察计数（B10/§7.2 ④）：有 `tool_result` 但**从未被声明过** `tool_use`。

    `_track` 对这种 id 一直只 `discard` 不报错（它只需知道“无未闭合 use”），所以正向检查抓不到它。
    本函数把反向失真变成可观察量：截断/seed 后非空 = 造出了头部孤儿，必须拒（不静默）。
    """
    used, produced = tool_result_pairing(messages)
    return tuple(sorted(produced - used))


def open_tool_use_ids(messages: tuple[Message, ...]) -> tuple[str, ...]:
    """仍未应答的 tool_use id —— 存进 checkpoint 供恢复时回填/修复。"""
    open_ids: set[str] = set()
    for message in messages:
        for block in message.content:
            _track(block, open_ids)
    return tuple(sorted(open_ids))
