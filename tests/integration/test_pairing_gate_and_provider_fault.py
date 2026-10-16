"""ADR-0028：回发前配对关卡 + provider 故障归一（真机崩溃的证伪测试）。

复现事实（2026-10-16 对抗核验，脚本化 provider + 按 OpenAI/DeepSeek 规则校验投影历史）：
模型**一轮返回 ≥2 个 tool_call** 时，串行循环只执行第一条就回发下一次请求，历史里留下悬空
tool_call → provider 400 → 异常一路穿出 ``drive_controller`` → CLI 进程带 traceback 退出、
run 不落任何终态。三类形状都必须被钉住：
① 多调用轮必须"全部闭合才回发"（关卡真执行，不合成占位结果）；
② provider 故障归一 ``run_failed``（``ErrorEntry`` 带正确 kind/retryable），绝不崩进程；
③ 历史不可调和（context 有悬空 tool_use、账本无 OPEN 条目）时 fail-closed，**一次都不发**。

另钉四条纪律：取消优先于关卡补执行（C7/R01 F8）；退避重试编排后置 P10，本轮不得多打一次；
被 reduce 拒收的 assistant 不得经 ``FinalizeRun(final=…)`` 走私回 context（实测缺陷）；
关卡补执行只改变“接下来跑哪条”、**不改变“谁能跑”**（权限/floor/参数校验全部照走）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.write import WriteTool
from questor.contracts.common import new_id
from questor.contracts.events import AdvanceTurn, AppendAssistantMessage, SubmitMessage
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.contracts.state_schema import ApprovalStatus, Budget, ContentBlock, Message, Role, ToolArgsStatus, ToolCallStatus
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.litellm_adapter import to_openai_messages
from questor.state.checkpoint import open_tool_use_ids
from questor.state.domain_state import Run, ToolLedger
from questor.state.reduce import reduce

# 真机上把 CLI 打崩的那条错误文本（OpenAI 兼容网关的形状）。
_PAIRING_400 = "Error code: 400 - An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'. (insufficient tool messages)"

_TEXT = [StreamChunk(kind="text", text="都读完了"), StreamChunk(kind="finish", finish_reason="stop")]
_TERMINAL = {"run_completed", "run_failed", "run_cancelled"}


def _unpaired_ids(messages: tuple[Message, ...]) -> set[str]:
    """按 provider 的线上规则判悬空：assistant.tool_calls 之后必须跟齐每个 tool_call_id 的 tool 消息。

    为什么不复用 ``state.checkpoint.open_tool_use_ids``：那是关卡自己的判据，测试用**投影后的线上
    形状**独立判红，才不会和实现同源失效。
    """
    projected = to_openai_messages(messages, None)
    missing: set[str] = set()
    for index, entry in enumerate(projected):
        if not entry.get("tool_calls"):
            continue
        required = {call["id"] for call in entry["tool_calls"]}
        responded = set()
        cursor = index + 1
        while cursor < len(projected) and projected[cursor]["role"] == "tool":
            responded.add(projected[cursor]["tool_call_id"])
            cursor += 1
        missing |= required - responded
    return missing


class _Provider(ProviderPort):
    """脚本化 provider：可选「线上规则校验」与「第 N 次调用注入异常」。

    失败语义：``reject_unpaired`` 为真且投影历史有悬空 tool_call 时，抛 400 形状 ``RuntimeError``
    （等价真网关行为）；``fail_at`` 指定第几次 stream 抛 ``fail_exc``（默认同 400）。
    """

    def __init__(self, turns: list[list[StreamChunk]], *, reject_unpaired: bool = False, fail_at: int | None = None, fail_exc: BaseException | None = None) -> None:
        self.turns = turns
        self.reject_unpaired = reject_unpaired
        self.fail_at = fail_at
        self.fail_exc = fail_exc
        self.calls = 0
        self._index = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        self.calls += 1
        if self.reject_unpaired:
            missing = _unpaired_ids(request.messages)
            if missing:
                raise RuntimeError(f"{_PAIRING_400} missing={sorted(missing)}")
        if self.fail_at is not None and self.calls == self.fail_at:
            raise self.fail_exc or RuntimeError(_PAIRING_400)
        if self._index >= len(self.turns):
            yield StreamChunk(kind="finish", finish_reason="stop")
            return
        for chunk in self.turns[self._index]:
            yield chunk
        self._index += 1


class _StatusError(Exception):
    """带 ``status_code`` 的 provider 异常（openai/litellm 的错误形状）。"""

    def __init__(self, status_code: int, message: str = "provider refused") -> None:
        super().__init__(f"Error code: {status_code} - {message}")
        self.status_code = status_code


class _CancelAfterTool(Tool):
    """执行后立刻置取消事件的只读工具：用来钉「取消优先于关卡补执行」。"""

    spec = ToolSpec(
        name="cancelread",
        description="read-only probe that raises the cancel flag after running",
        params={"type": "object", "properties": {}, "additionalProperties": False},
        capability=Capability.READONLY,
        risk=Risk.LOW,
        read_only=True,
    )

    def __init__(self, cancel: asyncio.Event) -> None:
        self._cancel = cancel

    def available(self) -> bool:
        return True

    async def execute(self, args: object, ctx: ToolContext) -> ToolResult:
        self._cancel.set()
        return ToolResult(status="success", result="done")


def _calls_turn(*specs: tuple[str, str]) -> list[StreamChunk]:
    """一条 assistant 消息里发多个 tool_call（index 递增，等价 DeepSeek 一轮并行调工具）。"""
    chunks = [StreamChunk(kind="text", text="我先看看工作区。")]
    for index, (call_id, path) in enumerate(specs):
        chunks.append(StreamChunk(kind="tool_call", tool_call={"index": index, "id": call_id, "name": "read", "args_delta": f'{{"file_path": "{path}"}}'}))
    chunks.append(StreamChunk(kind="finish", finish_reason="tool_calls"))
    return chunks


def _setup(tmp: Path) -> None:
    (tmp / "a.txt").write_text("AAA", encoding="utf-8")
    (tmp / "b.txt").write_text("BBB", encoding="utf-8")


def _make(tmp: Path, provider: ProviderPort, *, cancel: asyncio.Event | None = None, extra_tools: tuple[Tool, ...] = ()) -> tuple[DefaultTurnLoop, InProcessEventBus]:
    read = ReadTool()
    by_name = {read.spec.name: read, **{tool.spec.name: tool for tool in extra_tools}}
    bus = InProcessEventBus(None)
    loop = DefaultTurnLoop(
        provider=provider,
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=by_name.get,
        tools=(read, *extra_tools),
        workspace_root=tmp,
        model="test-model",
        cancel_event=cancel,
    )
    return loop, bus


def _run(max_turns: int = 6) -> Run:
    return Run(run_id=new_id("run"), budget=Budget(max_turns=max_turns))


async def _drive(loop: DefaultTurnLoop, run: Run, bus: InProcessEventBus) -> tuple[Run, list[str]]:
    """驱动到终态，并收回总线上的事件类型（终态计数是 C13「恰一终态」的判据）。"""
    queue = bus.add_subscriber(run.run_id)
    final = await loop.drive(run, "看看我的工作区")
    types: list[str] = []
    while not queue.empty():
        types.append(queue.get_nowait().type)
    return final, types


def _results_for(run: Run, call_id: str) -> list[str]:
    return [b.text or "" for m in run.context.items for b in m.content if b.type == "tool_result" and b.tool_use_id == call_id]


def _poisoned_run(run_id: str, call_id: str) -> Run:
    """造出"context 有悬空 tool_use、账本却被抹平"的分裂态（关卡判红样例）。

    为什么手工造：正常路径经 ``AppendAssistantMessage`` 一定同步步建账本条目，这条分裂只能注入。
    它守的是 P2 审计实测过的另一条泄漏（被拒收的消息回灌 context），关卡必须对此 fail-closed。
    """
    run = Run(run_id=run_id, budget=Budget(max_turns=4))
    run, _ = reduce(run, SubmitMessage(run_id=run_id, content=Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text="看看我的工作区"),), seq=0)))
    run, _ = reduce(run, AdvanceTurn(run_id=run_id, turn=1))
    block = ContentBlock(type="tool_use", tool_use_id=call_id, name="read", input={"file_path": "a.txt"}, args_status=ToolArgsStatus.VALID)
    run, _ = reduce(run, AppendAssistantMessage(run_id=run_id, turn=1, message=Message(id=new_id("msg"), role=Role.ASSISTANT, content=(block,), seq=1)))
    return replace(run, tool_ledger=ToolLedger(calls=()))


def test_provider_stream_has_exactly_one_call_site_and_it_sits_behind_the_gate() -> None:
    """C19 的机械面：全仓只允许一个 ``ProviderPort.stream`` 调用点，且它必先行走关卡。

    为什么用源码扫描而不是运行时断言：关卡的价值在于**没人能绕过**。多开一个调用点（P5 MCP、
    P9 OpenAI 兼容 API 都可能是下一个）会把这条不变式静默地变成“看运气”——而这正是本次崩溃的成因。
    fail-on-empty：扫不到任何调用点同样判红（不能把“没匹配到”当成通过）。
    """
    root = Path("src/questor")
    # as_posix()：CI 同时在 ubuntu-24.04 与 windows-2022 跑，Windows 下 relative_to 会给出
    # 反斜杠路径，不归一就会把“绿”变成平台相关的假红。
    callers = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py") if "self.provider.stream(" in path.read_text(encoding="utf-8"))
    assert callers == ["kernel/loop.py"], f"provider 调用点必须唯一且在 kernel：{callers}"

    body = (root / "kernel" / "loop.py").read_text(encoding="utf-8")
    stream_turn = body.split("async def _stream_turn", 1)[1].split("async def _ensure_paired_history", 1)[0]
    assert "self._ensure_paired_history(" in stream_turn, "关卡不得从 _stream_turn 里被拆出去"
    assert "self._consume_stream(" in stream_turn.split("_ensure_paired_history(", 1)[1], "请求必须在关卡之后"


async def test_parallel_tool_calls_all_settle_before_next_provider_request(tmp_path: Path) -> None:
    """一轮两 tool_call：两条都真执行、配对齐了才回发（provider 侧按线上规则校验）。"""
    _setup(tmp_path)
    provider = _Provider([_calls_turn(("call_1", "a.txt"), ("call_2", "b.txt")), _TEXT], reject_unpaired=True)
    loop, bus = _make(tmp_path, provider)

    final, types = await _drive(loop, _run(), bus)

    assert final.status.value == "completed", final.status
    assert provider.calls == 2, "关卡补齐后只需一次额外请求，不该反复带悬空回发"
    assert {c.status for c in final.tool_ledger.calls} == {ToolCallStatus.SUCCESS}
    # 真执行（不是合成占位）：两条 tool_result 各自带文件正文。
    assert _results_for(final, "call_1") == ["AAA"], final.context.items
    assert _results_for(final, "call_2") == ["BBB"]
    assert open_tool_use_ids(final.context.items) == (), "I1 配对不变式被破坏"
    assert [t for t in types if t in _TERMINAL] == ["run_completed"]


async def test_stop_gate_no_longer_resends_unpaired_history(tmp_path: Path) -> None:
    """策略想 Finish 但账本还有未闭合调用时：关卡先补齐，而不是把悬空历史再发一次。"""
    _setup(tmp_path)
    provider = _Provider([_calls_turn(("call_1", "a.txt"), ("call_2", "b.txt")), _TEXT])
    loop, bus = _make(tmp_path, provider)

    final, _ = await _drive(loop, _run(), bus)

    assert final.status.value == "completed"
    assert provider.calls == 2, f"关卡应在回发前闭合 call_2，实测 stream {provider.calls} 次"
    assert open_tool_use_ids(final.context.items) == ()


async def test_provider_400_becomes_failed_terminal_instead_of_killing_the_process(tmp_path: Path) -> None:
    """provider 故障域：400 必须归一 ``run_failed``（PROVIDER/FORMAT_ERROR/不可重试），绝不穿出 loop。"""
    _setup(tmp_path)
    provider = _Provider([_calls_turn(("call_1", "a.txt"), ("call_2", "b.txt")), _TEXT], fail_at=2)
    loop, bus = _make(tmp_path, provider)

    final, types = await _drive(loop, _run(), bus)  # 修复前：这里直接抛 RuntimeError

    assert final.status.value == "failed"
    entry = final.error_stack[-1]
    assert entry.layer.value == "provider"
    assert entry.kind.value == "format_error"
    assert entry.hints.retryable is False, "配对违规是确定性错误，重试只会原样再失败"
    assert [t for t in types if t in _TERMINAL] == ["run_failed"], "恰一终态（C13）"
    # 终态侧配对仍守住：FinalizeRun 回填把落单的 call_2 闭合，durable 历史不带悬空进 resume。
    assert open_tool_use_ids(final.context.items) == (), final.context.items


async def test_transient_provider_error_is_voiced_retryable_without_auto_retry(tmp_path: Path) -> None:
    """429 归 RATE_LIMIT 且 retryable=True；退避/fallback 编排按 ADR-0028 后置 P10，本轮不多打一次。"""
    _setup(tmp_path)
    provider = _Provider([_calls_turn(("call_1", "a.txt"))], fail_at=1, fail_exc=_StatusError(429, "Too Many Requests"))
    loop, bus = _make(tmp_path, provider)

    final, _ = await _drive(loop, _run(), bus)

    assert final.status.value == "failed"
    entry = final.error_stack[-1]
    assert entry.kind.value == "rate_limit"
    assert entry.hints.retryable is True
    assert provider.calls == 1, "重试编排属 P10（plan/01 §1.2 后置），本轮不得自动重试烧预算"


async def test_unpaired_history_without_open_ledger_call_fails_closed_and_never_sends(tmp_path: Path) -> None:
    """不可调和的历史：关卡 fail-closed，一次都不发（发出去就是那次 400）。"""
    _setup(tmp_path)
    provider = _Provider([_TEXT])
    loop, bus = _make(tmp_path, provider)

    final, _types = await _drive(loop, _poisoned_run(new_id("run"), "tc_ghost"), bus)

    assert provider.calls == 0
    assert final.status.value == "failed"
    entry = final.error_stack[-1]
    assert entry.kind.value == "format_error"
    assert entry.layer.value == "kernel", "我们造出的非法历史属内核不变式失败，不是模型侧错误"
    assert "tc_ghost" in entry.message


async def test_rejected_duplicate_tool_use_id_does_not_smuggle_dangling_message(tmp_path: Path) -> None:
    """重复 tool_use_id 被 reduce 整条拒收后：不得再把它当 final 写回 context（实测缺陷）。"""
    _setup(tmp_path)
    first = _calls_turn(("tc_1", "a.txt"))
    dup = [StreamChunk(kind="text", text="我再读一次"), *first[1:]]  # 复用同一个 tool_use id
    provider = _Provider([first, dup, dup])
    loop, bus = _make(tmp_path, provider)

    final, types = await _drive(loop, _run(), bus)

    assert final.status.value == "failed", "被拒收的消息不能伪装成正常收尾"
    entry = final.error_stack[-1]
    assert entry.kind.value == "format_error"
    assert entry.layer.value == "provider"
    use_blocks = [b for m in final.context.items for b in m.content if b.type == "tool_use"]
    assert len(use_blocks) == 1, f"拒收的 assistant 不得走私进 durable：{use_blocks}"
    assert open_tool_use_ids(final.context.items) == ()
    assert [t for t in types if t in _TERMINAL] == ["run_failed"]


async def test_cancel_wins_over_gate_backfill(tmp_path: Path) -> None:
    """取消优先：关卡不得为了补齐配对而继续执行未跑的调用（C7；R01 F8 取消绝不进重试路径）。"""
    _setup(tmp_path)
    cancel = asyncio.Event()
    probe = _CancelAfterTool(cancel)
    turn = [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "c1", "name": "cancelread", "args_delta": "{}"}),
        StreamChunk(kind="tool_call", tool_call={"index": 1, "id": "c2", "name": "cancelread", "args_delta": "{}"}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]
    provider = _Provider([turn, _TEXT])
    loop, bus = _make(tmp_path, provider, cancel=cancel, extra_tools=(probe,))

    final, types = await _drive(loop, _run(), bus)

    assert final.status.value == "cancelled"
    assert provider.calls == 1, "取消后不得再补一次 provider 请求"
    by_id = {c.tool_call_id: c for c in final.tool_ledger.calls}
    assert by_id["c2"].status is ToolCallStatus.CANCELLED, "落单调用由 reduce Cancel 回填闭合"
    assert open_tool_use_ids(final.context.items) == ()
    assert final.error_stack == (), "取消不是错误，绝不进 error_stack/重试分类"
    assert [t for t in types if t in _TERMINAL] == ["run_cancelled"]


async def test_gate_settles_invalid_args_call_as_error_and_still_pairs(tmp_path: Path) -> None:
    """关卡补执行不跳过参数校验：落单调用的 args 非法时仍必须闭合配对（每一调都有回应）。"""
    _setup(tmp_path)
    turn = [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "ok_1", "name": "read", "args_delta": '{"file_path": "a.txt"}'}),
        StreamChunk(kind="tool_call", tool_call={"index": 1, "id": "bad_2", "name": "read", "args_delta": '{"file_path": '}),  # 截断的非法 JSON
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]
    provider = _Provider([turn, _TEXT], reject_unpaired=True)
    loop, bus = _make(tmp_path, provider)

    final, _types = await _drive(loop, _run(), bus)

    assert final.status.value == "completed"
    by_id = {c.tool_call_id: c for c in final.tool_ledger.calls}
    assert by_id["ok_1"].status is ToolCallStatus.SUCCESS
    assert by_id["bad_2"].status is ToolCallStatus.ERROR, by_id["bad_2"].status
    assert "invalid json arguments" in str(by_id["bad_2"].result)
    assert open_tool_use_ids(final.context.items) == (), "非法参数也必须回一条 tool_result"


async def test_gate_backfill_never_bypasses_the_permission_gate(tmp_path: Path) -> None:
    """关卡补执行一个无围栏的 write：必须真的发起并等待审批，绝不绕过 ask/floor。

    这是 P3 resume 已测纪律的同步延用（ADR-0021）：关卡只是把“**接下来跑哪条调用**”的决定权
    从策略手里提到回发前，**不改变“谁能跑”**。实测本例发出 `approval_request`（理由为 write
    capability floor：none 后端无写围栏）→ 无交互则超时 fail-closed deny，目标文件不得落盘。
    """
    _setup(tmp_path)
    target = tmp_path / "victim.txt"
    turn = [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "r1", "name": "read", "args_delta": '{"file_path": "a.txt"}'}),
        StreamChunk(kind="tool_call", tool_call={"index": 1, "id": "w2", "name": "write", "args_delta": f'{{"file_path": "{target.name}", "content": "boom"}}'}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]
    provider = _Provider([turn, _TEXT], reject_unpaired=True)
    read, write = ReadTool(), WriteTool()
    bus = InProcessEventBus(None)
    loop = DefaultTurnLoop(
        provider=provider,
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=lambda name: read if name == "read" else write if name == "write" else None,
        tools=(read, write),
        workspace_root=tmp_path,
        model="test-model",
    )
    run = Run(run_id=new_id("run"), budget=Budget(max_turns=6, approval_timeout_seconds=0.05))

    final, types = await _drive(loop, run, bus)

    assert not target.exists(), "关卡不得把未批的写静默放行"
    by_id = {c.tool_call_id: c for c in final.tool_ledger.calls}
    assert by_id["w2"].status is ToolCallStatus.DENIED, by_id["w2"].status
    assert by_id["w2"].permission_decision == "deny"
    # 不只看“被拒”，还要钉住“真的问了”：审批请求已对外发出且因无人决策而过期 fail-closed。
    assert "approval_request" in types, "关卡补执行必须走 ask，不能静默放行"
    asked = [a for a in final.permission_ctx.approvals if a.tool_call_id == "w2"]
    assert asked and asked[0].status is ApprovalStatus.EXPIRED and asked[0].decided_by == "timeout", asked
    assert "capability floor" in (asked[0].reason or "").lower(), asked[0].reason
    assert open_tool_use_ids(final.context.items) == (), "被拒的落单调用同样要闭合配对"
    assert provider.calls == 2
