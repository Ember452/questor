"""apply_patch 安全加固（#156）。逐项复现报告实测缺陷并钉死。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.apply_patch import ApplyPatchTool
from questor.kernel.tool_arguments import extract_paths
from support.tool_ctx import FakeToolContext


async def test_extract_paths_includes_unified_diff_targets() -> None:
    """BLK-1：apply_patch 的 `input` 补丁路径必须进权限候选（含 .env 裸名）。"""
    patch = "--- a/.env\n+++ b/.env\n@@\n-old\n+new\n"
    paths = extract_paths({"input": patch})
    assert ".env" in paths, f"补丁路径未进权限候选：{paths}"


async def test_body_dashes_are_not_treated_as_file_delete(tmp_path: Path) -> None:
    """BLK-11：hunk 内形如 `--- BREAK` 的行不得被误判为删除无关文件。"""
    (tmp_path / "doc.md").write_text("a\n", encoding="utf-8")
    (tmp_path / "BREAK").write_text("IMPORTANT DATA\n", encoding="utf-8")
    patch = "--- a/doc.md\n+++ b/doc.md\n@@\n-a\n+b\n--- BREAK\n"
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    # `--- BREAK` 被当作 hunk 内容（而非新文件段）→ 上下文不匹配报错，绝不会当成删除段。
    assert res.status == "error", res
    assert (tmp_path / "BREAK").exists(), "无关文件 BREAK 被补丁静默删除（BLK-11）"


async def test_pure_add_hunk_inserts_at_declared_position(tmp_path: Path) -> None:
    """MAJ-12：纯新增 hunk 按 @@ 行号插入，而非一律塞到文件头。"""
    (tmp_path / "f.txt").write_text("L1\nL2\n", encoding="utf-8")
    # @@ -2,0 声明在第 2 行前插入；旧实现会把 NEW 放到文件头。
    patch = "--- a/f.txt\n+++ b/f.txt\n@@ -2,0 +2,1 @@\n+NEW\n"
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    assert res.status == "success", res.result
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "L1\nNEW\nL2\n"


async def test_crlf_file_keeps_crlf_after_patch(tmp_path: Path) -> None:
    """MAJ-13：CRLF 文件应用补丁后必须保持 CRLF，不被整文件翻成 LF。"""
    (tmp_path / "crlf.txt").write_bytes(b"keep\r\nold\r\n")
    patch = "--- a/crlf.txt\n+++ b/crlf.txt\n@@\n keep\n-old\n+new\n"
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    assert res.status == "success", res.result
    assert (tmp_path / "crlf.txt").read_bytes() == b"keep\r\nnew\r\n"


async def test_lf_file_keeps_lf_after_patch(tmp_path: Path) -> None:
    (tmp_path / "lf.txt").write_bytes(b"keep\nold\n")
    patch = "--- a/lf.txt\n+++ b/lf.txt\n@@\n keep\n-old\n+new\n"
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    assert res.status == "success", res.result
    assert (tmp_path / "lf.txt").read_bytes() == b"keep\nnew\n"


async def test_multi_file_failure_rolls_back(tmp_path: Path, monkeypatch) -> None:
    """MAJ-11：多文件补丁在阶段二任一文件写失败时，必须回滚全部、不留半改。"""
    real = Path.write_bytes

    def fake(self: Path, data) -> int:  # 对名字含 boom 的目标注入写失败
        if "boom" in self.name:
            raise OSError("injected disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", fake)
    patch = (
        "--- /dev/null\n+++ b/good.txt\n@@ -0,0 +1,1 @@\n+ok\n"
        "--- /dev/null\n+++ b/boom.txt\n@@ -0,0 +1,1 @@\n+bad\n"
    )
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    monkeypatch.undo()
    assert res.status == "error" and "rolled back" in res.result, res.result
    assert not (tmp_path / "good.txt").exists(), "半改：第二个文件写失败但 good.txt 残留"
    assert not (tmp_path / "boom.txt").exists()


async def test_git_prefix_diff_edits_real_path(tmp_path: Path) -> None:
    """MAJ-29：``--- a/x +++ b/x`` 的 git 前缀必须被剥离、落到真实 x（不产生 b/x）。"""
    (tmp_path / "real.txt").write_bytes(b"keep\nold\n")
    patch = "--- a/real.txt\n+++ b/real.txt\n@@\n keep\n-old\n+new\n"
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    assert res.status == "success", res.result
    assert (tmp_path / "real.txt").read_bytes() == b"keep\nnew\n"
    assert not (tmp_path / "b/real.txt").exists()


async def test_real_a_prefixed_dir_not_mistripped(tmp_path: Path) -> None:
    """MAJ-29 歧义消解：仓库真有 a/ 目录时，``a/a/x -> b/a/x`` 落到真实 a/x（只剥一层前缀，与 git apply 同义）。"""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_bytes(b"keep\nold\n")
    patch = "--- a/a/x.txt\n+++ b/a/x.txt\n@@\n keep\n-old\n+new\n"
    res = await ApplyPatchTool().execute({"input": patch}, FakeToolContext(tmp_path))
    assert res.status == "success", res.result
    assert (tmp_path / "a" / "x.txt").read_bytes() == b"keep\nnew\n"
    assert not (tmp_path / "x.txt").exists()
