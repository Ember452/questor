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


# 目录顺序 = 注册顺序 = /help 顺序；`/` 是零前缀，菜单前几行必须是“人先要用的”，
# 不是字母序前几个（旧行为：agents/autopilot/brainstorming）。
ORDERED = {
    "/help": "Show available commands",
    "/exit": "Exit QuestorHarness",
    "/model": "Show, switch, or manage profile models",
    "/compact": "Compact older conversation history",
    "/lark-mail": "Invoke the lark-mail skill",
}


def test_bare_slash_keeps_the_catalog_order() -> None:
    """只打 `/`：按目录顺序给出，而不是重新按字母序排。"""
    assert _texts(SlashCompleter(ORDERED), "/")[:3] == ["/help", "/exit", "/model"]


def test_prefix_hit_suppresses_fuzzy_noise() -> None:
    """有前缀命中时，子序列噪音不得挤进菜单（`/m` 只该看见 /model）。"""
    assert _texts(SlashCompleter(ORDERED), "/m") == ["/model"]


def test_fuzzy_only_when_no_prefix_hit() -> None:
    """没有前缀命中时才轮到子序列，且顺序仍取目录顺序。"""
    assert _texts(SlashCompleter(ORDERED), "/lml") == ["/lark-mail"]


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
