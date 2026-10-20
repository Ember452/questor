"""默认上下文装配器的逐字节 golden 钉（OPT-12a b2）。

golden 由**当前实现生成一次**并入库（``tests/golden/prompt_system*.txt``），断言逐字节相等：
空白、末尾换行、以及 ``system=None`` 时那个字面 ``"None"`` 都算契约——它是**现存行为**，
修它属于 OPT-12b/B7，本刀只搬家不改行为，并用 golden 防止“顺手修好”。

golden 文件必须 **LF-only**：Windows 检出若带回 CRLF，`read_text` 的通用换行会把它折叠成 LF，
“逐字节”就退化成平台相关；故先断言原始字节里没有 ``\\r``。
"""

from __future__ import annotations

from pathlib import Path

from questor.surfaces._assembly import DEFAULT_CONTEXT_ASSEMBLER, DefaultContextAssembler, assemble_system_prompt

_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"

#: golden 生成时的固定 system（非空用例）。
_SYSTEM = "You are questor, a terminal agent."


def _golden(name: str) -> str:
    """读 golden 的**原始字节**（先证 LF-only，再按 UTF-8 解码；不做换行折叠）。"""
    raw = (_GOLDEN_DIR / name).read_bytes()
    assert b"\r" not in raw, f"{name} 必须是 LF-only（否则逐字节 golden 变成平台相关）"
    return raw.decode("utf-8")


def _skills_fixture(root: Path) -> Path:
    """两个确定性技能（名字+描述即全部可变面；目录里不会出现绝对路径）。"""
    for name, description in (
        ("web-research", "searches the web and summarizes sources"),
        ("code-review", "reviews a diff for correctness and style"),
    ):
        skill_dir = root / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\nbody\n", encoding="utf-8")
    return root


def test_non_empty_system_matches_golden(tmp_path: Path) -> None:
    """system 非空：默认装配器输出 == golden（逐字节含空白）。"""
    skills = _skills_fixture(tmp_path)
    assert DEFAULT_CONTEXT_ASSEMBLER.assemble(_SYSTEM, skills) == _golden("prompt_system.txt")


def test_none_system_matches_golden_including_literal_none(tmp_path: Path) -> None:
    """system=None：现状会把字面 ``None`` 拼进 prompt——逐字节复现，不在这里修 B7 的 bug。"""
    skills = _skills_fixture(tmp_path)
    produced = DEFAULT_CONTEXT_ASSEMBLER.assemble(None, skills)
    assert produced is not None
    assert produced.startswith("None\n\nAvailable skills:")
    assert produced == _golden("prompt_system_none.txt")


def test_no_skills_dir_leaves_system_unchanged() -> None:
    """无技能目录：装配器原样返回入参（None 仍 None、非空不变），不凭空造空串。"""
    assert assemble_system_prompt(None, None) is None
    assert assemble_system_prompt(_SYSTEM, None) == _SYSTEM
    assert DefaultContextAssembler().assemble(_SYSTEM, Path("/no/such/dir")) == _SYSTEM
