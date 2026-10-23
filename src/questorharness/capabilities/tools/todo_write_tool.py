"""Tool for maintaining a project TODO file."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from questorharness.capabilities.tools.base import ToolCapabilities, BaseTool, ToolExecutionContext, ToolResult


class TodoWriteToolInput(BaseModel):
    """Arguments for TODO writes."""

    item: str = Field(description="TODO item text")
    checked: bool = Field(default=False)
    path: str = Field(default="TODO.md")


class TodoWriteTool(BaseTool):
    """Add or update an item in a TODO markdown file."""

    name = "todo_write"
    description = "Add a new TODO item or mark an existing one as done in a markdown checklist file."
    input_model = TodoWriteToolInput

    capabilities = ToolCapabilities()

    async def execute(self, arguments: TodoWriteToolInput, context: ToolExecutionContext) -> ToolResult:
        path = Path(context.cwd) / arguments.path
        existing = path.read_text(encoding="utf-8") if path.exists() else "# TODO\n"

        unchecked_line = f"- [ ] {arguments.item}"
        checked_line = f"- [x] {arguments.item}"
        target_line = checked_line if arguments.checked else unchecked_line

        if unchecked_line in existing and arguments.checked:
            # 将现有未勾选项标记为完成（原地更新）
            updated = existing.replace(unchecked_line, checked_line, 1)
        elif target_line in existing:
            # 条目已处于目标状态 — 无操作
            return ToolResult(output=f"No change needed in {path}")
        else:
            # 新条目 — 追加
            updated = existing.rstrip() + f"\n{target_line}\n"

        path.write_text(updated, encoding="utf-8")
        return ToolResult(output=f"Updated {path}")

# questor: allow R7 -- until W8 adds the mirror test
