"""T15 集成：文件工具在真实临时工作区上的协作流水线。"""

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


async def test_file_tools_pipeline_on_real_workspace(tmp_path: Path) -> None:
    ctx = FakeToolContext(tmp_path)
    assert (await WriteTool().execute({"file_path": "pkg/main.py", "content": "def run():\n    return 1\n"}, ctx)).status == "success"
    assert (await EditTool().execute({"file_path": "pkg/main.py", "old_string": "return 1", "new_string": "return 2"}, ctx)).status == "success"

    patch = "--- a/pkg/main.py\n+++ b/pkg/main.py\n@@\n def run():\n-    return 2\n+    return 3\n"
    assert (await ApplyPatchTool().execute({"input": patch}, ctx)).status == "success"

    read_res = await ReadTool().execute({"file_path": "pkg/main.py"}, ctx)
    assert read_res.status == "success"
    assert "return 3" in read_res.result

    grep_res = await GrepTool().execute({"pattern": "return 3", "glob": "*.py"}, ctx)
    assert grep_res.status == "success"
    assert "pkg/main.py" in grep_res.result

    glob_res = await GlobTool().execute({"pattern": "pkg/*.py"}, ctx)
    assert glob_res.status == "success"
    assert "main.py" in glob_res.result

    ls_res = await LsTool().execute({"path": "pkg"}, ctx)
    assert ls_res.status == "success"
    assert "main.py" in ls_res.result
