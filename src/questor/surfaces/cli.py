"""L6 CLI surface — the P1 DoD main stage (design/02 §4; STRUCTURE S6).

Zero business logic: it *wires* the injected ports and turns them into a
terminal that asks a line, streams the answer, and can be cancelled. All state
changes still flow through the loop -> ``reduce`` (C2). Provider is chosen by
configuration: ``EchoProvider`` for an offline demo (no key), ``LiteLLMProvider``
for a real model (BYOM).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import JsonObject, new_id
from questor.contracts.events import EventType
from questor.contracts.ports import ProviderPort
from questor.contracts.state_schema import Budget
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.observability.logging import configure_logging, log_event
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import EchoProvider
from questor.providers.litellm_adapter import LiteLLMProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run


async def terminal_approver(name: str, arguments: JsonObject, reason: str) -> bool:
    """Resolve an ``ask`` on the terminal (adapted from DeepCode ``harness/approval.py``)."""
    if not sys_stdin_tty():
        return False  # non-interactive -> fail-closed
    print(f"\n[approval] {name}({arguments}) — {reason}")
    answer = await asyncio.to_thread(input, "allow? [y/n]: ")
    return answer.strip().lower() in {"y", "yes"}


def sys_stdin_tty() -> bool:
    import sys

    return sys.stdin.isatty()


def provider_from_env() -> ProviderPort:
    model = os.environ.get("QUESTOR_MODEL")
    if model and os.environ.get("LITELLM_API_KEY"):
        return LiteLLMProvider(model)
    return EchoProvider()


class CliSurface:
    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        provider: ProviderPort | None = None,
        system: str | None = None,
        model: str = "echo",
    ) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.provider = provider or provider_from_env()
        self.system = system
        self.model = model
        self.read = ReadTool()
        self.registry = {self.read.spec.name: self.read}

    def _loop(self, bus: InProcessEventBus, cancel: asyncio.Event) -> DefaultTurnLoop:
        return DefaultTurnLoop(
            provider=self.provider,
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(read_only_tools=frozenset(self.registry)),
            bus=bus,
            tool_for=self.registry.get,
            tools=tuple(self.registry.values()),
            workspace_root=self.workspace_root,
            model=self.model,
            system=self.system,
            approver=terminal_approver,
            cancel_event=cancel,
        )

    async def run_once(self, text: str, *, on_delta=None) -> Run:
        """Run one user turn to a terminal event, streaming deltas as they arrive."""
        store = await SQLiteStore(":memory:").connect()
        bus = InProcessEventBus(store)
        cancel = asyncio.Event()
        loop = self._loop(bus, cancel)
        run = Run(run_id=new_id("run"), budget=Budget())
        printer = asyncio.create_task(self._stream(bus, run.run_id, on_delta))
        final = await loop.drive(run, text)
        await printer
        await store.close()
        return final

    async def _stream(self, bus: InProcessEventBus, run_id: str, on_delta) -> None:
        async for env in bus.subscribe(run_id, 0):
            log_event(env)
            if env.type == EventType.TEXT_DELTA:
                piece = env.data.get("delta", "")
                if on_delta is not None:
                    on_delta(piece)
                else:
                    print(piece, end="", flush=True)
            if env.type in {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}:
                print()
                return


async def interactive() -> int:
    """REPL loop: type a line, stream the answer; Ctrl-C cancels the current run."""
    configure_logging()
    surface = CliSurface()
    print("questor P1 CLI — type a message (Ctrl-D to exit).")
    while True:
        try:
            text = await asyncio.to_thread(input, "\n> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text.strip():
            continue
        await surface.run_once(text)
    return 0


def main() -> int:
    try:
        return asyncio.run(interactive())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
