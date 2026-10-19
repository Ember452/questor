"""PowerShell parser safety corpus（ADR-0017；T7）。

Windows 是本项目一等平台；这里不追求完整 PowerShell grammar，而是证明任何无法分类/动态输入
都不能被标成 read-only。
"""

from __future__ import annotations

import pytest

from questor.contracts.shell_analysis import ShellDialect, ShellParseStatus
from questor.kernel.shell_parse_powershell import parse_powershell


def _category(analysis) -> str:  # noqa: ANN001
    if analysis.status is not ShellParseStatus.PARSED or analysis.dynamic:
        return "not_proven"
    if any(segment.destructive or segment.write_paths for segment in analysis.segments):
        return "ask"
    return "read_only" if analysis.all_read_only else "not_proven"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("Get-ChildItem .", "read_only"),
        ("ls .", "read_only"),
        ("dir", "read_only"),
        ("Get-Content notes.md", "read_only"),
        ("cat notes.md", "read_only"),
        ("gc notes.md", "read_only"),
        ("type notes.md", "read_only"),
        ("Get-Process", "read_only"),
        ("Write-Output hello", "read_only"),
        ("Get-ChildItem . > out.txt", "ask"),
        ("Remove-Item -Recurse -Force target", "ask"),
        ("rm -Recurse -Force target", "ask"),
        ("del /s /q target", "ask"),
        ("erase target", "ask"),
        ("rd /s /q target", "ask"),
        ("rmdir /s /q target", "ask"),
        ("ri -Force target", "ask"),
        ("Set-Content out.txt value", "ask"),
        ("Add-Content out.txt value", "ask"),
        ("Out-File out.txt", "ask"),
        ("Move-Item a b", "ask"),
        ("Copy-Item a b", "ask"),
        ("New-Item file.txt", "ask"),
        ("Invoke-Expression 'Get-Process'", "not_proven"),
        ("iex 'Get-Process'", "not_proven"),
        ("& { Remove-Item x }", "not_proven"),
        ("& $program file", "not_proven"),
        ("Start-Process cmd", "not_proven"),
        ("powershell -EncodedCommand ZQBjAGgAbwA=", "not_proven"),
        ("powershell -Command 'Remove-Item x'", "not_proven"),
        ("powershell -File script.ps1", "not_proven"),
        ("cmd /c del file", "not_proven"),
        ("Some-UnknownCmdlet", "not_proven"),
        ("$x = 1; Remove-Item $x", "not_proven"),
        ("Remove-Item", "not_proven"),
        ("Get-ChildItem | ForEach-Object { Remove-Item $_ }", "not_proven"),
        # #155：只读 cmdlet 带写文件参数，不得再判只读。
        ("Get-ChildItem | Sort-Object Name -OutputPath C:\\Temp\\pwn.txt", "not_proven"),
        ("Get-Process | Format-Table -OutFile C:\\pwn.txt", "not_proven"),
        ("Sort-Object -OutputPath out.txt", "not_proven"),
        # 不得误伤：不带写参数的只读命令仍 read_only。
        ("Get-ChildItem | Sort-Object Name", "read_only"),
    ],
)
def test_powershell_parser_classifies_safety(command: str, expected: str) -> None:
    analysis = parse_powershell(command)
    assert analysis.dialect is ShellDialect.POWERSHELL
    assert _category(analysis) == expected, analysis


def test_unbalanced_quote_is_unparsable() -> None:
    analysis = parse_powershell("Get-Content 'unclosed")
    assert analysis.status is ShellParseStatus.UNPARSABLE
    assert analysis.all_read_only is False
