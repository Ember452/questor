"""#162B：provider 错误回显的 prompt 明文必须在源头被剥离。

provider 4xx 常把请求体（含用户 prompt）整段回显进异常文本；旧实现只在 redact 里按凭据 pattern
脱敏，`strip_prompt_echo` 未接线 → 非凭据的 prompt 散文随 run_failed 进事件/快照/主干日志。
现在 loop 的 provider 异常归一点按本轮 prompt 基准剥回显。
"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.common import new_id
from questor.contracts.state_schema import Budget, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.state.domain_state import Run

_MARKER = "USER_SECRET_PROMPT_MARKER_do_not_leak_into_logs"


class _EchoRaiseProvider:
    """stream 直接抛一个回显了请求体的 provider 4xx（模拟网关把请求体塞进错误消息）。"""

    def __init__(self, echo: str) -> None:
        self._echo = echo

    async def stream(self, request):  # -> AsyncIterator[StreamChunk]
        if False:  # pragma: no cover - 使其成为 async generator
            yield None
        raise RuntimeError(f"litellm.BadRequestError: 400 body={self._echo}")


async def test_provider_error_echo_is_stripped_from_run_failed(tmp_path: Path) -> None:
    loop = DefaultTurnLoop(
        provider=_EchoRaiseProvider(_MARKER),  # type: ignore[arg-type]
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(None),
        tool_for=lambda name: None,
        tools=(),
        workspace_root=tmp_path,
        model="m",
    )
    final = await loop.drive(Run(run_id=new_id("run"), budget=Budget(max_turns=2)), _MARKER)

    assert final.status is RunStatus.FAILED
    message = final.error_stack[-1].message
    assert _MARKER not in message, f"prompt 明文未被剥离，仍进 run_failed（#162B）：{message!r}"
    assert "<prompt>" in message, f"应出现回显占位符：{message!r}"
