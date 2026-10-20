"""B15（可问可看）：`ask_user` 复用审批生命周期 + `/context`、`/cost` 只读账单。

判据分两半：

* **可问**：`approval_mode="prompt"` 必须把本会 ALLOW 的调用抬成 ASK（问对一句胜过做十步的前提是
  "问了真的会停下来等人答"），且 allow / deny / expired 三态在既有事实流里各自可复现——
  工具本身**不**假装能拿到自由文本答案。
* **可看**：账单的每一段都带 `estimate` 字样（仓内没有官方 tokenizer），成本没有价目表就停在 token，
  并且**没跑过的 run 不会被编出一份看似完整的报告**。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.capabilities.tools.ask_user import MAX_OPTIONS, MAX_QUESTION_CHARS, AskUserTool
from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.state_schema import ContentBlock, Message, Role, ToolArgsStatus
from questor.contracts.tool import ToolResult
from questor.kernel.permission_policy import PermissionDecision, PermissionEvaluation, evaluate_permission
from questor.providers.fake import EchoProvider, ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Context, PermissionCtx, Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.context_report import (
    COST_REPLAY_LIMIT,
    context_report_for_run,
    context_segments,
    cost_report_for_store,
    estimate_tokens,
    format_context_report,
)


class _Ctx:
    """最小 ToolContext：本工具只需要取消位，不碰任何 store 句柄（C4）。"""

    def __init__(self, *, cancelled: bool = False) -> None:
        self.tool_call_id = "tc-ask"
        self.workspace_root = Path(".")
        self.cwd = Path(".")
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled


def _evaluation(tool: AskUserTool, arguments: dict) -> PermissionEvaluation:
    return PermissionEvaluation(
        tool_name=tool.spec.name,
        tool_spec=tool.spec,
        args_status=ToolArgsStatus.VALID,
        arguments=arguments,
        permission=PermissionCtx(),
        # NullSandbox 形状（本工具不跑进程也不联网）：写/网围栏都是 False。
        sandbox=SandboxDescriptor(
            backend=SandboxBackend.NONE,
            confinement=Confinement.NONE,
            fences_writes=False,
            fences_network=False,
            isolates_process_tree=False,
            limitation="no sandbox: ask_user only surfaces a question",
        ),
    )


def test_ask_user_spec_is_the_prompt_mode() -> None:
    tool = AskUserTool()
    assert tool.spec.approval_mode == "prompt"
    assert tool.spec.read_only is True and tool.spec.capability.value == "readonly"
    assert tool.spec.name == "ask_user"
    assert "question" in tool.spec.params["required"]


def test_prompt_mode_escalates_allow_to_ask() -> None:
    """权限本来会 ALLOW 的只读工具，被 `approval_mode="prompt"` 抬成 ASK（只收紧不放宽）。"""
    tool = AskUserTool()
    outcome = evaluate_permission(_evaluation(tool, {"question": "ship today or tomorrow?"}))
    assert outcome.decision is PermissionDecision.ASK
    assert "confirmation" in outcome.reason.lower()


async def test_execute_after_assent_is_bounded_and_honest() -> None:
    tool = AskUserTool()
    result = await tool.execute(
        {"question": "ship today?", "options": ["today", "tomorrow"] * 4, "why": "release window"},
        _Ctx(),
    )
    assert isinstance(result, ToolResult) and result.status == "success"
    assert result.result and "ship today?" in result.result
    assert "assent only" in result.result  # 明说这不是自由文本回答通道
    assert len(result.result.split("options offered: ")[1].split("\n")[0].split("|")) <= MAX_OPTIONS
    assert result.display and result.display.startswith("✓")


async def test_execute_rejects_bad_questions_without_inventing_an_answer() -> None:
    tool = AskUserTool()
    for args in ({}, {"question": "   "}, {"question": "x" * (MAX_QUESTION_CHARS + 1)}, {"question": "ok", "options": "not-a-list"}):
        result = await tool.execute(args, _Ctx())
        assert result.status == "error", args
    assert (await tool.execute({"question": "cancelled?"}, _Ctx(cancelled=True))).status == "error"


def _run(items: tuple[Message, ...]) -> Run:
    return Run(run_id="r-report", turn=2, context=Context(items=items, summary="folded middle"))


def _msg(role: Role, text: str, seq: int) -> Message:
    return Message(id=f"m{seq}", role=role, content=(ContentBlock(type="text", text=text),), seq=seq)


def test_context_report_is_estimated_and_shows_what_is_not_there() -> None:
    run = _run((_msg(Role.USER, "q" * 400, 0), _msg(Role.ASSISTANT, "a" * 200, 1)))
    tool = AskUserTool()
    segments = context_segments(run, system="sys" * 100, tools=(tool.spec,), memory_index_chars=120)
    report = format_context_report(run, segments)
    assert "system" in report and "history" in report and "summary" in report
    assert "(estimate)" in report  # 每个 token 数都带估算标记
    assert "window: unknown" in report  # 没配窗口就明说，不编一个 128k
    total_line = next(line for line in report.splitlines() if "total" in line)
    assert "estimate" in total_line


def test_context_report_marks_the_threshold_it_can_compute() -> None:
    from questor.contracts.policy import CompactionConfig

    window = CompactionConfig(context_window=200_000, max_output=8_192)
    run = _run((_msg(Role.USER, "hi", 0),))
    report = format_context_report(run, context_segments(run, system="s", tools=()), window=window)
    assert "auto_threshold=" in report and "warning_threshold=" in report


async def test_reports_refuse_to_fabricate_for_unknown_runs(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider())
        text = await context_report_for_run(store, surface, "run-nope")
        assert "no durable state" in text  # 不编一份"看起来是 0"的报告
        cost = await cost_report_for_store(store)
        assert "cost_usd=UNVERIFIED" in cost
        assert "n/a (no succeeded tasks)" in cost  # 比值不存在，不是 0
        assert "run_completed.usage" not in cost.split("\n")[0]
    finally:
        await store.close()


async def test_cost_report_projects_durable_usage(tmp_path: Path) -> None:
    """`--cost` 的数只能来自 durable `run_completed.usage`（与 `logs --totals` 同一口径）。"""
    from questor.contracts.events import FinalizeRun, RecordTurnCompleted, SubmitMessage
    from questor.state.reduce import reduce

    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        run = Run(run_id="rcost")
        run, events = reduce(run, SubmitMessage(run_id="rcost", content=_msg(Role.USER, "hi", 0)))
        await store.append("rcost", tuple({"v": 1, "seq": e.seq, "run_id": e.run_id, "type": e.type, "turn": e.turn, "data": dict(e.data)} for e in events))
        run, events = reduce(run, RecordTurnCompleted(run_id="rcost", turn=1, usage={"input_tokens": 120, "output_tokens": 30}, interrupted=False))
        await store.append("rcost", tuple({"v": 1, "seq": e.seq, "run_id": e.run_id, "type": e.type, "turn": e.turn, "data": dict(e.data)} for e in events))
        run, events = reduce(run, FinalizeRun(run_id="rcost", status="completed", final="done", usage={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}, exit_reason="answered"))
        await store.append("rcost", tuple({"v": 1, "seq": e.seq, "run_id": e.run_id, "type": e.type, "turn": e.turn, "data": dict(e.data)} for e in events))
        report = await cost_report_for_store(store)
        assert "total_tokens=150" in report
        assert "tokens_per_succeeded_task=150.0" in report
        assert "cost_usd=UNVERIFIED" in report
        assert COST_REPLAY_LIMIT > 0
    finally:
        await store.close()


def test_ask_user_is_only_added_by_the_composition_root() -> None:
    """默认 profile 名册不变；`ask_user` 是组合根追加的那一步（直接构造 CliSurface 的旧路径不多工具）。"""
    plain = CliSurface(provider=ScriptedProvider([]))
    assert "ask_user" not in {tool.spec.name for tool in plain.registry.list_available()}
    wired = CliSurface(provider=ScriptedProvider([]), extra_tools=(AskUserTool(),))
    names = [tool.spec.name for tool in wired.registry.list_available()]
    assert names[-1] == "ask_user"  # 追加在末尾：既有顺序一位不动
    assert names[:-1] == [tool.spec.name for tool in plain.registry.list_available()]


def test_estimate_tokens_rounds_up_never_down() -> None:
    assert estimate_tokens(0) == 0
    assert estimate_tokens(1) == 1
    assert estimate_tokens(101) == 26  # 向上取整：宁多报不少报
    with pytest.raises(TypeError):
        estimate_tokens(None)  # type: ignore[arg-type]
