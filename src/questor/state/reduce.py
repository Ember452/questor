"""L1 ``reduce`` —— Domain_State 的**唯一写者**（design/01 §7；HARD C2/C5/C7/C13）。

``reduce(run, command) -> (new_run, durable_events)``。它绝不原地改传入的 ``Run``，
而是经 ``dataclasses.replace`` 返回一个全新的（COW，旧快照对回放/分支仍有效——C2/C3、X3）。

在 reduce 内部强制的不变式（不靠上层自觉，design/01 §12）：
- I1 配对：``tool_use`` id 必须唯一，且结果只能闭合一个仍打开的调用。
- C7：``Cancel`` 置 cancelled **且**把所有未闭合 tool_call 回填为 error。
- C13 / 02 E2：一旦终态即冻结——后续 Command 被拒并发 ``warning`` 事件（first-writer-wins，恰一终态）。

delta（``text_delta``/``tool_progress``）是 live-only、绝不经 reduce（I3）。这是纯状态机；
turn 循环（kernel）驱动它。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from questor.contracts.artifacts import OutputBudget
from questor.contracts.common import utc_now
from questor.contracts.events import (
    EVENT_SCHEMA_VERSION,
    AdvanceTurn,
    AppendAssistantMessage,
    Cancel,
    Command,
    CompactContext,
    Envelope,
    EventType,
    ExpireApproval,
    FinalizeRun,
    MarkToolDenied,
    MarkToolRunning,
    MarkToolValidated,
    RecordToolResult,
    RecordWarning,
    ReportChildTerminal,
    RequestApproval,
    ResolveApproval,
    SetPermissionMode,
    SpawnSubagent,
    SubmitMessage,
    UpdateTaskTree,
    WriteMemory,
)
from questor.contracts.memory import source_for_write
from questor.contracts.profile import PERMISSION_MODE_SET
from questor.contracts.state_schema import (
    OPEN_TOOL_CALL_STATUSES,
    ApprovalRequest,
    ApprovalStatus,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    TaskKind,
    TaskNode,
    TaskStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.state.checkpoint import closed_prefix
from questor.state.domain_state import Context, PermissionCtx, PermissionDecisionRecord, Run, TaskTree

_OPEN_CALL = OPEN_TOOL_CALL_STATUSES

#: 任务节点的终态集（first-writer-wins：已终态的节点不被迟到 ReportChildTerminal 翻案）。
_TERMINAL_NODE_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED}
)

#: 单条记忆写载荷的字节上限（承 ADR-0019 ToolResult 默认 16 KiB；超限 fail-closed 拒，
#: 防长跑把 memory.db / event payload 撑爆。实现期可经配置覆盖，只增不改）。
_MAX_MEMORY_WRITE_BYTES = 16 * 1024

#: 工具事件内 preview 的字符上限（P7 T7；C18）——远小于 ADR-0019 的 16 KiB model 预算，
#: 因为事件帧要给所有 surface 高频扇出、必须比“回模型”的预算更小。全文靠 artifact 指针按需读。
_TOOL_PREVIEW_CHARS = 4096

#: 定稿消息 `final_text` 的字符上限（D-P7-C 选型①；ADR-0034 / C18）。事件帧恒有界；超长部分
#: 置 `truncated=True`，完整正文仍以 checkpoint（Domain_State.context.items）为权威（reduce 无法做
#: 异步 IO，故不在事件内归档；重连常见消息即自足，病态超长靠 rebuild）。
_MSG_FINAL_TEXT_CHARS = 8192

#: 进模型的 tool_result 文本上限（#158；承 C18/ADR-0019 的 16 KiB 预算）。超限截断并标注，
#: 全文归档留待 exec/artifact 接线（#154）经 envelope_for_text 承接——避免单条 bash~2MiB/MCP 无界结果炸上下文与计费。
_MAX_MODEL_TOOL_RESULT_CHARS = 16 * 1024

#: 进事实流的用户正文上限（B1；设计文档 §4.2 事实流补齐）。与 `protocol/event.schema.json` 的
#: `$defs.user_message.text.maxLength` **同源**（= :class:`OutputBudget` 的 model 预算），
#: 由 `check_protocol_schema._max_length_drift` 机守；单位按 UTF-8 字节（OutputBudget 的声明单位）。
_USER_MESSAGE_TEXT_BYTES = OutputBudget().model_result_bytes


def _bounded_user_text(text: str) -> tuple[str, bool]:
    """把用户正文收进 OutputBudget 预算（按 **UTF-8 字节**截断、不劈开多字节字符）。

    返回 ``(有界正文, 是否截断)``：截断不静默——``truncated=True`` 随事件外发（承 message_completed
    先例）。完整正文仍以 checkpoint（Domain_State.context.items）为权威，事件帧恒有界。
    """
    raw = text.encode("utf-8")
    if len(raw) <= _USER_MESSAGE_TEXT_BYTES:
        return text, False
    return raw[:_USER_MESSAGE_TEXT_BYTES].decode("utf-8", errors="ignore"), True


def _message_completed_data(message: Message) -> dict[str, object]:
    """为 ``message_completed`` 派生**有界**定稿正文（D-P7-C 选型①；ADR-0034）。

    取消息可见文本（text 块拼接）写进事件帧，使 ``after_seq`` 重放**仅靠事件流**即可恢复定稿
    消息——单一真源，不另开 `/transcript` 第二读契约。纯字符串截断（L1 不做 IO）；`item_id` 供前端
    把 live delta 与定稿消息归组。**未定稿的半条在途 delta 仍不在本事件里**（诚实边界，标 UNVERIFIED）。
    """
    text = "".join(b.text or "" for b in message.content if b.type == "text")
    data: dict[str, object] = {
        "message_id": message.id,
        "item_id": message.id,
        "truncated": len(text) > _MSG_FINAL_TEXT_CHARS,
    }
    if text:
        data["final_text"] = text[:_MSG_FINAL_TEXT_CHARS]
    return data


def _tool_completed_data(tool_call_id: str, status: str, *, result: object, display: object) -> dict[str, object]:
    """为 ``tool_completed`` 事件派生**有界** preview + artifact 指针 + truncated（P7 T7；ADR-0035/ADR-0019）。

    - 短输出：``preview`` 即全文、``truncated=False``、无 ``artifact_ref``。
    - 超长 display：``preview`` 截到字符上限、``truncated=True``（不臆造指针）。
    - 归档信封（``result`` 为 ``archived_tool_result`` dict）：取内层有界 ``preview`` + ``artifact_ref.artifact_id``
      + ``truncated=True``。
    - **写失败绝不回退全文**（ADR-0019）：事件里永远最多一屏 preview；无归档就只给截断 preview。
    为何在 L1 内联 slice：不能 import L3 ``capabilities/tools/_output``（state 不得依赖上层，C1/C14），
    故自带一份极简字符截断（与 _output 的字节级 preview 同语义、只用于事件展示层上界）。
    """
    data: dict[str, object] = {"tool_call_id": tool_call_id, "status": status}
    text = display if isinstance(display, str) and display else (result if isinstance(result, str) else "")
    artifact_ref: object = None
    truncated = False
    if isinstance(result, dict) and result.get("kind") == "archived_tool_result":
        ref = result.get("artifact_ref")
        if isinstance(ref, dict) and isinstance(ref.get("artifact_id"), str):
            artifact_ref = ref["artifact_id"]
        inner = result.get("preview")
        if isinstance(inner, str):
            text = inner
        truncated = True
    if text:
        data["preview"] = text[:_TOOL_PREVIEW_CHARS]
        if len(text) > _TOOL_PREVIEW_CHARS:
            truncated = True
    if artifact_ref is not None:
        data["artifact_ref"] = artifact_ref
    data["truncated"] = truncated
    return data


def _event(seq: int, run: Run, turn: int | None, etype: str, data: dict) -> Envelope:
    """构造一个对外事件信封（v 取 wire 版本，run_id 取自当前 run）。"""
    return Envelope(v=EVENT_SCHEMA_VERSION, seq=seq, run_id=run.run_id, type=etype, turn=turn, data=data)


def _reject(run: Run, message: str) -> tuple[Run, list[Envelope]]:
    """拒绝一条命令：Domain_State 不改，但仍**占用一个 durable seq** 承载 warning。

    地基不变式：任何**产出 durable 事件**的分支必须同步推进 ``run.seq``——否则下一条 durable
    复用同一 seq，落库撞 ``event_log UNIQUE(run_id, seq)`` 并抛穿 ``bus.emit``（崩循环）。历史实现
    在单事件拒绝分支写 ``run.seq + 1`` 却 ``return run`` 不 bump，正是该碰撞（track5-backbone BLK-1 实测）。
    """
    seq = run.seq + 1
    return replace(run, seq=seq), [_event(seq, run, run.turn, EventType.WARNING, {"message": message})]


def validate_task_tree(nodes: tuple[TaskNode, ...]) -> list[str]:
    """任务树依赖校验（I1，[ADR-0037]）：唯一 id / 无自环 / 无悬空 dep / 无环。

    纯函数，返回问题清单（空=合法）。reduce 在写入 ``task_tree`` 前调用；非法即拒 + 发错误事件、
    **不改状态、不崩**（design/01 §12 I1）。**只校验、不做拓扑调度**（调度器/ fan-in 后置，见 ADR-0037）。
    环检测用 Kahn：反复移除“所有已知依赖均已就绪”的节点，残留者即在环中（悬空 dep 单独报、不掺入环判定）。
    """
    problems: list[str] = []
    seen: set[str] = set()
    dup: set[str] = set()
    for node in nodes:
        if node.id in seen:
            dup.add(node.id)
        seen.add(node.id)
    for node_id in sorted(dup):
        problems.append(f"duplicate node id {node_id!r}")

    deps_by_id: dict[str, tuple[str, ...]] = {node.id: node.deps for node in nodes}
    for node in nodes:
        for dep in node.deps:
            if dep == node.id:
                problems.append(f"node {node.id!r} depends on itself")
            elif dep not in deps_by_id:
                problems.append(f"node {node.id!r} has unknown dep {dep!r}")

    remaining = dict(deps_by_id)
    resolved: set[str] = set()
    while True:
        ready = [
            nid
            for nid, deps in remaining.items()
            if all(dep in resolved or dep not in deps_by_id for dep in deps)
        ]
        if not ready:
            break
        for nid in ready:
            resolved.add(nid)
            remaining.pop(nid, None)
    if remaining:
        problems.append(f"cycle detected involving {sorted(remaining)}")
    return problems


def reduce(run: Run, command: Command, *, now: datetime | None = None) -> tuple[Run, list[Envelope]]:  # noqa: C901
    """应用一条 Command；返回新 Run + 按 seq 有序的可持久事件。

    确定性（#160）：reduce 是 ``(run, command, now)`` 的纯函数——自身不读墙上时钟、不产随机 id。
    时间戳取入参 ``now``（缺省回落 :func:`utc_now` 供生产；重放/测试注入固定 ``now`` 即逐字节可复现），
    tool_result 消息 id 由 ``tool_call_id`` 确定性派生（不再 uuid4）。同一输入序列 → 同一输出状态。
    """
    ts = now if now is not None else utc_now()
    if run.status.is_terminal:
        # C13 first-writer-wins：终态后冻结，忽略后续写。
        msg = f"run {run.run_id} already {run.status}; ignored {command.type}"
        return _reject(run, msg)

    if isinstance(command, RecordWarning):
        # 内核 out-of-band 告警的唯一 seq 分配入口（C2）：占一个 durable seq、不改状态。
        seq = run.seq + 1
        return replace(run, seq=seq), [_event(seq, run, command.turn, EventType.WARNING, {"message": command.message})]

    if isinstance(command, SubmitMessage):
        was_idle = run.status is RunStatus.IDLE
        ctx = replace(run.context, items=(*run.context.items, command.content))
        if was_idle:
            # 首条消息的 durable 事实 = ``run_started``（既有冻结契约：idle 提交恰产 [run_started] 且 seq==1，
            # 见 test_reduce.py:51 / test_transition_chokepoint.py:45）；正文由 turn 边界快照承载。
            new = replace(run, context=ctx, status=RunStatus.RUNNING)
            seq = new.seq + 1
            # run_started additive 带 policy_ref（P9/ADR-0045）：None 则不发该键（optional，不破旧消费者）。
            started_data: dict[str, object] = {"run_id": new.run_id}
            if new.policy_ref is not None:
                started_data["policy_ref"] = {"id": new.policy_ref.id, "fingerprint": new.policy_ref.fingerprint}
            new = replace(new, seq=seq)
            return new, [_event(seq, new, None, EventType.RUN_STARTED, started_data)]
        # 非 idle（busy / awaiting_approval / cancelled 外的活态）：用户输入同样进事实流——
        # 有界正文 + bump seq。旧实现只追加内存 context、无事件且不 bump seq（不对称），崩溃后该输入
        # 不在事实流、``after_seq`` 重放看不到（T1 第①件要修的根）。
        text = "".join(b.text or "" for b in command.content.content if b.type == "text")
        bounded, truncated = _bounded_user_text(text)
        seq = run.seq + 1
        new = replace(run, context=ctx, seq=seq)
        return new, [_event(seq, new, run.turn, EventType.USER_MESSAGE, {"text": bounded, "truncated": truncated})]

    if isinstance(command, AdvanceTurn):
        new = replace(run, turn=command.turn, seq=run.seq + 1)
        return new, [_event(new.seq, new, command.turn, EventType.TURN_STARTED, {"turn": command.turn})]

    if isinstance(command, AppendAssistantMessage):
        use_ids = [b.tool_use_id for b in command.message.content if b.type == "tool_use" and b.tool_use_id]
        known = {c.tool_call_id for c in run.tool_ledger.calls}
        if any(i in known for i in use_ids):
            return _reject(run, "duplicate tool_use id; command rejected")
        new_calls = tuple(
            ToolCall(
                tool_call_id=b.tool_use_id,
                turn=command.turn,
                name=b.name or "",
                args=dict(b.input or {}),
                args_status=b.args_status,
                raw_args_summary=b.raw_input,
                permission_reason=b.args_error,
                status=ToolCallStatus.PENDING,
            )
            for b in command.message.content
            if b.type == "tool_use" and b.tool_use_id
        )
        ledger = replace(run.tool_ledger, calls=(*run.tool_ledger.calls, *new_calls))
        ctx = replace(run.context, items=(*run.context.items, command.message))
        new = replace(run, context=ctx, tool_ledger=ledger, seq=run.seq + 1)
        return new, [_event(new.seq, new, command.turn, EventType.MESSAGE_COMPLETED, _message_completed_data(command.message))]

    if isinstance(command, RecordToolResult):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            return _reject(run, f"no open tool_call {command.tool_call_id}; rejected")
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, replace(target, status=_call_status(command.status), result=command.result, display=command.display)))
        ctx = _append_tool_result(run.context, command.tool_call_id, command.result, is_error=command.status != "success", now=ts)
        new = replace(run, tool_ledger=ledger, context=ctx, seq=run.seq + 1)
        return new, [_event(new.seq, new, target.turn, EventType.TOOL_COMPLETED, _tool_completed_data(command.tool_call_id, command.status, result=command.result, display=command.display))]

    if isinstance(command, MarkToolValidated):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            # 已 validated/闭合的重复 transition 是幂等 no-op；未知 id 同样不产 durable event，
            # 避免把内部 lifecycle 噪声污染 replay。
            return run, []
        if target.status is ToolCallStatus.VALIDATED:
            return run, []
        validated = replace(target, status=ToolCallStatus.VALIDATED)
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, validated))
        return replace(run, tool_ledger=ledger), []

    if isinstance(command, MarkToolDenied):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            return _reject(run, f"no open tool_call to deny {command.tool_call_id}")
        denied = replace(target, status=ToolCallStatus.DENIED, permission_decision="deny", result=command.reason)
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, denied))
        ctx = _append_tool_result(run.context, command.tool_call_id, f"denied: {command.reason}", is_error=True, now=ts)
        new = replace(run, tool_ledger=ledger, context=ctx, seq=run.seq + 1)
        return new, [_event(new.seq, new, target.turn, EventType.TOOL_COMPLETED, _tool_completed_data(command.tool_call_id, "denied", result=command.reason, display=None))]

    if isinstance(command, RequestApproval):
        target = _open_call(run, command.tool_call_id)
        existing = next((a for a in run.permission_ctx.approvals if a.request_id == command.request_id), None)
        if existing is not None:
            if existing.status is ApprovalStatus.PENDING and existing.tool_call_id == command.tool_call_id:
                return run, []
            return _reject(run, f"approval request {command.request_id} conflicts with an existing request")
        if target is None:
            return _reject(run, f"no open tool_call to approve {command.tool_call_id}")
        requested = replace(
            target,
            status=ToolCallStatus.AWAITING_APPROVAL,
            approval_request_id=command.request_id,
            permission_reason=command.reason,
        )
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, requested))
        request = ApprovalRequest(
            request_id=command.request_id,
            tool_call_id=command.tool_call_id,
            args_summary=command.args_summary,
            risk=command.risk,
            reason=command.reason,
            created_at=ts,
            expires_at=command.expires_at,
        )
        permissions = replace(run.permission_ctx, approvals=(*run.permission_ctx.approvals, request))
        new = replace(run, tool_ledger=ledger, permission_ctx=permissions, status=RunStatus.AWAITING_APPROVAL, seq=run.seq + 1)
        event_data = {
            "request_id": request.request_id,
            "tool_call_id": command.tool_call_id,
            "name": target.name,
            "args_summary": command.args_summary,
            "risk": command.risk,
            "reason": command.reason,
            "expires_at": command.expires_at.isoformat(),
        }
        return new, [_event(new.seq, new, target.turn, EventType.APPROVAL_REQUEST, event_data)]

    if isinstance(command, ResolveApproval):
        return _resolve_approval(run, command, decision=command.decision, decided_by=command.decided_by, status=ApprovalStatus.APPROVED if command.decision == "allow" else ApprovalStatus.DENIED, expired=False, now=ts)

    if isinstance(command, ExpireApproval):
        return _resolve_approval(run, command, decision="deny", decided_by="timeout", status=ApprovalStatus.EXPIRED, expired=True, now=ts)

    if isinstance(command, SetPermissionMode):
        # 合法 mode 集合的唯一 Python 真源在 L0 ``contracts.profile``（wire 真源仍是
        # ``protocol/event.schema.json``）；此处不再写第二份字面集（OPT-3 c4）。
        if command.mode not in PERMISSION_MODE_SET:
            return _reject(run, f"invalid permission mode {command.mode}")
        if run.permission_ctx.mode == command.mode:
            return run, []
        permissions = replace(run.permission_ctx, mode=command.mode)
        new = replace(run, permission_ctx=permissions, seq=run.seq + 1)
        return new, [_event(new.seq, new, run.turn, EventType.PERMISSION_MODE_CHANGED, {"mode": command.mode, "changed_by": command.changed_by, "effective_from_turn": run.turn + 1})]

    if isinstance(command, MarkToolRunning):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            return _reject(run, f"no open tool_call to start {command.tool_call_id}")
        if target.status is ToolCallStatus.RUNNING:
            return run, []
        started = replace(
            target,
            status=ToolCallStatus.RUNNING,
            capability=command.capability,
            risk=command.risk,
            timeout_s=command.timeout_s,
            started_at=ts,
        )
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, started))
        new = replace(run, tool_ledger=ledger, status=RunStatus.RUNNING, seq=run.seq + 1)
        return new, [_event(new.seq, new, target.turn, EventType.TOOL_STARTED, {
            "tool_call_id": command.tool_call_id,
            "name": target.name,
            "capability": command.capability,
            "risk": command.risk,
            "args_summary": target.raw_args_summary or target.name,
        })]

    if isinstance(command, WriteMemory):
        # 记忆写：reduce 是纯状态机、不碰 IO（落库由 kernel 在消费点经注入 MemoryStorePort 完成）。
        # ① 载荷有界校验（C18，超限 fail-closed 拒）；② 占一个 durable seq（design/02 §10）；
        # ③ 发内部 memory_written 回执（有界 kind/chunk_count/source，**无原文**，DoD⑤）。
        # 记忆正文绝不进 Domain_State（DoD⑤；至多由检索侧经白名单回注有界投影）。
        payload = command.payload
        if len(payload.text.encode("utf-8")) > _MAX_MEMORY_WRITE_BYTES:
            return _reject(run, "memory write exceeds bound; rejected")
        new = replace(run, seq=run.seq + 1)
        return new, [
            _event(new.seq, new, run.turn, EventType.MEMORY_WRITTEN, {"kind": payload.kind.value, "chunk_count": 1, "source": source_for_write(payload.kind).value})
        ]

    if isinstance(command, CompactContext):
        # P10/ADR-0048：压缩应用——reduce **纯校验 + 纯应用**（对抗评审 MAJ-8）：摘要/锚/floor 均
        # 由 loop 侧算好随命令携带，reduce 绝不计算摘要/哈希。三道 fail-closed：
        #   ① summary 非空；② evict 边界 ≤ closed_prefix（C19 绝不孤儿化未闭合 tool_use）；
        #   ③ 新锚必须非空（可恢复锚生产者，ADR-0024）。非法则拒 + 发 warning、状态不变。
        items = run.context.items
        cut = closed_prefix(items)
        if not command.summary_text.strip():
            return _reject(run, "compaction requires non-empty summary; rejected")
        if not (0 <= command.evict_start <= command.evict_end <= min(cut, len(items))):
            return _reject(run, "compaction range crosses an open tool_use; rejected")
        if not command.new_pointers:
            return _reject(run, "compaction requires a fail-closed recovery anchor; rejected")
        new_items = items[: command.evict_start] + items[command.evict_end :]
        ctx = replace(
            run.context,
            items=new_items,
            summary=command.summary_text,
            compaction_floor=command.new_floor,
            recovery_pointers=(*run.context.recovery_pointers, *command.new_pointers),
        )
        # 为本次两条事件连续取号（不复用同一 seq，ADR-0011）；baseline_seq = compact_applied 的 seq。
        seq = run.seq
        seq += 1
        started = _event(seq, run, run.turn, EventType.COMPACT_STARTED, {"reason": "kernel_token_pressure"})
        seq += 1
        covered_from = command.new_pointers[0].seq_from
        covered_to = command.new_pointers[-1].seq_to
        applied = _event(
            seq,
            run,
            run.turn,
            EventType.COMPACT_APPLIED,
            {"baseline_seq": seq, "covered_from": covered_from, "covered_to": covered_to, "summary_bytes": len(command.summary_text.encode("utf-8"))},
        )
        new = replace(run, context=ctx, seq=seq)
        return new, [started, applied]

    if isinstance(command, Cancel):
        open_calls = _open_calls(run)
        closed, extra = _backfill_open_calls(run, now=ts)
        ledger = replace(run.tool_ledger, calls=closed)
        ctx = replace(run.context, items=extra)
        permissions = _cancel_pending_approvals(run.permission_ctx, ts)
        # 为本次产出的全部事件（回填 + 唯一终态）连续取号，再把 Run.seq 推进到最后一个号——
        # 绝不复用同一 seq（ADR-0011；旧写法 run.seq+1 与 new.seq 相撞会打断 store.append）。
        seq = run.seq
        events: list[Envelope] = []
        for call in open_calls:
            seq += 1
            events.append(_event(seq, run, None, EventType.TOOL_COMPLETED, {"tool_call_id": call.tool_call_id, "status": "cancelled"}))
        seq += 1
        events.append(_event(seq, run, run.turn, EventType.RUN_CANCELLED, {"reason": str(command.reason)}))
        new = replace(run, tool_ledger=ledger, context=ctx, permission_ctx=permissions, status=RunStatus.CANCELLED, cancel_reason=command.reason, completed_at=ts, seq=seq)
        return new, events

    if isinstance(command, FinalizeRun):
        # 任何终态都必须先闭合还开着的 tool_use（C7/I1）。failed 分支以前直接落终态，
        # 把未配对的 tool_use 留在 context；P3 做 resume/after_seq 续传时会被原样喂回 provider
        # （Anthropic/OpenAI 强制 tool_use↔tool_result 成对，直接 4xx），所以在这一步就补上。
        open_calls = _open_calls(run)
        closed, extra_messages = _backfill_open_calls(run, note=f"run finished as {command.status} before this call completed", now=ts)
        ledger = replace(run.tool_ledger, calls=closed)
        items = (*run.context.items, *extra_messages)
        seq = run.seq
        events: list[Envelope] = []
        for call in open_calls:
            seq += 1
            events.append(_event(seq, run, None, EventType.TOOL_COMPLETED, {"tool_call_id": call.tool_call_id, "status": "cancelled"}))
        if command.status == "failed":
            stack = (*run.error_stack, command.error) if command.error else run.error_stack
            err = {"code": command.error.kind.value, "message": command.error.message, "retryable": command.error.hints.retryable} if command.error else {}
            seq += 1
            events.append(_event(seq, run, run.turn, EventType.RUN_FAILED, {"error": err}))
            new = replace(
                run,
                tool_ledger=ledger,
                context=replace(run.context, items=items),
                status=RunStatus.FAILED,
                error_stack=stack,
                completed_at=ts,
                seq=seq,
            )
            return new, events
        if command.final is not None:
            items = (*items, command.final)
        seq += 1
        events.append(_event(seq, run, run.turn, EventType.RUN_COMPLETED, {"usage": command.usage or {}, "exit_reason": command.exit_reason}))
        new = replace(
            run,
            tool_ledger=ledger,
            context=replace(run.context, items=items),
            status=RunStatus.COMPLETED,
            completed_at=ts,
            seq=seq,
        )
        return new, events

    if isinstance(command, UpdateTaskTree):
        # 首次让 reduce 处理 task_tree：写入前跑 DAG 校验（I1）；非法 → 拒 + 出声、**不改树**。
        by_id = {n.id: n for n in run.task_tree.nodes}
        for node in command.upsert:
            by_id[node.id] = node
        for nid in command.remove_ids:
            by_id.pop(nid, None)
        candidate = tuple(by_id.values())  # 插入序：现有节点在前、新节点追加，回放确定。
        problems = validate_task_tree(candidate)
        if problems:
            msg = "task tree rejected: " + "; ".join(problems)
            return _reject(run, msg)
        seq = run.seq
        events: list[Envelope] = []
        for node in command.upsert:
            seq += 1
            events.append(_event(seq, run, run.turn, EventType.NODE_UPDATED, _node_event_data(node)))
        return replace(run, task_tree=TaskTree(nodes=candidate), seq=seq), events

    if isinstance(command, SpawnSubagent):
        # 父侧记账：绑 assigned_run_id + 置 active + 发 peer_started。reduce **不创建子 run**（IO 在 loop 消费点）。
        node = next((n for n in run.task_tree.nodes if n.id == command.node_id), None)
        if node is None:
            return _reject(run, f"spawn: unknown node {command.node_id}")
        if node.assigned_run_id == command.child_run_id:
            return run, []  # 幂等：同 child 再报 = no-op
        if node.assigned_run_id is not None:
            return _reject(run, f"spawn: node {command.node_id} already bound to {node.assigned_run_id}")
        bound = replace(node, kind=TaskKind.SUBAGENT, assigned_run_id=command.child_run_id, status=TaskStatus.ACTIVE)
        tree = replace(run.task_tree, nodes=_replace_node(run.task_tree.nodes, bound))
        seq = run.seq
        events = [_event(seq + 1, run, run.turn, EventType.PEER_STARTED, {"parent_run_id": run.run_id, "child_run_id": command.child_run_id, "node_id": command.node_id})]
        events.append(_event(seq + 2, run, run.turn, EventType.NODE_UPDATED, _node_event_data(bound)))
        return replace(run, task_tree=tree, seq=seq + 2), events

    if isinstance(command, ReportChildTerminal):
        # 子终态回父（经父 inbox，非直写）：回填 node 终态 + 发 peer_ended。已终态 → 幂等 no-op（不被迟到翻案）。
        node = next((n for n in run.task_tree.nodes if n.id == command.node_id), None)
        if node is None:
            return _reject(run, f"report: unknown node {command.node_id}")
        if node.assigned_run_id != command.child_run_id:
            return _reject(run, f"report: child_run_id mismatch for node {command.node_id}")
        if node.status in _TERMINAL_NODE_STATUSES:
            return run, []
        mapped = {"completed": TaskStatus.DONE, "failed": TaskStatus.FAILED, "cancelled": TaskStatus.CANCELLED}[command.terminal_status]
        settled = replace(node, status=mapped)
        tree = replace(run.task_tree, nodes=_replace_node(run.task_tree.nodes, settled))
        seq = run.seq
        events = [_event(seq + 1, run, run.turn, EventType.PEER_ENDED, {
            "parent_run_id": run.run_id,
            "child_run_id": command.child_run_id,
            "node_id": command.node_id,
            "terminal_status": command.terminal_status,
            "result_ref": command.result_ref,
            "resumable_hint": command.resumable_hint,
        })]
        events.append(_event(seq + 2, run, run.turn, EventType.NODE_UPDATED, _node_event_data(settled)))
        return replace(run, task_tree=tree, seq=seq + 2), events

    # 未处理的 Command → 以 warning 拒绝（绝不崩循环，design/04 L1）。
    return _reject(run, f"unsupported command {command.type}")


def _cancel_pending_approvals(ctx: PermissionCtx, now: datetime) -> PermissionCtx:
    return replace(
        ctx,
        approvals=tuple(
            replace(a, status=ApprovalStatus.CANCELLED, decision="deny", decided_by="cancel", resolved_at=now) if a.status is ApprovalStatus.PENDING else a
            for a in ctx.approvals
        ),
    )


def _resolve_approval(
    run: Run,
    command: object,
    *,
    decision: str,
    decided_by: str,
    status: ApprovalStatus,
    expired: bool,
    now: datetime,
) -> tuple[Run, list[Envelope]]:
    request_id = command.request_id
    tool_call_id = getattr(command, "tool_call_id", None)
    approval = next((item for item in run.permission_ctx.approvals if item.request_id == request_id), None)
    if approval is None or (tool_call_id is not None and approval.tool_call_id != tool_call_id):
        return _reject(run, f"unknown approval request {request_id}")
    if approval.status is not ApprovalStatus.PENDING:
        if approval.decision == decision:
            return run, []
        return _reject(run, f"approval {request_id} already {approval.status.value}")
    target = _open_call(run, approval.tool_call_id)
    if target is None:
        return _reject(run, f"approval {request_id} has no open tool_call")
    resolved = replace(approval, status=status, decision=decision, decided_by=decided_by, resolved_at=now)
    permissions = replace(
        run.permission_ctx,
        approvals=tuple(resolved if a.request_id == request_id else a for a in run.permission_ctx.approvals),
        decisions=(*run.permission_ctx.decisions, PermissionDecisionRecord(tool_call_id=target.tool_call_id, decision=decision, decided_by=decided_by, at=now, request_id=request_id)),
    )
    if decision == "allow":
        call = replace(target, status=ToolCallStatus.READY, permission_decision="allow", permission_reason=approval.reason, permission_decided_by=decided_by)
        ctx = run.context
        run_status = RunStatus.RUNNING
    else:
        reason = "approval expired before a decision" if expired else f"approval denied: {approval.reason}"
        call = replace(target, status=ToolCallStatus.DENIED, permission_decision="deny", permission_reason=reason, permission_decided_by=decided_by, result=reason, ended_at=now)
        ctx = _append_tool_result(run.context, target.tool_call_id, reason, is_error=True, now=now)
        run_status = RunStatus.RUNNING
    ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, call))
    seq = run.seq
    events: list[Envelope] = []
    seq += 1
    events.append(_event(seq, run, target.turn, EventType.APPROVAL_RESOLVED, {
        "request_id": request_id,
        "tool_call_id": target.tool_call_id,
        "decision": decision,
        "decided_by": decided_by,
        "resolved_at": now.isoformat(),
    }))
    if decision != "allow":
        seq += 1
        events.append(_event(seq, run, target.turn, EventType.TOOL_COMPLETED, {"tool_call_id": target.tool_call_id, "status": "denied"}))
    return replace(run, tool_ledger=ledger, context=ctx, permission_ctx=permissions, status=run_status, seq=seq), events


def _open_calls(run: Run) -> tuple[ToolCall, ...]:
    """返回仍打开（pending/running）的调用。"""
    return tuple(c for c in run.tool_ledger.calls if c.status in _OPEN_CALL)


def _open_call(run: Run, tool_call_id: str) -> ToolCall | None:
    """按 id 找一个仍打开的调用；找不到（已闭合/不存在）返回 None。"""
    return next((c for c in _open_calls(run) if c.tool_call_id == tool_call_id), None)


def _call_status(status: str) -> ToolCallStatus:
    """把工具返回的字符串状态映射为账本枚举；未知一律按 error（fail-closed）。"""
    mapping = {
        "success": ToolCallStatus.SUCCESS,
        "error": ToolCallStatus.ERROR,
        "critical_error": ToolCallStatus.CRITICAL_ERROR,
        "timed_out": ToolCallStatus.TIMED_OUT,
        "cancelled": ToolCallStatus.CANCELLED,
    }
    return mapping.get(status, ToolCallStatus.ERROR)


def _replace_call(calls: tuple[ToolCall, ...], updated: ToolCall) -> tuple[ToolCall, ...]:
    """不可变替换：返回把匹配 id 的那条换成 ``updated`` 的新元组。"""
    return tuple(updated if c.tool_call_id == updated.tool_call_id else c for c in calls)


def _replace_node(nodes: tuple[TaskNode, ...], updated: TaskNode) -> tuple[TaskNode, ...]:
    """任务树不可变替换（同 ``_replace_call``）；匹配 id 换成 ``updated``。"""
    return tuple(updated if n.id == updated.id else n for n in nodes)


def _node_event_data(node: TaskNode) -> dict[str, object]:
    """``node_updated`` 的**有界**白名单载荷（{node_id,status,title,parent_id}）。

    绝不含 ``objective``/``result``/``deps``/``assigned_run_id``（C18/C20；ADR-0035/0042）——富节点走只读端点拉快照。
    """
    return {
        "node_id": node.id,
        "status": node.status.value,
        "title": node.title,
        "parent_id": node.parent_id,
    }


def _append_tool_result(ctx: Context, tool_call_id: str, result: object, *, is_error: bool, now: datetime) -> Context:
    """追加一条含 tool_result 的消息，维持 tool_use↔tool_result 配对（I1）。

    进模型的文本有界（#158）：旧实现 ``str(result)`` 无上限，巨型结果会原样进下一轮 provider 请求。
    消息 id 由 tool_call_id 确定性派生、created_at 取传入 ``now``（#160：不再 uuid4/墙上时钟）。"""
    text = str(result)
    if len(text) > _MAX_MODEL_TOOL_RESULT_CHARS:
        text = text[:_MAX_MODEL_TOOL_RESULT_CHARS] + f"\n…[tool_result truncated from {len(text)} chars]"
    block = ContentBlock(type="tool_result", tool_use_id=tool_call_id, text=text, is_error=is_error)
    msg = Message(id=f"toolresult:{tool_call_id}", role=Role.TOOL, content=(block,), seq=len(ctx.items), created_at=now)
    return replace(ctx, items=(*ctx.items, msg))


def _backfill_open_calls(run: Run, *, note: str = "cancelled before completion", now: datetime) -> tuple[tuple[ToolCall, ...], tuple[Message, ...]]:
    """C7：用 cancelled 结果闭合每一个未完成的调用，保住配对不变式。

    取消不是普通工具 error：账本必须保留可区分事实，resume/审计才能判断进程被用户停止
    而非业务失败（ADR-0016）。`note` 区分两种成因：用户取消 vs 落终态时尚未完成；
    两者都是 cancelled 状态，但后者额外带运行终态说明，供回放与审计区分。
    """
    open_ids = {c.tool_call_id for c in _open_calls(run)}
    closed = tuple(
        replace(c, status=ToolCallStatus.CANCELLED, result=note)
        if c.tool_call_id in open_ids
        else c
        for c in run.tool_ledger.calls
    )
    extra = tuple(
        Message(
            id=f"toolresult:{c.tool_call_id}",
            role=Role.TOOL,
            content=(ContentBlock(type="tool_result", tool_use_id=c.tool_call_id, text=note, is_error=True),),
            seq=len(run.context.items) + i,
            created_at=now,
        )
        for i, c in enumerate(_open_calls(run))
    )
    return closed, extra
