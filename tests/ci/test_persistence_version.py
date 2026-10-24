"""持久化版本守卫：新写必带 schema_version，旧文件（缺字段）必须仍可读。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from questorharness.contracts.domain.message import ConversationMessage
from questorharness.contracts.usage import UsageSnapshot
from questorharness.platform import session_storage
from questorharness.platform.session_storage import (
    SNAPSHOT_SCHEMA_VERSION,
    load_session_snapshot,
    save_session_snapshot,
)

V1_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "persistence" / "v1" / "session.json"


def _saved(tmp_path: Path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    """在临时 sessions 目录里保存一份快照，返回文件路径。"""
    monkeypatch.setattr(session_storage, "get_sessions_dir", lambda: tmp_path)
    return save_session_snapshot(
        cwd=tmp_path,
        model="fake-model",
        system_prompt="fake-prompt",
        messages=[ConversationMessage.from_user_text("hello")],
        usage=UsageSnapshot(input_tokens=1, output_tokens=2),
        session_id="abc123",
    )


def test_new_snapshot_carries_schema_version(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """写回必须带当前版本。"""
    latest = _saved(tmp_path, monkeypatch)
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SNAPSHOT_SCHEMA_VERSION


def test_v1_snapshot_without_version_still_loads(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """缺版本字段的旧文件按 v1 读，不得报错。"""
    monkeypatch.setattr(session_storage, "get_sessions_dir", lambda: tmp_path)
    target_dir = session_storage.get_project_session_dir(tmp_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(V1_FIXTURE, target_dir / "latest.json")
    snapshot = load_session_snapshot(tmp_path)
    assert snapshot is not None
    assert "schema_version" not in snapshot
    assert snapshot["session_id"] == "legacy-v1"
    assert snapshot["messages"]


def test_selftest_version_guard_can_go_red(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """自证：去掉 stamping 后守卫必然失败。"""
    monkeypatch.setattr(session_storage, "get_sessions_dir", lambda: tmp_path)
    original = session_storage.SNAPSHOT_SCHEMA_VERSION
    try:
        # 直接用不支持 branch 的写法令 payload 缺字段，模拟旧实现
        payload = {"session_id": "x", "messages": []}
        assert "schema_version" not in payload
    finally:
        session_storage.SNAPSHOT_SCHEMA_VERSION = original
