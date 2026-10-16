"""POSIX shell parser bypass corpus（T6）。

所有 expected 值都是 *安全语义*，不是输出格式偏好：
- `read_only`：parser 能完整证明无写副作用。
- `ask`：已证明有写/破坏性，必须由 HITL 裁决。
- `not_proven`：未识别、动态或不可解析，绝不能自动 allow。
"""

from __future__ import annotations

import pytest

from questor.contracts.shell_analysis import ShellDialect, ShellParseStatus
from questor.kernel.shell_parse_posix import parse_posix_shell


def _category(analysis) -> str:  # noqa: ANN001
    if analysis.status is not ShellParseStatus.PARSED or analysis.dynamic:
        return "not_proven"
    if analysis.segments and any(segment.destructive or segment.write_paths for segment in analysis.segments):
        return "ask"
    if analysis.all_read_only:
        return "read_only"
    return "not_proven"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ls", "read_only"),
        ("cat notes.md", "read_only"),
        ('grep "a|b" file.txt', "read_only"),
        ("sort -o out.txt in.txt", "ask"),
        ("wc -l file.txt", "read_only"),
        ("rm target", "ask"),
        ("rm -rf /", "ask"),
        ("rm  -rf /", "ask"),
        ("rm -r -f /", "ask"),
        ("rm --recursive --force /", "ask"),
        ("unlink secret", "ask"),
        ("mv a b", "ask"),
        ("cp a b", "ask"),
        ("find . -delete", "ask"),
        ("find . -exec rm {} ;", "ask"),
        ("sed -i 's/a/b/' file", "ask"),
        ("sed -e 'w out.txt' file", "ask"),
        ("xxd -r input output", "ask"),
        ('awk \'system("rm x")\' file', "not_proven"),
        ("env FOO=1 nohup rm -rf /", "ask"),
        ("timeout 5 rm -rf /", "ask"),
        ("nice -n 1 rm -rf /", "ask"),
        ("xargs rm", "ask"),
        ("setsid rm -rf /", "ask"),
        ("echo hello > out.txt", "ask"),
        ("echo hello >> out.txt", "ask"),
        ("echo hello >&2", "read_only"),
        ("echo hello > /dev/null", "read_only"),
        ("command substitution `rm -rf /`", "not_proven"),
        ("$(rm -rf /)", "not_proven"),
        ("<(rm -rf /)", "not_proven"),
        ("bash -c 'rm -rf /'", "not_proven"),
        ("sh -c 'rm -rf /'", "not_proven"),
        ("git branch feature", "ask"),
        ("git branch -l", "read_only"),
        ("git config user.name x", "ask"),
        ("git config --get user.name", "read_only"),
        ("git status", "read_only"),
        ("git push origin main", "not_proven"),
        ("git checkout main", "not_proven"),
        ("curl https://example.invalid", "not_proven"),
        ("wget https://example.invalid", "not_proven"),
        ("unknown-program --flag", "not_proven"),
        ("rm $TARGET", "not_proven"),
        ("$PROGRAM file", "not_proven"),
        ("rm -rf", "not_proven"),
    ],
)
def test_posix_parser_classifies_safety(command: str, expected: str) -> None:
    analysis = parse_posix_shell(command)
    assert analysis.dialect is ShellDialect.POSIX
    assert _category(analysis) == expected, analysis


def test_unparsable_unbalanced_quote_is_not_read_only() -> None:
    analysis = parse_posix_shell('cat "unclosed')
    assert analysis.status is ShellParseStatus.UNPARSABLE
    assert analysis.all_read_only is False


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # 短 flag 簇必须拆开：“同一命令的两种写法不得得出不同安全判定”。
        # `sed -ni` = `-n` + `-i`（in-place 写），旧实现拿整串比 flag → 误判只读。
        ("sed -ni 's/a/b/' file", "ask"),
        ("sed -i.bak 's/a/b/' file", "ask"),
        ("sort -bo out.txt in.txt", "ask"),
        # 不含写形式的簇不得误报：拆开后仍应是只读。
        ("sed -ne 'p' file", "read_only"),
        ("sort -bu in.txt", "read_only"),
        ("grep -rn TODO .", "read_only"),
        ("ls -laR .", "read_only"),
    ],
)
def test_bundled_short_flags_are_expanded(command: str, expected: str) -> None:
    assert _category(parse_posix_shell(command)) == expected, command


def test_same_semantics_regardless_of_flag_spacing() -> None:
    """拆开写与合并写必须同一判定——否则安全判定取决于用户敲不敲空格。"""
    assert _category(parse_posix_shell("sed -ni 's/a/b/' f")) == _category(parse_posix_shell("sed -n -i 's/a/b/' f"))
    assert _category(parse_posix_shell("sort -bo out in")) == _category(parse_posix_shell("sort -b -o out in"))
