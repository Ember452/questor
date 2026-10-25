"""coordinator_drain 镜像测试：未通知的异步 agent 条目筛选。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.coordinator_drain import pending_async_agent_entries


def test_pending_entries_ignores_missing_metadata() -> None:
    """缺元数据时返回空列表，不抛错。"""
    assert pending_async_agent_entries(None) == []
    assert pending_async_agent_entries({}) == []
    assert pending_async_agent_entries({"async_agent_tasks": "bad"}) == []


def test_pending_entries_filters_notified_and_idless() -> None:
    """已通知与缺 task_id 的条目都不进入待汇总集合。"""
    metadata = {
        "async_agent_tasks": [
            {"task_id": "t1", "notification_sent": False, "description": "first"},
            {"task_id": "t2", "notification_sent": True, "description": "already sent"},
            {"notification_sent": False, "description": "no id"},
            "not-a-dict",
        ]
    }
    pending = pending_async_agent_entries(metadata)
    assert [entry["task_id"] for entry in pending] == ["t1"]
