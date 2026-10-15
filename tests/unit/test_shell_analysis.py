"""Shell IR 安全分类不变式。"""

from __future__ import annotations

import pytest

from questor.contracts.shell_analysis import (
    ShellAnalysis,
    ShellDialect,
    ShellParseStatus,
    ShellRedirect,
    ShellSegment,
)


def test_unparsed_analysis_cannot_claim_read_paths() -> None:
    with pytest.raises(ValueError, match="unparsed shell analysis"):
        ShellAnalysis(
            dialect=ShellDialect.POSIX,
            status=ShellParseStatus.UNPARSABLE,
            unparsable=True,
            read_paths=("safe.txt",),
        )


def test_segment_cannot_mark_write_segment_read_only() -> None:
    with pytest.raises(ValueError, match="read_only"):
        ShellSegment(
            program="rm",
            write_paths=("target",),
            read_only=True,
        )


def test_all_read_only_requires_complete_parsed_segments() -> None:
    analysis = ShellAnalysis(
        dialect=ShellDialect.POWERSHELL,
        status=ShellParseStatus.PARSED,
        segments=(
            ShellSegment(program="Get-ChildItem", read_paths=("x",), read_only=True),
            ShellSegment(
                program="Out-File",
                write_paths=("y",),
                redirects=(ShellRedirect(target="y", append=True),),
            ),
        ),
    )
    assert analysis.all_read_only is False
    assert analysis.dynamic is True
