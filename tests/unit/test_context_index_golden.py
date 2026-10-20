"""B7/c4：索引段的 golden 钉（默认关逐字节不变 + 开索引只多一段定界文本）。

沿用 OPT-12a 的 golden 纪律：**LF-only**、原始字节比对（不做换行折叠），
这样 Windows 检出带回 CRLF 也不会让"逐字节"退化成平台相关。

两张金标的分工：
- ``prompt_system.txt``（既有）：**默认路径**——不开索引时 provider 的 system 必须一字不变；
- ``prompt_system_index_on.txt``（本刀新增）：**开索引后**只多出一段定界文本，前缀部分逐字节不变
  ——这正是 §6.1 的 prompt cache 论证：新增内容只能追加在静态块尾部，不得改写前缀。
"""

from __future__ import annotations

from pathlib import Path

from questor.memory.index import LEAD_IN, build_index_block
from questor.providers.fake import EchoProvider
from questor.surfaces._assembly import DEFAULT_CONTEXT_ASSEMBLER, inject_memory_block
from questor.surfaces.cli import CliSurface

_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"

_SYSTEM = "You are questor, a terminal agent."

#: 索引段固定素材（无绝对路径、无时间戳，保证 golden 可重放）。
_CORE = """# MEMORY
- user prefers short answers
- pitfalls: never rm -rf without confirmation
"""


def _skills_fixture(root: Path) -> Path:
    """与 `test_context_assembler_golden.py` 同一对技能（同序）：金标才能直接复用。"""
    for name, description in (
        ("web-research", "searches the web and summarizes sources"),
        ("code-review", "reviews a diff for correctness and style"),
    ):
        skill_dir = root / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\nbody\n", encoding="utf-8")
    return root


def _golden(name: str) -> str:
    raw = (_GOLDEN_DIR / name).read_bytes()
    assert b"\r" not in raw, f"{name} 必须是 LF-only（否则逐字节 golden 变成平台相关）"
    return raw.decode("utf-8")


def _assembled(root: Path, *, with_index: bool) -> str | None:
    base = DEFAULT_CONTEXT_ASSEMBLER.assemble(_SYSTEM, root)
    if not with_index:
        return base
    block = build_index_block(_CORE)
    assert block is not None
    return inject_memory_block(base, lambda: block.text)


def test_default_path_still_matches_the_existing_golden(tmp_path: Path) -> None:
    """不开索引：装配结果与既有金标逐字节相等（含 skills 目录那段）。"""
    skills = _skills_fixture(tmp_path)
    assert _assembled(skills, with_index=False) == _golden("prompt_system.txt")
    assert CliSurface(provider=EchoProvider(), system=_SYSTEM, skills_dir=skills).system == _golden("prompt_system.txt")


def test_index_on_golden_only_appends_the_delimited_section(tmp_path: Path) -> None:
    """开索引：金标 = 原前缀 + ``\\n\\n`` + 定界段；前缀部分一位未改（cache 前缀稳定性）。"""
    skills = _skills_fixture(tmp_path)
    golden_on = _golden("prompt_system_index_on.txt")
    produced = _assembled(skills, with_index=True)
    assert produced == golden_on
    prefix = _golden("prompt_system.txt")
    assert golden_on.startswith(prefix)
    section = golden_on[len(prefix) :]
    assert section.startswith(f"\n\n{LEAD_IN}\n")
    assert "user prefers short answers" in section and "never rm -rf" in section
