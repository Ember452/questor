"""L0 Shell 分析 IR（ADR-0015/ADR-0017；HARD C8/C9）。

解析器把不同 shell dialect 转成同一结构化事实；权限层只消费 IR，不依赖具体 shell 文本。
未识别、动态执行和无法证明只读必须显式表达，不能默认安全。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from questor.contracts.common import JsonObject, freeze


class ShellDialect(StrEnum):
    """支持的 shell 语法族；PowerShell 不借用 POSIX 语义。"""

    POSIX = "posix"
    POWERSHELL = "powershell"


class ShellParseStatus(StrEnum):
    """解析结果。非 PARSED 一律不可自动归类 read-only。"""

    PARSED = "parsed"
    UNPARSABLE = "unparsable"
    DYNAMIC = "dynamic"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ShellRedirect:
    """单个 redirect 目标；fd dup/NULL sink 不冒充写路径。"""

    target: str
    append: bool = False
    fd_dup: bool = False
    null_sink: bool = False


@dataclass(frozen=True, slots=True)
class ShellSegment:
    """一条管道/序列中的单个程序调用。"""

    program: str
    args: tuple[str, ...] = ()
    read_paths: tuple[str, ...] = ()
    write_paths: tuple[str, ...] = ()
    redirects: tuple[ShellRedirect, ...] = ()
    read_only: bool | None = None
    destructive: bool = False
    dynamic: bool = False
    git_subcommand: str | None = None

    def __post_init__(self) -> None:
        if not self.program.strip():
            raise ValueError("ShellSegment.program is required")
        # parser 不能把“未证明只读”伪装成 False/True 之外的第三态；True 必须有充分事实。
        if self.read_only is True and (self.dynamic or self.destructive or self.write_paths):
            raise ValueError("dynamic/destructive/write segment cannot be marked read_only")


@dataclass(frozen=True, slots=True)
class ShellAnalysis:
    """一条 shell 命令的安全相关结构化摘要。"""

    dialect: ShellDialect
    status: ShellParseStatus
    segments: tuple[ShellSegment, ...] = ()
    read_paths: tuple[str, ...] = ()
    write_paths: tuple[str, ...] = ()
    dynamic: bool = False
    unparsable: bool = False
    actions: JsonObject = field(default_factory=dict)

    @property
    def all_read_only(self) -> bool:
        """只有完整 PARSED 且每个 segment 都被证明只读，调用方才可能自动 allow。"""
        return self.status is ShellParseStatus.PARSED and bool(self.segments) and all(
            segment.read_only is True for segment in self.segments
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", freeze(self.actions))
        if self.status is not ShellParseStatus.PARSED:
            if self.read_paths or self.segments:
                raise ValueError("unparsed shell analysis cannot carry claimed safe paths")
            if self.unparsable != (self.status is ShellParseStatus.UNPARSABLE):
                raise ValueError("unparsable flag must match status")
            if self.dynamic != (self.status is ShellParseStatus.DYNAMIC):
                raise ValueError("dynamic flag must match status")
            return
        object.__setattr__(
            self,
            "dynamic",
            self.dynamic or any(segment.dynamic for segment in self.segments),
        )
        if not self.read_paths:
            object.__setattr__(self, "read_paths", tuple(dict.fromkeys(path for segment in self.segments for path in segment.read_paths)))
        if not self.write_paths:
            object.__setattr__(self, "write_paths", tuple(dict.fromkeys(path for segment in self.segments for path in segment.write_paths)))


__all__ = ["ShellAnalysis", "ShellDialect", "ShellParseStatus", "ShellRedirect", "ShellSegment"]
