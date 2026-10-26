"""catalog 路由与 provider：未知 kind 404、每个 kind 都回真实数据形状。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.catalog import KINDS, CatalogContext, providers
from questorharness.bootstrap.hosts.serve.routes import Router
from questorharness.bootstrap.hosts.serve.transport import MemoryTransport
from questorharness.bootstrap.hosts.serve.wire import WireEncoder


class _Host:
    def __init__(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        self.runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
        self.authority = Authority()
        self.broadcaster = Broadcaster()
        self.encoder = WireEncoder()
        self.profile_root = tmp_path
        self.profile_id = "coding"

    def start_turn_task(self, record) -> None:  # type: ignore[no-untyped-def]
        raise AssertionError("not used")

    def cancel_turn(self, turn_id: str, client_id: str) -> bool:
        return True


def _get(host: object, path: str):  # type: ignore[no-untyped-def]
    transport = MemoryTransport(Router(host))  # type: ignore[arg-type]
    return asyncio.run(transport.request("GET", path))


def test_unknown_kind_is_404_and_never_an_empty_success(tmp_path) -> None:  # type: ignore[no-untyped-def]
    response = _get(_Host(tmp_path), "/rt/r1/catalog/nope")
    assert response.status == 404
    payload = json.loads(response.body)
    assert payload["code"]


def test_every_known_kind_answers_with_items(tmp_path) -> None:  # type: ignore[no-untyped-def]
    host = _Host(tmp_path)
    for kind in KINDS:
        response = _get(host, f"/rt/r1/catalog/{kind}")
        assert response.status == 200, kind
        payload = json.loads(response.body)
        assert payload["kind"] == kind
        assert isinstance(payload["items"], list), kind


def test_sessions_provider_lists_saved_snapshots(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """空工作区必须回空表（面板显示空态），而不是抛异常。"""

    items = providers.sessions(CatalogContext(cwd=tmp_path))
    assert items == []


def test_jobs_provider_formats_enabled_and_expression(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        providers,
        "load_cron_jobs",
        lambda: [{"name": "nightly", "enabled": False, "expression": "0 3 * * *"}],
    )
    items = providers.jobs(CatalogContext(cwd=tmp_path))
    assert items == [{"id": "nightly", "label": "nightly", "detail": "off · 0 3 * * *"}]


def test_git_provider_reports_branch_and_dirty_count(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import subprocess

    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    subprocess.run(("git", "-C", str(tmp_path), "config", "user.email", "a@b.c"), check=True)
    subprocess.run(("git", "-C", str(tmp_path), "config", "user.name", "t"), check=True)
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(("git", "-C", str(tmp_path), "add", "."), check=True)
    subprocess.run(("git", "-C", str(tmp_path), "commit", "-qm", "init"), check=True)
    (tmp_path / "f.txt").write_text("changed", encoding="utf-8")

    items = providers.git(CatalogContext(cwd=tmp_path))
    assert len(items) == 1
    assert items[0]["current"] is True
    assert "改动" in str(items[0]["detail"])


def test_build_returns_none_for_unknown_kind(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert providers.build("nope", CatalogContext(cwd=tmp_path)) is None


class _Settings:
    """provider 眼里的 settings：permission.mode.value / model / effort。"""

    def __init__(self, mode: str, model: str = "m1", effort: str = "low") -> None:
        self.permission = SimpleNamespace(mode=SimpleNamespace(value=mode))
        self.model = model
        self.effort = effort


def test_posture_provider_lists_three_modes_and_marks_the_current_one(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """/permissions 的三档就是引擎 PermissionMode 枚举；current 来自运行时 settings。"""

    ctx = CatalogContext(
        cwd=tmp_path, settings_provider=lambda: _Settings("plan", model="glm", effort="high")
    )
    items = providers.posture(ctx)
    assert [item["id"] for item in items] == ["default", "plan", "full_auto"]
    assert [item["id"] for item in items if item.get("current")] == ["plan"]


def test_status_provider_reports_model_and_effort(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """状态栏真值源：模型与推理强度各一行（值进 label，缺省回空串）。"""

    ctx = CatalogContext(
        cwd=tmp_path, settings_provider=lambda: _Settings("default", model="glm-4.7", effort="high")
    )
    items = providers.status(ctx)
    labels = {item["id"]: item["label"] for item in items}
    assert labels["model"] == "glm-4.7"
    assert labels["effort"] == "high"


def test_router_passes_the_runtime_settings_provider(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """路由必须把 runtime.current_settings 接给 provider，否则 CLI 覆盖会漂。"""

    host = _Host(tmp_path)
    host.runtime = SimpleNamespace(
        cwd=str(tmp_path),
        session_id="sid",
        current_settings=lambda: _Settings("full_auto", model="glm", effort="low"),
    )
    response = _get(host, "/rt/r1/catalog/posture")
    assert response.status == 200
    payload = json.loads(response.body)
    assert [item["id"] for item in payload["items"] if item.get("current")] == ["full_auto"]


def test_todos_provider_parses_the_default_checklist_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """:todo 面板的数据源：清单文件直读（与 git provider 读工作区同构）。"""

    (tmp_path / "TODO.md").write_text(
        "# TODO\n\n- [ ] 写文档\n- [x] 跑通 e2e\n", encoding="utf-8"
    )
    items = providers.todos(CatalogContext(cwd=tmp_path))
    assert [item["id"] for item in items] == ["写文档", "跑通 e2e"]
    assert items[1]["label"].startswith("✓")
    assert items[0]["label"].startswith("○")


def test_todos_provider_reads_the_last_written_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """模型可能写自定义路径：跟随宿主记住的最近一次 todo_write 路径。"""

    (tmp_path / "PLAN.md").write_text("- [x] 迁移\n", encoding="utf-8")
    items = providers.todos(CatalogContext(cwd=tmp_path, todo_path="PLAN.md"))
    assert [item["id"] for item in items] == ["迁移"]


def test_todos_provider_missing_file_is_an_empty_list(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """没有清单（会话里没写过 todo）→ 空表走面板空态，不抛异常。"""

    assert providers.todos(CatalogContext(cwd=tmp_path)) == []
