"""Mirror test for ``runtime/bridge/session_manager.py`` (plan 01, R7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.runtime.bridge.session_manager import (
    BridgeSessionManager,
    BridgeSessionRecord,
    get_bridge_manager,
)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr("questorharness.runtime.bridge.session_manager.get_data_dir", lambda: root)
    return root


def _record(session_id: str, started_at: float, status: str = "running") -> BridgeSessionRecord:
    return BridgeSessionRecord(
        session_id=session_id,
        command="questor",
        cwd="/work",
        pid=100,
        status=status,
        started_at=started_at,
        output_path=f"/tmp/{session_id}.log",
    )


class _Process:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.pid = 4242
        self.stdout = None


class _Handle:
    def __init__(self, returncode: int | None = None) -> None:
        self.process = _Process(returncode)
        self.cwd = "/work"
        self.started_at = 10.0
        self.killed = False

    async def kill(self) -> None:
        self.killed = True


def test_a_fresh_manager_reports_no_sessions() -> None:
    assert BridgeSessionManager().list_sessions() == []
    assert BridgeSessionManager().read_output("absent") == ""


def test_status_is_derived_from_the_process_returncode() -> None:
    manager = BridgeSessionManager()
    manager._sessions["running"] = _Handle(None)
    manager._sessions["done"] = _Handle(0)
    manager._sessions["broken"] = _Handle(1)
    manager._commands.update({"running": "r", "done": "d", "broken": "b"})
    for key in ("running", "done", "broken"):
        manager._output_paths[key] = Path("/tmp/x.log")

    statuses = {record.session_id: record.status for record in manager.list_sessions()}

    assert statuses == {"running": "running", "done": "completed", "broken": "failed"}


def test_sessions_are_listed_newest_first() -> None:
    manager = BridgeSessionManager()
    for key, started in (("old", 1.0), ("new", 5.0), ("mid", 3.0)):
        handle = _Handle()
        handle.started_at = started
        manager._sessions[key] = handle
        manager._commands[key] = "questor"
        manager._output_paths[key] = Path("/tmp/x.log")

    assert [record.session_id for record in manager.list_sessions()] == ["new", "mid", "old"]


def test_output_is_read_from_the_tail(data_root: Path) -> None:
    manager = BridgeSessionManager()
    path = data_root / "s1.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0123456789" * 5, encoding="utf-8")
    manager._output_paths["s1"] = path

    assert manager.read_output("s1", max_bytes=10) == "0123456789"[-10:]
    assert manager.read_output("s1", max_bytes=1000) == "0123456789" * 5


async def test_stop_kills_the_session_and_rejects_an_unknown_id() -> None:
    manager = BridgeSessionManager()
    handle = _Handle()
    manager._sessions["s1"] = handle

    await manager.stop("s1")
    assert handle.killed is True

    with pytest.raises(ValueError, match="Unknown bridge session"):
        await manager.stop("nope")


def test_get_bridge_manager_is_a_singleton() -> None:
    assert get_bridge_manager() is get_bridge_manager()
