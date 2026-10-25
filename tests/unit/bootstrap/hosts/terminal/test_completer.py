"""`completer.py`：命令前缀/子序列、`@` 路径、目录后缀。"""

from __future__ import annotations

from prompt_toolkit.document import Document

from questorharness.bootstrap.hosts.terminal.completer import FileCompleter, SlashCompleter

CATALOG = {
    "/compact": "Compact older conversation history",
    "/copy": "Copy the latest response",
    "/model": "Show or set the model",
}


def _texts(completer: object, text: str) -> list[str]:
    document = Document(text=text, cursor_position=len(text))
    return [item.text for item in completer.get_completions(document, None)]  # type: ignore[attr-defined]


def test_prefix_matches_come_first() -> None:
    texts = _texts(SlashCompleter(CATALOG), "/co")
    assert texts[:2] == ["/compact", "/copy"]
    assert "/model" not in texts


def test_subsequence_matches_a_shorter_typing() -> None:
    """/cmp 要能命中 /compact（Reasonix 补全菜单的模糊前缀）。"""
    assert "/compact" in _texts(SlashCompleter(CATALOG), "/cmp")


def test_command_with_arguments_stops_completing() -> None:
    assert _texts(SlashCompleter(CATALOG), "/model gpt") == []


def test_plain_text_is_not_command_completed() -> None:
    assert _texts(SlashCompleter(CATALOG), "hello") == []


def test_at_prefix_completes_files_in_the_base_dir(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    texts = _texts(FileCompleter(tmp_path), "@sr")
    assert any(text.endswith("src/") for text in texts), texts


def test_directory_completion_carries_a_slash(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "pkg").mkdir()
    texts = _texts(FileCompleter(tmp_path), "@")
    assert any(text.endswith("pkg/") for text in texts), texts


def test_bare_path_prefix_completes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "notes.md").write_text("", encoding="utf-8")
    texts = _texts(FileCompleter(tmp_path), "not")
    assert any(text.endswith("notes.md") for text in texts), texts


def test_slash_text_is_left_to_the_command_completer(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert _texts(FileCompleter(tmp_path), "/mod") == []


def test_missing_directory_is_silent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert _texts(FileCompleter(tmp_path), "@no-such-dir/x") == []
