#!/usr/bin/env python3
"""文档一致性守卫：计数 / 交叉引用 / "原写↔已改"成对 / 跨文档否决词（advisory；v3 §21 G2 + §15.6 + §20.3）。

文档是单一真源（§20 互锁表 + §15.6 锚点勘误 + §21 G11「文档即契约」），但它会漂：§15.6 的背景
自述「新表改对、旧表未回灌」的漂移复发，就是本守卫要机守的缺陷类。本守卫**只读**文档与仓库计数，
**从不改文档**——不一致写进报告，修正属文档作业（G11：代码事实 > 文档声明）。

退出码（沿用 scripts/_guard_kit 约定）：
    0 = 一致；或文档不在仓内 → 打印 `SKIP: doc not present`（advisory 语义：CI 里文档不在仓内）
    1 = 文档存在但不一致（红）
    2 = 参数/自身错误（文档为空、workflow/脚本/内核文件缺失等 fail-on-empty）

四项检查：
  A. **计数一致**：9 条 EXPECTED（见下方常量，逐条注明来源 §）。第 9 条（基线 913/6）**只做注释**——
     它随每次开发变化，断言它只会制造噪声红；真正的基线由 pytest 自己保证。
  B. **引用存在**：正文出现的 §n、附录X、B<数字>、C-<数字> 必须在文内有定义（外部文档引用由
     "限定词"与 EXTERNAL_SECTION_REFS 显式豁免，见下）。
  C. **"已改"成对**：§15.6 与 §20.3 的表，每行都要同时有"原写"侧（原写/冲突）与"已改"侧（状态/裁决）。
     只改一半（删了旧文本、没写新值；或写了新值、旧行没标已改）是最常见的漂移形状。
  D. **跨文档否决词**：PLAN §3 的否决关键词（事实版本链|providers/*子包|Fiber/reflect|声明式失败|
     中间件链化|QueueHandler）在设计文档里出现时，同句必须带 `C-\\d|已改|不建|不拆|仅借`——
     否则读者无法判断"这条是复活了否决项，还是转述否决"。

两个已实测的坑（正则必须照此写，否则守卫自己假绿/假红；2026-10-20 实测）：
  ① **不要用裸 `os\\.walk` 断言全文**：§15.5.1/§16 里描述"外部仓扫描方法"的段落是**正确文本**，
     裸正则会把它们判红。要用 `各自\\s*os\\.walk` 且**只**限定在 §21 G2 行（G2 才是"scripts/
     各自实现"的主张，且实测 scripts/ 全用 `Path.rglob`）。
  ② **不要用裸 `unit\\s*83`**：勘误记录"83→107"本身就含 `unit 83` 字样，裸正则会把**已修好**的
     文档判红。要用 `unit\\s*\\*{0,2}83` 且限定 §4 行（旧口径只该出现在 §4 的现状事实里）。

Usage:
    uv run python scripts/check_doc_cross_refs.py
    uv run python scripts/check_doc_cross_refs.py --self-test
    uv run python scripts/check_doc_cross_refs.py --doc ../questor目标形态设计.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, fail_on_empty, read_text, run_self_test, walk_py

#: 仓库根（本文件在 `<root>/scripts/` 下）。默认文档路径相对 `questor/`：`../questor目标形态设计.md`。
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOC = ROOT.parent / "questor目标形态设计.md"

#: A 项期望值。改这里 = 改"文档声称的事实"：必须同时改文档并在 commit/CHANGELOG 说明理由。
EXPECTED: dict[str, int] = {
    "takeaways": 19,  # §0 标题「本版定夺的 19 条取舍」；数 `^| T\d+ |` 行
    "blades": 17,  # §13「17 刀（T16）」+ T16；数 `^| **B` 行（B0.5 算一刀）
    "points_live": 13,  # §5.1 表内 13 行生效点位（B6 启用 Stop）
    "points_reserved": 4,  # §5.1「预留 4 位」句里的 4 个名字（Notification/Elicitation/TaskUpdated/PlanStep）
    "src_py": 131,  # §21 前提判断「131 个 src/ 下 .py」（B3/B4/B6/B2；B11 schedule/__init__.py + scheduler.py）
    "gate_scripts": 16,  # §21：14 个 check_*.py + 2 个 verify_*.py（不含 _diag_threads.py；B0 新增 check_reduce_chokepoint.py）
    "ci_gate_steps": 18,  # §21 / PLAN SCAN-1：boundaries 恒阻塞 job 的「门步」数（B0 新增 1 步）
    "reduce_calls": 0,  # §2-1：B0 后 loop.py/recovery.py 不再直调 reduce（17 处全改走 apply()）
    "test_files": 193,  # PLAN SCAN-2：tests/ 下 .py 合计 193（B2 +1 unit；B3/B4/B6/B11 +4 integration）
    "test_unit": 113,  # PLAN SCAN-2：unit 113（B2 +1 command window）
    "test_integration": 74,  # PLAN SCAN-2：integration 74（B3/B4/B6/B11 各 +1）
    "test_support": 3,  # PLAN SCAN-2：support 3（fixture 基建，非 test_* 命名）
    "test_evals": 2,  # PLAN SCAN-2：evals 2
    "test_root": 1,  # tests/ 顶层 conftest.py
}

#: 第 9 条 EXPECTED（基线）**只做注释、不做断言**：它会随每次开发变化，断言=制造噪声红。
BASELINE_NOTE = "913 passed / 6 skipped @ 6571457（v3 §1「实测基线」；CHANGELOG/CI 各自背书）"

#: §15.6 与 §20.3 的"已改"侧标记（§15.6 状态列有 `✅ 已改`/`✅ 已标`/`✅ 已逐符号标` 多种写法，统一按 ✅ 或 已改/已标 认）。
_PAIR_STATUS_OK = re.compile(r"✅|已改|已标")
_PAIR_DECISION_OK = re.compile(r"采|删|加|澄清|同判|不在|已改|已入|按|拒|留")
#: §20.3 的"原写"侧：冲突以 `vs`/自纠/归属重叠三种形状陈述。
_PAIR_CONFLICT_OK = re.compile(r"vs|自纠|重叠")

#: D 项：PLAN §3「已否决（勿复活）」的关键词（原文见 QUESTOR-OPTIMIZATION-PLAN.md §3）。
_VETO = re.compile(r"事实版本链|providers/[^\s|]*子包|Fiber/reflect|声明式失败|中间件链化|QueueHandler")
_VETO_OK = re.compile(r"C-\d|已改|不建|不拆|仅借")

#: 坑①：裸 `os\.walk` 会误伤 §15.5.1/§16 的"外部仓扫描方法"正确文本 → 必须限定 G2 行。
_TRAP_SELF_WALK = re.compile(r"各自\s*os\.walk")
#: 坑②：裸 `unit\s*83` 会误伤 "83→107" 的勘误记录 → 必须 `\*{0,2}` 且限定 §4 行。
_TRAP_STALE_UNIT = re.compile(r"unit\s*\*{0,2}83")

#: 引用解析。
_SEC_REF = re.compile(r"§\s*(\d+(?:\.\d+)*)")
_SEC_DEF = re.compile(r"^#{2,4}\s+(\d+(?:\.\d+)*)[\.\s、]")
_SEC_DEF_IN_HEADING = re.compile(r"§\s*(\d+(?:\.\d+)*)")
_APPX_REF = re.compile(r"附录\s*([A-Z])(?:\.(\d+))?")
_APPX_DEF = re.compile(r"^#{2,4}\s+附录\s*([A-Z])")
_APPX_SUB_DEF = re.compile(r"^#{2,4}\s+([A-Z]\.\d+)[\.\s、]")
_BLADE_REF = re.compile(r"(?<![\w.])B(\d+(?:\.\d+)?)(?![\d.])")
_BLADE_DEF = re.compile(r"^\| \*\*(B\d+(?:\.\d+)?)\*\*")
_CASE_REF = re.compile(r"C-(\d+)")
_CASE_DEF = re.compile(r"^\| (C-\d+) \|")

#: 引用的"限定词"：`v2 §4.7` / `PLAN §3` / `W1 §8` / `ADR-0012 §5` 是**别份文档**的章节，不是自引。
_FOREIGN_DOC = re.compile(r"(?:v2|v3|PLAN|W\d|ADR-\d+)\s*$")

#: 显式豁免的 §：确非本文自引（键=编号，值=理由；新增必须写理由）。
EXTERNAL_SECTION_REFS: dict[str, str] = {
    "8.2": "§16 R4 引用外部审查原话「§8.2-9 不 bump」——指 W1 的 8.2，不是本文",
}

#: 不计入 §21「15 个质量门脚本」的 advisory 守卫（§21 G2 门禁分级：blocking / advisory / nightly）。
#: 条目必须在磁盘上存在——陈旧的豁免就是假绿，故 check_repo_counts 会验它。
ADVISORY_SCRIPTS: frozenset[str] = frozenset({"check_doc_cross_refs.py"})

#: §21 G2 行（坑①的扫描面）。
_G2_ROW_PREFIX = "| **G2"


def _mismatch(name: str, got: int, want: int, source: str) -> str:
    return f"count mismatch [{name}]: doc/repo says {got}, EXPECTED says {want} (source: {source})"


def _region(lines: list[str], start: str) -> list[str]:
    """取以 `start` 开头的标题到下一个同级/更高级标题之间的行（不含边界）。"""
    for i, line in enumerate(lines):
        if line.startswith(start):
            level = len(line) - len(line.lstrip("#"))
            out: list[str] = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("#") and (len(nxt) - len(nxt.lstrip("#"))) <= level:
                    break
                out.append(nxt)
            return out
    return []


def _find_table(lines: list[str], header_keys: tuple[str, ...]) -> list[list[str]]:
    """按表头关键字定位 markdown 表，返回数据行（已切成单元格）。找不到 → 空列表（由调用方判红）。"""
    for i, line in enumerate(lines):
        if not line.startswith("|") or not all(k in line for k in header_keys):
            continue
        if i + 1 >= len(lines) or not re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            continue
        rows: list[list[str]] = []
        for raw in lines[i + 2 :]:
            if not raw.startswith("|"):
                break
            rows.append([cell.strip() for cell in raw.strip().strip("|").split("|")])
        return rows
    return []


def _reserved_points(region: list[str]) -> tuple[int | None, list[str]]:
    """解析 §5.1「**预留 N 位**：`A`、`B`…。第 N 个是 `C`。」→ (声明数, 名字清单)。"""
    text = ""
    for i, line in enumerate(region):
        if "预留" in line and "位" in line:
            block = [line]
            for nxt in region[i + 1 :]:
                if not nxt.strip():
                    break
                block.append(nxt)
            text = "".join(block)
            break
    if not text:
        return None, []
    declared_match = re.search(r"预留\s*(\d+)\s*位", text)
    declared = int(declared_match.group(1)) if declared_match else None
    body = re.split(r"\*\*[：:]", text, maxsplit=1)
    body_text = body[1] if len(body) > 1 else text
    names: list[str] = []
    tick = chr(96)
    for piece in body_text.split("、"):
        lead = re.match(rf"^\s*{tick}([A-Za-z][A-Za-z0-9]*){tick}", piece)
        if lead and lead.group(1) not in names:
            names.append(lead.group(1))
    fifth = re.search(rf"第\s*(\d+)\s*个是\s*{tick}([A-Za-z][A-Za-z0-9]*){tick}", text)
    if fifth and fifth.group(2) not in names:
        names.append(fifth.group(2))
    return declared, names


def _declared(lines: list[str], prefix: str, pattern: str) -> int | None:
    """取指定标题行里的**声明数字**（标题写 19 条，表就必须有 19 行）。"""
    for line in lines:
        if line.startswith(prefix) and (match := re.search(pattern, line)):
            return int(match.group(1))
    return None


def check_doc_counts(lines: list[str], expected: dict[str, int]) -> list[str]:
    """A（文档侧）：§0 取舍 / §13 刀 / §5.1 点位，且**标题声明数**必须等于表行数。"""
    out: list[str] = []
    takeaways = sum(1 for line in lines if re.match(r"^\| T\d+ \|", line))
    if takeaways != expected["takeaways"]:
        out.append(_mismatch("takeaways", takeaways, expected["takeaways"], "§0"))
    declared_takeaways = _declared(lines, "## 0.", r"(\d+)\s*条取舍")
    if declared_takeaways is not None and declared_takeaways != takeaways:
        out.append(f"§0 title declares {declared_takeaways} 条取舍 but the table has {takeaways} T rows")

    blades = sum(1 for line in lines if re.match(r"^\| \*\*B", line))
    if blades != expected["blades"]:
        out.append(_mismatch("blades", blades, expected["blades"], "§13/T16"))
    declared_blades = _declared(lines, "## 13.", r"(\d+)\s*刀")
    if declared_blades is not None and declared_blades != blades:
        out.append(f"§13 title declares {declared_blades} 刀 but the table has {blades} B rows")

    points = _region(lines, "### 5.1")
    live = sum(1 for line in points if re.match(r"^\| \d+ \|", line))
    if live != expected["points_live"]:
        out.append(_mismatch("points_live", live, expected["points_live"], "§5.1"))
    declared, names = _reserved_points(points)
    if not points:
        out.append("missing section: §5.1 (封闭名单) not found — reserved/live points unparseable")
    else:
        declared_live = _declared(points, "### 5.1", r"(\d+)\s*个生效")
        declared_reserved = _declared(points, "### 5.1", r"(\d+)\s*个预留")
        if declared_live is not None and declared_live != live:
            out.append(f"§5.1 title declares {declared_live} 个生效 but the table has {live} rows")
        if declared_reserved is not None and declared_reserved != (declared if declared is not None else -1):
            out.append(f"§5.1 title declares {declared_reserved} 个预留 but the sentence lists {declared}")
        cap = _declared(points, "### 5.1", r"上限\s*(\d+)")
        if cap is not None and cap != live + len(names):
            out.append(f"§5.1 上限 {cap} != {live} 生效 + {len(names)} 预留（G3：封顶必须自洽）")
        if declared != len(names):
            out.append(f"§5.1 reserved: header declares {declared} but lists {len(names)} names {names}")
        elif len(names) != expected["points_reserved"]:
            out.append(_mismatch("points_reserved", len(names), expected["points_reserved"], "§5.1"))
    return out


def _boundaries_gate_steps(workflow: Path) -> tuple[list[str], list[str]]:
    """解析 ci-python.yml 的 `boundaries` job，返回 (blocking 门步名, advisory 步名)。

    口径说明（一轮实测）：§21「boundaries 实串 17 步」数的是**blocking 门步**，不是 step 总数。
    实测该 job = 3 个 `uses:`（checkout/setup-uv/setup-node）+ `uv sync` + 17 个 blocking 门步
    + advisory 步（`continue-on-error: true`，本守卫自己就是第一个）。
    所以字面执行「step 数 − Setup Node」得 20（加上本步是 21），会误判；三个 `uses:` 是环境装配、
    `uv sync` 是安装、advisory 是分级门禁（§21 G2）—— 三者都不计入「门步」。
    """
    lines = fail_on_empty(f"workflow lines in {workflow}", read_text(workflow).splitlines())
    start = next((i for i, line in enumerate(lines) if re.match(r"^  boundaries:\s*$", line)), None)
    if start is None:
        print(f"CONFIG: fail-on-empty: no `boundaries:` job in {workflow}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    block: list[str] = []
    for line in lines[start + 1 :]:
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            break
        block.append(line)
    steps: list[list[str]] = []
    for line in block:
        if re.match(r"^ {6}- ", line):
            steps.append([line])
        elif steps:
            steps[-1].append(line)
    blocking: list[str] = []
    advisory: list[str] = []
    for step in steps:
        body = "\n".join(step)
        if not re.search(r"^\s+run:", body, re.MULTILINE):
            continue  # uses: 环境装配
        if "uv sync" in body:
            continue  # 依赖安装，不产生判据
        head = step[0]
        name = head.split("name:", 1)[1].strip() if "name:" in head else head.strip()
        if re.search(r"^\s+continue-on-error:\s*true", body, re.MULTILINE):
            advisory.append(name)
        else:
            blocking.append(name)
    return blocking, advisory


def check_repo_counts(root: Path, expected: dict[str, int]) -> list[str]:
    """A（仓库侧）：src .py / 门脚本 / CI 门步 / reduce 调用点 / 测试文件分布。"""
    out: list[str] = []
    src_files = fail_on_empty(f"python files under {root / 'src'}", walk_py(root / "src"))
    if len(src_files) != expected["src_py"]:
        out.append(_mismatch("src_py", len(src_files), expected["src_py"], "§21"))

    scripts = [p for p in (root / "scripts").glob("*.py") if p.name.startswith(("check_", "verify_"))]
    fail_on_empty("advisory scripts declared", [p for p in scripts if p.name in ADVISORY_SCRIPTS])
    gates = fail_on_empty("quality-gate scripts in scripts/", [p for p in scripts if p.name not in ADVISORY_SCRIPTS])
    if len(gates) != expected["gate_scripts"]:
        out.append(_mismatch("gate_scripts", len(gates), expected["gate_scripts"], "§21"))

    steps, advisory = _boundaries_gate_steps(root / ".github" / "workflows" / "ci-python.yml")
    if len(steps) != expected["ci_gate_steps"]:
        out.append(_mismatch("ci_gate_steps", len(steps), expected["ci_gate_steps"], "§21/PLAN SCAN-1"))
    fail_on_empty("boundaries advisory steps", advisory)

    reduce_files = [root / "src" / "questor" / "kernel" / "loop.py", root / "src" / "questor" / "kernel" / "recovery.py"]
    fail_on_empty("reduce() call-site files", [p for p in reduce_files if p.exists()])
    reduce_calls = 0
    for path in reduce_files:
        for line in read_text(path).splitlines():
            stripped = line.strip()
            if stripped.startswith(("def ", "async def ", "import ", "from ")):
                continue
            if re.search(r"(^|[^._a-zA-Z])reduce\(", line):
                reduce_calls += 1
    if reduce_calls != expected["reduce_calls"]:
        out.append(_mismatch("reduce_calls", reduce_calls, expected["reduce_calls"], "§2-1"))

    tests = root / "tests"
    total = len(fail_on_empty(f"python files under {tests}", walk_py(tests)))
    buckets = {
        "test_unit": len(list(walk_py(tests / "unit"))),
        "test_integration": len(list(walk_py(tests / "integration"))),
        "test_support": len(list(walk_py(tests / "support"))),
        "test_evals": len(list(walk_py(tests / "evals"))),
        "test_root": len(list((tests).glob("*.py"))),
    }
    if total != expected["test_files"]:
        out.append(_mismatch("test_files", total, expected["test_files"], "PLAN SCAN-2"))
    for key, got in buckets.items():
        if got != expected[key]:
            out.append(_mismatch(key, got, expected[key], "PLAN SCAN-2"))
    if sum(buckets.values()) != total:
        out.append(
            f"count mismatch [test_buckets]: buckets sum {sum(buckets.values())} != total {total} "
            "(new tests directory? add a bucket + EXPECTED key)"
        )
    return out


def _definitions(lines: list[str]) -> tuple[set[str], set[str]]:
    """收集文内定义：章节号（含标题里 `（§19）` 这类）+ 附录字母/子节。"""
    sections: set[str] = set()
    appx: set[str] = set()
    for line in lines:
        match = _SEC_DEF.match(line)
        if match:
            sections.add(match.group(1))
        if line.startswith("#"):
            sections.update(_SEC_DEF_IN_HEADING.findall(line))
            letter = _APPX_DEF.match(line)
            if letter:
                appx.add(letter.group(1))
            sub = _APPX_SUB_DEF.match(line)
            if sub:
                appx.add(sub.group(1))
    return sections, appx


def check_refs(lines: list[str]) -> list[str]:
    """B：正文引用必须文内有定义（外部文档引用显式豁免，且豁免要写理由）。"""
    sections, appx = _definitions(lines)
    blades = {match.group(1) for line in lines if (match := _BLADE_DEF.match(line))}
    cases = {match.group(1) for line in lines if (match := _CASE_DEF.match(line))}
    out: list[str] = []
    for lineno, line in enumerate(lines, 1):
        for match in _SEC_REF.finditer(line):
            ref = match.group(1)
            prefix = line[max(0, match.start() - 12) : match.start()]
            if _FOREIGN_DOC.search(prefix) or ref in EXTERNAL_SECTION_REFS:
                continue
            if ref not in sections:
                out.append(f"dangling reference at L{lineno}: §{ref} has no heading definition")
        for match in _APPX_REF.finditer(line):
            key = match.group(1) + (f".{match.group(2)}" if match.group(2) else "")
            if key not in appx:
                out.append(f"dangling reference at L{lineno}: 附录 {key} has no heading definition")
        for match in _BLADE_REF.finditer(line):
            ref = f"B{match.group(1)}"
            if ref not in blades:
                out.append(f"dangling reference at L{lineno}: {ref} is not a 刀次 row in §13")
        for match in _CASE_REF.finditer(line):
            ref = f"C-{match.group(1)}"
            if ref not in cases:
                out.append(f"dangling reference at L{lineno}: {ref} is not a row in §20.3")
    return out


def check_pairs(lines: list[str]) -> list[str]:
    """C：§15.6 / §20.3 每行都要同时有"原写"侧与"已改"侧。"""
    out: list[str] = []
    errata = _find_table(lines, ("原写", "实测"))
    if not errata:
        out.append("missing table: §15.6 (原写/实测/状态) not found — pairing unverifiable")
    for row in errata:
        if len(row) != 4:
            out.append(f"§15.6 row has {len(row)} cells (want 4: 错位/原写/实测/状态): {' | '.join(row)}")
        elif not _PAIR_STATUS_OK.search(row[-1]):
            out.append(f"§15.6 row lost its 已改/已标 status marker: {' | '.join(row)}")
    decisions = _find_table(lines, ("冲突", "裁决"))
    if not decisions:
        out.append("missing table: §20.3 (冲突/裁决/代价) not found — pairing unverifiable")
    for row in decisions:
        if len(row) != 4:
            out.append(f"§20.3 row has {len(row)} cells (want 4: #/冲突/裁决/代价): {' | '.join(row)}")
            continue
        if not _PAIR_CONFLICT_OK.search(row[1]):
            out.append(f"§20.3 row lost its 原写 side (vs/自纠/重叠): {' | '.join(row)}")
        if not _PAIR_DECISION_OK.search(row[2]):
            out.append(f"§20.3 row lost its 裁决 side (采/删/加/澄清/同判/不在/已改/按…): {' | '.join(row)}")
    return out


def check_veto(lines: list[str]) -> list[str]:
    """D：PLAN §3 否决词出现时必须同句标注（C-\\d|已改|不建|不拆|仅借）。"""
    out: list[str] = []
    for lineno, line in enumerate(lines, 1):
        hits = _VETO.findall(line)
        if hits and not _VETO_OK.search(line):
            out.append(f"unqualified veto keyword at L{lineno} ({'/'.join(sorted(set(hits)))}): needs C-\\d|已改|不建|不拆|仅借")
    return out


def check_traps(lines: list[str]) -> list[str]:
    """两个已实测坑的 scoped 断言（正则见文件头 ①②）。"""
    out: list[str] = []
    for lineno, line in enumerate(lines, 1):
        if line.startswith(_G2_ROW_PREFIX) and _TRAP_SELF_WALK.search(line):
            out.append(
                f"L{lineno}: §21 G2 claims `各自 os.walk`; 实测 scripts/ 全用 `Path.rglob` "
                "(坑①: 该正则只许在 G2 行用，裸搜全文会误伤 §15.5.1/§16)"
            )
    for line in _region(lines, "## 4."):
        if _TRAP_STALE_UNIT.search(line):
            out.append(
                f"§4 still carries the stale `unit 83` count: {line.strip()[:80]} "
                "(坑②: 勘误记录「83→107」本身含该字样，故只扫 §4 且用 `unit\\s*\\*{0,2}83`)"
            )
    return out


def collect_notices(lines: list[str], root: Path) -> list[str]:
    """不判红的漂移观察（`NOTE:` 前缀）：文档作业待办，不该阻塞本轮代码。"""
    out: list[str] = []
    kit = root / "scripts" / "_guard_kit.py"
    for lineno, line in enumerate(lines, 1):
        if line.startswith(_G2_ROW_PREFIX) and "不存在" in line and kit.exists():
            out.append(
                f"NOTE: L{lineno}: §21 G2 仍写「`scripts/_guard_kit.py` 不存在」，但本轮已落地该文件 "
                "（且 boundaries 已多 1 个 advisory 步）——属文档作业，本轮只读不修"
            )
    return out


def check_all(text: str, root: Path, expected: dict[str, int]) -> list[str]:
    """跑全部四项检查 + 两个坑的 scoped 断言；返回违规行（空 = 绿）。"""
    lines = text.splitlines()
    violations: list[str] = []
    violations += check_doc_counts(lines, expected)
    violations += check_repo_counts(root, expected)
    violations += check_refs(lines)
    violations += check_pairs(lines)
    violations += check_veto(lines)
    violations += check_traps(lines)
    return violations


#: --self-test 的合成文档：结构最小但四项检查全可验证（含 §19/附录A/B 刀/C 条的定义位）。
FIXTURE_DOC = """# fixture

## 0. 定夺的 2 条取舍

| # | 取舍 |
|---|---|
| T1 | a |
| T2 | b |

## 4. 运行时底座

### 4.4 咽喉

见 §5.1 与 §20 C-1，另见附录 A。

## 5. 扩展面

### 5.1 封闭名单：2 个生效 + 2 个预留

| # | 具名点 |
|---|---|
| 1 | A |
| 2 | B |

**预留 2 位（启用需 ADR）**：`Stop`、`Notification`。

## 13. 迁移计划：2 刀

| 刀 | 内容 |
|---|---|
| **B1** | x |
| **B2** | y |

### 15.6 锚点勘误表

| 错位 | 原写 | 实测 | 状态 |
|---|---|---|---|
| a | old | new | ✅ 已改 |
| b | old | new | ✅ 已标 |

## 20. 互锁与冲突裁决

### 20.3 冲突裁决

| # | 冲突 | 裁决 | 代价 |
|---|---|---|---|
| C-1 | PLAN 否决 x vs 本文 y | **采 PLAN**：已改 §4.4 | 零 |

## 附录 A（§19）· 台账

### A.1 两个真实缺口

1. 见 §4.4 与 B1。
"""


def self_test() -> int:
    """四种植入反例各判红一次；另证 fixture 基线为绿（否则"能判红"无意义）。"""
    base = dict(EXPECTED, takeaways=2, blades=2, points_live=2, points_reserved=2)
    cases: list[tuple[str, bool, str]] = []

    green = check_all(FIXTURE_DOC, ROOT, base)
    cases.append(("fixture-green", not green, f"{len(green)} violations: {green[:2]}"))

    mutated_expected = dict(base, takeaways=3)
    hits = check_all(FIXTURE_DOC, ROOT, mutated_expected)
    print(f"  expected-red -> {hits[0] if hits else '(none)'}")
    cases.append(("counts-mutation", any("takeaways" in h for h in hits), f"{len(hits)} hit(s)"))

    dropped_def = FIXTURE_DOC.replace("### 4.4 咽喉", "")
    hits = check_all(dropped_def, ROOT, base)
    print(f"  expected-red -> {hits[0] if hits else '(none)'}")
    cases.append(("refs-deletion", any("§4.4" in h for h in hits), f"{len(hits)} hit(s)"))

    split_pair = FIXTURE_DOC.replace("| ✅ 已改 |", "| — |")
    hits = check_all(split_pair, ROOT, base)
    print(f"  expected-red -> {hits[0] if hits else '(none)'}")
    cases.append(("pair-split", any("§15.6" in h for h in hits), f"{len(hits)} hit(s)"))

    bare_veto = FIXTURE_DOC + "\n- 已否决 QueueHandler 异步日志。\n"
    hits = check_all(bare_veto, ROOT, base)
    print(f"  expected-red -> {hits[0] if hits else '(none)'}")
    cases.append(("veto-bare", any("QueueHandler" in h for h in hits), f"{len(hits)} hit(s)"))

    g2_walk = FIXTURE_DOC + "| **G2 守卫可膨胀性** | 仍是各自 os.walk 实现 |\n"
    hits = check_all(g2_walk, ROOT, base)
    print(f"  expected-red -> {hits[0] if hits else '(none)'}")
    cases.append(("trap-g2-oswalk", any("G2" in h for h in hits), f"{len(hits)} hit(s)"))

    stale_unit = FIXTURE_DOC.replace("## 4. 运行时底座", "## 4. 运行时底座\n\nunit 83 是旧口径。")
    hits = check_all(stale_unit, ROOT, base)
    print(f"  expected-red -> {hits[0] if hits else '(none)'}")
    cases.append(("trap-unit83", any("unit 83" in h for h in hits), f"{len(hits)} hit(s)"))

    return run_self_test(cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC, help="设计文档路径（默认 ../questor目标形态设计.md 相对 questor/）")
    parser.add_argument("--root", type=Path, default=ROOT, help="仓库根（默认本脚本所在仓）")
    parser.add_argument("--self-test", action="store_true", help="证明四种反例都能判红")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    doc = args.doc if args.doc.is_absolute() else (Path.cwd() / args.doc)
    if not doc.exists():
        print("SKIP: doc not present")
        return EXIT_OK
    text = read_text(doc)
    fail_on_empty(f"lines in {doc}", text.splitlines())
    for note in collect_notices(text.splitlines(), args.root):
        print(note)
    violations = check_all(text, args.root, EXPECTED)
    for message in violations:
        print(message, file=sys.stderr)
    if violations:
        return EXIT_RED
    print(f"doc cross-refs: counts/refs/pairs/veto consistent ({len(text.splitlines())} lines, 9 EXPECTED items)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
