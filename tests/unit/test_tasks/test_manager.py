"""Tests for background task management."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from questorharness.contracts.task import TaskRecord
from questorharness.runtime.tasks.task_manager import BackgroundTaskManager, _encode_task_worker_payload


@pytest.mark.asyncio
async def test_completed_task_restarts_even_when_stale_process_is_still_mapped(tmp_path: Path) -> None:
    """A finished task must restart on write, even before the OS reaps it.

    Regression for a CI-only flake: sending a message to a completed agent wrote
    into the dying process's stdin instead of restarting it, so the payload was
    lost and the follow-up output never appeared.
    """
    manager = BackgroundTaskManager()
    task = TaskRecord(
        id="agent-1",
        type="local_agent",
        status="completed",
        description="echo agent",
        cwd=str(tmp_path),
        output_file=tmp_path / "agent-1.log",
        command="python -c pass",
    )
    manager._tasks[task.id] = task
    manager._output_locks[task.id] = asyncio.Lock()
    manager._input_locks[task.id] = asyncio.Lock()

    class _StaleProcess:
        stdin = object()  # writable handle still present
        returncode = None  # not reaped yet, but the task already finished

    manager._processes[task.id] = _StaleProcess()  # type: ignore[assignment]

    restarted: list[str] = []

    async def _fake_restart(record: TaskRecord):
        restarted.append(record.id)
        return _StaleProcess()

    manager._restart_agent_task = _fake_restart  # type: ignore[method-assign]

    await manager._ensure_writable_process(task)

    assert restarted == [task.id]


class _FakeStdout:
    """Yields one chunk then EOF, like a single-shot agent's stdout pipe."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)

    async def read(self, _size: int = -1) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class _FakeStdin:
    def __init__(self, *, closing: bool = False) -> None:
        self.closing = closing
        self.written: list[bytes] = []

    def write(self, payload: bytes) -> None:
        self.written.append(payload)

    async def drain(self) -> None:
        return None

    def is_closing(self) -> bool:
        return self.closing


class _FakeLiveProcess:
    """Looks fully alive: mapped, stdin present, not reaped, status running."""

    def __init__(self, stdout=None, stdin=None) -> None:
        self.stdout = stdout
        self.stdin = stdin
        self.returncode = None


@pytest.mark.asyncio
async def test_stdout_eof_makes_a_running_task_unwritable_even_before_the_waiter_records_it(tmp_path: Path) -> None:
    """stdout EOF ⇒ 该任务永远不会再产出 ⇒ 必须重启,不再等 waiter 记账。

    回归自 CI-only flake(2026-10-24 第二次):单发代理打印后退出,输出文件
    由 ``_copy_output`` 并发落盘,**先于** waiter 把 status/returncode 记成
    终态。决策方三项检查全"活着"就复用了垂死进程,消息写进管道静默丢失。
    终态记账在负载下可以滞后任意久,所以"输出通道已关"必须自成判据。
    """
    manager = BackgroundTaskManager()
    task = TaskRecord(
        id="agent-eof",
        type="local_agent",
        status="running",
        description="echo agent",
        cwd=str(tmp_path),
        output_file=tmp_path / "agent-eof.log",
        command="python -c pass",
    )
    manager._tasks[task.id] = task
    manager._output_locks[task.id] = asyncio.Lock()
    manager._input_locks[task.id] = asyncio.Lock()
    process = _FakeLiveProcess(stdout=_FakeStdout(b"AGENT_ECHO:ready\n"))
    manager._processes[task.id] = process  # type: ignore[assignment]

    await manager._copy_output(task.id, process)  # type: ignore[arg-type]

    assert task.output_file.read_text(encoding="utf-8") == "AGENT_ECHO:ready\n"
    assert manager._stdout_eof == {task.id}, "EOF must be recorded by the copy task itself"

    restarted: list[str] = []

    async def _fake_restart(record: TaskRecord):
        restarted.append(record.id)
        return _FakeLiveProcess(stdin=_FakeStdin())

    manager._restart_agent_task = _fake_restart  # type: ignore[method-assign]

    await manager._ensure_writable_process(task)

    assert restarted == [task.id], "a task whose stdout closed must restart, not reuse"


@pytest.mark.asyncio
async def test_write_treats_a_transport_that_closes_mid_write_as_undelivered(tmp_path: Path) -> None:
    """drain 成功 ≠ 投递成功:传输层在写中途关闭时数据被静默丢弃。

    Windows proactor 上,写缓冲尚未刷出、waiter 的收尾关闭了 stdin,这一刀
    既不抛管道异常也不报错——payload 就此消失。写完必须复核传输层状态,
    未证实投递就重启重写一次。
    """
    manager = BackgroundTaskManager()
    task = TaskRecord(
        id="agent-mid",
        type="local_agent",
        status="running",
        description="echo agent",
        cwd=str(tmp_path),
        output_file=tmp_path / "agent-mid.log",
        command="python -c pass",
    )
    manager._tasks[task.id] = task
    manager._output_locks[task.id] = asyncio.Lock()
    manager._input_locks[task.id] = asyncio.Lock()
    dying_stdin = _FakeStdin(closing=True)
    dying = _FakeLiveProcess(stdin=dying_stdin)
    fresh_stdin = _FakeStdin()
    manager._processes[task.id] = dying  # type: ignore[assignment]

    async def _fake_ensure(record: TaskRecord):
        return manager._processes[record.id]  # type: ignore[return-value]

    async def _fake_restart(record: TaskRecord):
        replacement = _FakeLiveProcess(stdin=fresh_stdin)
        manager._processes[record.id] = replacement  # type: ignore[assignment]
        return replacement

    manager._ensure_writable_process = _fake_ensure  # type: ignore[method-assign]
    manager._restart_agent_task = _fake_restart  # type: ignore[method-assign]

    await manager.write_to_task(task.id, "agent ping")

    assert fresh_stdin.written, "mid-write close must fall through to a restart and rewrite"


@pytest.mark.asyncio
async def test_create_shell_task_and_read_output(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="printf 'hello task'",
        description="hello",
        cwd=tmp_path,
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "completed"
    assert "hello task" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_create_agent_task_with_command_override_and_write(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="first",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    assert "got:first" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_create_agent_task_preserves_multiline_prompt(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="line 1\nline 2\nline 3",
        description="agent",
        cwd=tmp_path,
        command=(
            "python -u -c \"import sys, json; "
            "print(json.loads(sys.stdin.readline())['text'].replace(chr(10), '|'))\""
        ),
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    assert "line 1|line 2|line 3" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_write_to_stopped_agent_task_restarts_process(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="ready",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    await manager.write_to_task(task.id, "follow-up")
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    output = manager.read_task_output(task.id)
    assert "got:ready" in output
    assert "[QuestorHarness] Agent task restarted; prior interactive context was not preserved." in output
    assert "got:follow-up" in output
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.metadata["restart_count"] == "1"
    assert updated.metadata["status_note"] == "Task restarted; prior interactive context was not preserved."


@pytest.mark.asyncio
async def test_create_shell_task_stores_env_on_record(tmp_path: Path, monkeypatch):
    """``env=`` passed to ``create_shell_task`` must land on the
    ``TaskRecord.env`` field so ``_start_process`` can forward it to the
    subprocess. Plumbing this dict instead of baking ``KEY=val`` into the
    command string is the fix for #230."""
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="printf 'noop'",
        description="env test",
        cwd=tmp_path,
        env={"MY_OH_TEST_VAR": "hello-230"},
    )
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    stored = manager.get_task(task.id)
    assert stored is not None
    assert stored.env == {"MY_OH_TEST_VAR": "hello-230"}


@pytest.mark.asyncio
async def test_create_shell_task_argv_path_bypasses_shell(tmp_path: Path, monkeypatch):
    """The argv path runs the executable directly via
    ``asyncio.create_subprocess_exec(*argv)`` with no shell. This is the
    fix for #230: bash on Windows cannot exec Windows-pathed binaries
    when launched via ``create_subprocess_exec``, so teammate spawn must
    not route through a shell."""
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    import sys
    task = await manager.create_shell_task(
        argv=[sys.executable, "-c", "print('argv-route-ok')"],
        description="argv direct exec",
        cwd=tmp_path,
    )
    await asyncio.wait_for(manager._waiters[task.id], timeout=10)  # type: ignore[attr-defined]

    output = manager.read_task_output(task.id)
    assert "argv-route-ok" in output
    stored = manager.get_task(task.id)
    assert stored is not None
    assert stored.argv is not None
    assert stored.command is None


@pytest.mark.asyncio
async def test_create_shell_task_rejects_both_command_and_argv(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    with pytest.raises(ValueError, match="only one"):
        await manager.create_shell_task(
            command="printf hi",
            argv=["echo", "hi"],
            description="both",
            cwd=tmp_path,
        )


@pytest.mark.asyncio
async def test_create_shell_task_rejects_neither_command_nor_argv(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    with pytest.raises(ValueError, match="either command or argv"):
        await manager.create_shell_task(
            description="empty",
            cwd=tmp_path,
        )


@pytest.mark.asyncio
async def test_start_process_forwards_env_to_subprocess(tmp_path: Path, monkeypatch):
    """End-to-end: env vars passed via ``create_shell_task(env=...)`` must be
    visible to the spawned subprocess. The subprocess prints the value, and
    we read it back from the task output."""
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command='printf "value=%s" "$MY_OH_TEST_VAR"',
        description="env passthrough",
        cwd=tmp_path,
        env={"MY_OH_TEST_VAR": "spawn-230"},
    )
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    output = manager.read_task_output(task.id)
    assert "value=spawn-230" in output


def test_encode_task_worker_payload_wraps_multiline_text() -> None:
    payload = _encode_task_worker_payload("alpha\nbeta\n")
    assert json.loads(payload.decode("utf-8")) == {"text": "alpha\nbeta"}


def test_encode_task_worker_payload_preserves_structured_messages() -> None:
    raw = '{"text":"follow up","from":"coordinator"}'
    payload = _encode_task_worker_payload(raw)
    assert payload.decode("utf-8") == raw + "\n"


@pytest.mark.asyncio
async def test_stop_task(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="sleep 30",
        description="sleeper",
        cwd=tmp_path,
    )
    await manager.stop_task(task.id)
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "killed"


@pytest.mark.asyncio
async def test_completion_listener_fires_when_task_finishes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    seen: list[tuple[str, str, int | None]] = []
    done = asyncio.Event()

    async def _listener(task):
        seen.append((task.id, task.status, task.return_code))
        done.set()

    manager.register_completion_listener(_listener)

    task = await manager.create_shell_task(
        command="printf 'done'",
        description="listener",
        cwd=tmp_path,
    )

    await asyncio.wait_for(done.wait(), timeout=5)

    assert seen == [(task.id, "completed", 0)]
