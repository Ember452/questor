"""L1 持久化形态的唯一判定点（v3 §4.1 咽喉；ADR-0005/0020/0022；HARD C5/C13/I3）。

「什么进事实流、以什么形态进」只在这里决定，``kernel/events.py`` 只调用本模块：

- **live-only**（delta / progress / heartbeat / usage / tools_changed）→ ``None``：
  只转发给订阅者，永不落 ``event_log``（design/01 I3）；
- **终态**（run_completed / run_cancelled / run_failed）→ 由调用方做 first-writer-wins，
  一轮至多一个终态（C13）；本模块只提供 :func:`is_terminal` 这一处判断；
- **其余 durable** → 原样返回；调用方配了 :class:`OutputBudget` 时，字符串叶子按
  ``model_result_bytes`` 截断并带标记（B0 无人传 budget = 逐字节等价，有界形态留给后续刀）。
- **``user_message`` 正文**（B1）→ 落库前剥掉带内标记的注入脚手架段（只留「用户原话」，
  标记绝不进持久正文）；无标记时逐字节等价。

层次：state(L1) 只依赖 contracts(L0)；kernel(L2) 反向 import 本模块，故 LIVE_ONLY / TERMINAL
不再散落在 kernel 内部（状态形态的判断从 kernel 下沉到 state）。``EventType`` 取值域仍是 L0 契约，
本模块**不新增、不改名**任何事件类型（那是 P4 的范围）。
"""

from __future__ import annotations

from dataclasses import replace

from questor.contracts.artifacts import OutputBudget
from questor.contracts.events import Envelope, EventType

#: live-only 事件：只转发给订阅者、永不持久化（design/01 I3）。
LIVE_ONLY: frozenset[str] = frozenset(
    {
        EventType.TEXT_DELTA,
        EventType.REASONING_DELTA,
        EventType.TOOL_PROGRESS,
        EventType.HEARTBEAT,
        EventType.USAGE_DELTA,
        EventType.TOOLS_CHANGED,
        # B7：记忆注入与 cache 断裂都是“本轮请求的观察结果”，不是发生记录——正文/hash 不可逆，
        # 但它们的量级与频次也不该挤占事实流，故永不入库（§6.1 第④条只要求可观测，不要求可回放）。
        EventType.MEMORY_INJECTED,
        EventType.CACHE_BREAK,
    }
)

#: 终态事件：一轮至多一个（C13）；持久化顺序上先于 run_completed 的取消语义由 reduce 保证。
TERMINAL: frozenset[str] = frozenset({EventType.RUN_CANCELLED, EventType.RUN_FAILED, EventType.RUN_COMPLETED})

#: 带内注入标记（B1/c4）：在用户正文里界定「系统/工具注入段」的起止符。
#: 生产者（B4 SeedContext / B7 记忆注入等）**必须成对**书写；落库前由 :func:`strip_scaffolding` 剥除，
#: 使事实流里的 ``user_message.text`` 只留「用户原话」（仿 hermes 的 ephemeral-scaffolding 语义）。
#: **不做** hermes 上游那种「标记 = 已落库」式的去重——它的行标记是**别仓私有符号**，
#: 不属本仓符号域（本注释刻意不引其名：`check_comment_refs` 只认本仓标识符，外部符号名会被判悬空）；
#: 去重只能靠 ``apply`` 的幂等键（B0 咽喉），标记只用于内容剥离（R5：不造第二套去重）。
SCAFFOLDING_OPEN = "<<questor:injected>>"
SCAFFOLDING_CLOSE = "<<questor:end-injected>>"


def strip_scaffolding(text: str) -> str:
    """剥掉带内标记的注入脚手架段，返回「用户原话」。

    - 每对 ``OPEN ... CLOSE``（含标记与段内文本）整体移除，支持多段；
    - **未闭合**的 ``OPEN``：从该标记起到文末全部移除（fail-closed——注入段边界未知，
      绝不把注入文本当「用户原话」落库）；
    - 孤儿 ``CLOSE``（无对应 OPEN）：只剥标记记号本身，两侧文本保留（不丢用户词）；
    - 无标记时**逐字节等价**返回（既有行为零变化）。
    """
    if SCAFFOLDING_OPEN not in text and SCAFFOLDING_CLOSE not in text:
        return text
    kept: list[str] = []
    rest = text
    while rest:
        start = rest.find(SCAFFOLDING_OPEN)
        if start < 0:
            kept.append(rest.replace(SCAFFOLDING_CLOSE, ""))
            break
        kept.append(rest[:start].replace(SCAFFOLDING_CLOSE, ""))
        tail = rest[start + len(SCAFFOLDING_OPEN) :]
        end = tail.find(SCAFFOLDING_CLOSE)
        if end < 0:
            break  # 未闭合 OPEN：其后全部按注入段处理
        rest = tail[end + len(SCAFFOLDING_CLOSE) :]
    return "".join(kept)


def is_live_only(env: Envelope) -> bool:
    """``True`` = 只转发、永不入库。"""
    return env.type in LIVE_ONLY


def is_terminal(env: Envelope) -> bool:
    """``True`` = 该 run 的终态事件（C13 first-writer-wins 的唯一判据）。"""
    return env.type in TERMINAL


def _bounded_text(text: str, limit: int) -> str:
    """按 **UTF-8 字节** 截断（不按字符数），截断处带标记；不劈开多字节字符。"""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    kept = raw[:limit].decode("utf-8", errors="ignore")
    return f"{kept}…[truncated {len(raw) - limit} bytes]"


def _bounded_value(value: object, limit: int) -> object:
    """递归把超限字符串收进预算；非字符串结构（dict/tuple）保持形状。"""
    if isinstance(value, str):
        return _bounded_text(value, limit)
    if isinstance(value, dict):
        return {k: _bounded_value(v, limit) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_bounded_value(v, limit) for v in value)
    return value


def durable_form(env: Envelope, budget: OutputBudget | None = None) -> Envelope | None:
    """决定一条事件的**持久化形态**：``None`` = 不入库（live-only），否则返回要落库的信封。

    纯函数、不做 IO、不碰 store——调用方（kernel bus）拿返回值去 ``append``。这正是
    ``scripts/check_reduce_chokepoint.py`` 断言的唯一形态来源：``event_log.append`` 的载荷
    只可能来自本函数的返回，不允许在别处另造一份"要不要落库 / 落成什么"的判断。

    B1/c4：``user_message`` 的正文在落库前剥掉带内标记的注入脚手架（:func:`strip_scaffolding`）——
    事实流里只留「用户原话」，标记绝不进持久正文；内存/快照里的 context 消息**不动**
    （注入段是模型的合法输入，不是真相）。
    """
    if env.type in LIVE_ONLY:
        return None
    if env.type == EventType.USER_MESSAGE:
        text = env.data.get("text")
        if isinstance(text, str) and (SCAFFOLDING_OPEN in text or SCAFFOLDING_CLOSE in text):
            data = dict(env.data)
            data["text"] = strip_scaffolding(text)
            env = replace(env, data=data)
    if budget is None:
        return env
    data = _bounded_value(dict(env.data), budget.model_result_bytes)
    return env if data == dict(env.data) else replace(env, data=data)


__all__ = [
    "LIVE_ONLY",
    "SCAFFOLDING_CLOSE",
    "SCAFFOLDING_OPEN",
    "TERMINAL",
    "durable_form",
    "is_live_only",
    "is_terminal",
    "strip_scaffolding",
]
