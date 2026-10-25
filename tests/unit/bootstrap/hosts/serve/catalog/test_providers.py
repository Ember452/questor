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
