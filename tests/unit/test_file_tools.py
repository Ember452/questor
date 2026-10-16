"""T15：文件工具单元覆盖（read/write/edit/apply_patch/ls/glob/grep）。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.apply_patch import ApplyPatchTool
from questor.capabilities.tools.edit import EditTool
from questor.capabilities.tools.glob import GlobTool
from questor.capabilities.tools.grep import GrepTool
from questor.capabilities.tools.ls import LsTool
from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.write import WriteTool
from support.tool_ctx import FakeToolContext


async def test_read_returns_full_content(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    res = await ReadTool().execute({"file_path": "a.txt"}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert "line1" in res.result and "line3" in res.result


async def test_read_offset_limit_window(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("\n".join(str(i) for i in range(100)), encoding="utf-8")
    res = await ReadTool().execute({"file_path": "big.txt", "offset": 10, "limit": 5}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert res.result.startswith("10")
    assert "truncated" in res.result


async def test_read_directory_is_error(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    res = await ReadTool().execute({"file_path": "d"}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "directory" in res.result


async def test_read_binary_is_error(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02abc")
    res = await ReadTool().execute({"file_path": "bin.dat"}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "binary" in res.result


async def test_read_escape_denied(tmp_path: Path) -> None:
    res = await ReadTool().execute({"file_path": "../../etc/passwd"}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "escapes workspace root" in res.result


async def test_read_cancelled(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    res = await ReadTool().execute({"file_path": "a.txt"}, FakeToolContext(tmp_path, cancelled=True))
    assert res.status == "error"
    assert res.result == "cancelled"


async def test_write_creates_and_overwrites(tmp_path: Path) -> None:
    res = await WriteTool().execute({"file_path": "sub/out.txt", "content": "hello"}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert (tmp_path / "sub" / "out.txt").read_text(encoding="utf-8") == "hello"


async def test_write_escape_denied(tmp_path: Path) -> None:
    res = await WriteTool().execute({"file_path": "../evil.txt", "content": "x"}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "escapes workspace root" in res.result
    assert not (tmp_path.parent / "evil.txt").exists()


async def test_edit_unique_anchor(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    res = await EditTool().execute({"file_path": "f.txt", "old_string": "beta", "new_string": "gamma"}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "alpha\ngamma\n"


async def test_edit_ambiguous_without_replace_all_errors(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("dup\ndup\n", encoding="utf-8")
    res = await EditTool().execute({"file_path": "f.txt", "old_string": "dup", "new_string": "x", "replace_all": False}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "multiple" in res.result.lower()


async def test_edit_replace_all_reports_count(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("dup dup dup", encoding="utf-8")
    res = await EditTool().execute({"file_path": "f.txt", "old_string": "dup", "new_string": "x", "replace_all": True}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "x x x"
    assert "3" in str(res.display)


async def test_edit_missing_anchor_errors(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("abc", encoding="utf-8")
    res = await EditTool().execute({"file_path": "f.txt", "old_string": "zzz", "new_string": "y"}, FakeToolContext(tmp_path))
    assert res.status == "error"


async def test_apply_patch_all_or_nothing(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("keep\nold\n", encoding="utf-8")
    patch = (
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@\n"
        " keep\n"
        "-old\n"
        "+new\n"
    )
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "keep\nnew\n"


async def test_apply_patch_context_mismatch_leaves_file_untouched(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("actual\n", encoding="utf-8")
    patch = "--- a/a.txt\n+++ b/a.txt\n@@\n-wrong\n+new\n"
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "actual\n"


async def test_apply_patch_escape_denied(tmp_path: Path) -> None:
    patch = "--- a/../evil.txt\n+++ b/../evil.txt\n@@\n+x\n+y\n"
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "escapes workspace root" in res.result


async def test_ls_lists_and_skips_noise_dirs(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x", encoding="utf-8")
    res = await LsTool().execute({"path": "."}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert "keep.txt" in res.result
    assert "dep.js" not in res.result
    assert "node_modules" not in res.result.split("\n")


async def test_ls_entry_cap(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    res = await LsTool().execute({"path": ".", "limit": 3}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert res.result.count("\n") <= 4
    assert "truncated" in res.result


async def test_glob_matches_and_caps(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    res = await GlobTool().execute({"pattern": "**/*.txt"}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert "a.txt" in res.result
    assert "b.py" not in res.result


async def test_glob_skips_dirs(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.txt").write_text("x", encoding="utf-8")
    res = await GlobTool().execute({"pattern": "**/*.txt"}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert "x.txt" not in res.result


async def test_grep_finds_pattern(tmp_path: Path) -> None:
    (tmp_path / "code.py").write_text("hello world\nfoo bar\n", encoding="utf-8")
    res = await GrepTool().execute({"pattern": "foo"}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert "code.py" in res.result
    assert "foo bar" in res.result


async def test_grep_invalid_regex_errors(tmp_path: Path) -> None:
    res = await GrepTool().execute({"pattern": "("}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "regex" in res.result.lower()


async def test_grep_respects_max_matches(tmp_path: Path) -> None:
    (tmp_path / "many.txt").write_text("\n".join("hit" for _ in range(50)), encoding="utf-8")
    res = await GrepTool().execute({"pattern": "hit", "max_matches": 5}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert res.result.count("many.txt") <= 5
