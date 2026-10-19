"""#169：多命令 shell 分析任一未解析必须整体非只读（防 exec fail-open）。"""

from __future__ import annotations

from questor.capabilities.tools.bash import BashTool
from questor.contracts.shell_analysis import ShellParseStatus
from questor.kernel.loop import _analyze_shell


def test_multi_command_with_unparsed_tail_is_not_read_only() -> None:
    """首条只读、次条动态/未解析 → 整体不得判只读（exec 已接通，fail-open 现可达）。"""
    res = _analyze_shell(BashTool().spec, {"commands": ["ls", "cat $HOME/x"]})
    assert res is not None
    assert res.status is not ShellParseStatus.PARSED
    assert res.all_read_only is False


def test_all_parsed_read_only_still_read_only() -> None:
    """回归保护：全部只读且解析成功，仍应可被证明只读。"""
    res = _analyze_shell(BashTool().spec, {"commands": ["ls", "date"]})
    assert res is not None
    assert res.all_read_only is True
