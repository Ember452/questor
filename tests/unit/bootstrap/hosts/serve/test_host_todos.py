"""`todos` 帧（plan03 W-D4）：清单解析与宿主发布时机。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from questorharness.bootstrap.hosts.serve import ServeHost, wire
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.contracts.domain.events import (
    ToolExecutionCompleted,
    ToolExecutionStarted,
)


def _host(tmp_path: Path) -> ServeHost:
    runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
    return ServeHost(runtime, authority=Authority(), profile_root=tmp_path)  # type: ignore[arg-type]


def test_parse_checklist_reads_both_states() -> None:
    text = "# TODO\n- [ ] 写文档\n- [x] 补测试\n  - [X] 大写也算\n不是清单行\n"
    assert wire.parse_checklist(text) == [
        {"text": "写文档", "checked": False},
        {"text": "补测试", "checked": True},
        {"text": "大写也算", "checked": True},
    ]


def test_parse_checklist_ignores_prose() -> None:
    assert wire.parse_checklist("只有段落，没有清单\n") == []


def test_successful_todo_write_publishes_the_checklist(tmp_path: Path) -> None:
    host = _host(tmp_path)
    (tmp_path / "TODO.md").write_text("- [ ] 一件\n- [x] 另一件\n", encoding="utf-8")
    published: list[dict[str, object]] = []

    async def capture(frame):  # type: ignore[no-untyped-def]
        published.append(frame)

    host.broadcaster.publish = capture  # type: ignore[method-assign]

    async def scenario() -> None:
        await host.render_event(
            ToolExecutionStarted(tool_name="todo_write", tool_input={"item": "一件"})
        )
        await host.render_event(
            ToolExecutionCompleted(tool_name="todo_write", output="Updated", is_error=False)
        )

    asyncio.run(scenario())
    todos = [frame for frame in published if frame.get("kind") == "todos"]
    assert len(todos) == 1
    assert todos[0]["path"] == "TODO.md"
    assert todos[0]["items"] == [
        {"text": "一件", "checked": False},
        {"text": "另一件", "checked": True},
    ]


def test_failed_todo_write_publishes_nothing(tmp_path: Path) -> None:
    host = _host(tmp_path)
    (tmp_path / "TODO.md").write_text("- [ ] 一件\n", encoding="utf-8")
    published: list[dict[str, object]] = []

    async def capture(frame):  # type: ignore[no-untyped-def]
        published.append(frame)

    host.broadcaster.publish = capture  # type: ignore[method-assign]
    asyncio.run(
        host.render_event(
            ToolExecutionCompleted(tool_name="todo_write", output="boom", is_error=True)
        )
    )
    assert [frame for frame in published if frame.get("kind") == "todos"] == []


def test_missing_checklist_file_publishes_nothing(tmp_path: Path) -> None:
    """读不到文件就不发帧：宁可没有清单，也不发一个假清单。"""

    host = _host(tmp_path)
    published: list[dict[str, object]] = []

    async def capture(frame):  # type: ignore[no-untyped-def]
        published.append(frame)

    host.broadcaster.publish = capture  # type: ignore[method-assign]
    asyncio.run(
        host.render_event(
            ToolExecutionCompleted(tool_name="todo_write", output="Updated", is_error=False)
        )
    )
    assert [frame for frame in published if frame.get("kind") == "todos"] == []


def test_custom_path_is_remembered_from_the_started_event(tmp_path: Path) -> None:
    host = _host(tmp_path)
    (tmp_path / "docs-TODO.md").write_text("- [ ] 自定义\n", encoding="utf-8")
    published: list[dict[str, object]] = []

    async def capture(frame):  # type: ignore[no-untyped-def]
        published.append(frame)

    host.broadcaster.publish = capture  # type: ignore[method-assign]

    async def scenario() -> None:
        await host.render_event(
            ToolExecutionStarted(tool_name="todo_write", tool_input={"path": "docs-TODO.md"})
        )
        await host.render_event(
            ToolExecutionCompleted(tool_name="todo_write", output="Updated", is_error=False)
        )

    asyncio.run(scenario())
    todos = [frame for frame in published if frame.get("kind") == "todos"]
    assert todos and todos[0]["path"] == "docs-TODO.md"


def test_other_tools_never_publish_todos(tmp_path: Path) -> None:
    host = _host(tmp_path)
    published: list[dict[str, object]] = []

    async def capture(frame):  # type: ignore[no-untyped-def]
        published.append(frame)

    host.broadcaster.publish = capture  # type: ignore[method-assign]
    asyncio.run(
        host.render_event(
            ToolExecutionCompleted(tool_name="bash", output="ok", is_error=False)
        )
    )
    assert [frame for frame in published if frame.get("kind") == "todos"] == []
