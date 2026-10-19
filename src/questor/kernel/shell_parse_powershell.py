"""PowerShell → ShellAnalysis IR（ADR-0015/0017；T7）。

Windows 主平台不能用 POSIX parser 猜测 PowerShell。这里采用保守 dialect parser：
只证明已知 cmdlet/alias 的安全性；variable、scriptblock、call operator、encoded command、
pipeline 动态对象和未识别 cmdlet 一律 not proven。
"""

from __future__ import annotations

from collections.abc import Sequence

from questor.contracts.shell_analysis import (
    ShellAnalysis,
    ShellDialect,
    ShellParseStatus,
    ShellRedirect,
    ShellSegment,
)

_ALIASES = {
    "ls": "get-childitem",
    "dir": "get-childitem",
    "gci": "get-childitem",
    "cat": "get-content",
    "type": "get-content",
    "gc": "get-content",
    "rm": "remove-item",
    "del": "remove-item",
    "erase": "remove-item",
    "rmdir": "remove-item",
    "rd": "remove-item",
    "ri": "remove-item",
    "echo": "write-output",
    "ni": "new-item",
    "mi": "move-item",
    "mv": "move-item",
    "move": "move-item",
    "cp": "copy-item",
    "copy": "copy-item",
    "ci": "copy-item",
    "sc": "set-content",
    "ac": "add-content",
    "iex": "invoke-expression",
    "ipmo": "import-module",
}

_READ_ONLY = frozenset(
    {
        "get-childitem",
        "get-content",
        "get-item",
        "get-process",
        "get-service",
        "get-location",
        "get-command",
        "get-help",
        "write-output",
        "select-object",
        "sort-object",
        "measure-object",
        "format-table",
        "format-list",
    }
)

#: 写文件类参数：只读 cmdlet 带这些参数即不再是只读（`Sort-Object -OutputPath`、`Format-Table -OutFile` 等）。
_READ_ONLY_WRITE_PARAMS = frozenset(
    {
        "-outputpath",
        "-outfile",
        "-filepath",
        "-logfile",
        "-tafile",
        "-redirectstandardoutput",
        "-redirectstandarderror",
    }
)

_WRITE_COMMANDS = frozenset(
    {
        "remove-item",
        "set-content",
        "add-content",
        "out-file",
        "out-default",
        "move-item",
        "copy-item",
        "new-item",
        "rename-item",
        "clear-content",
        "remove-itemproperty",
    }
)

_DYNAMIC_COMMANDS = frozenset(
    {
        "invoke-expression",
        "invoke-command",
        "invoke-item",
        "invoke-webrequest",
        "invoke-restmethod",
        "start-process",
        "start-job",
        "start-threadjob",
        "cmd",
        "powershell",
        "pwsh",
        "wsl",
        "foreach-object",
        "where-object",
        "import-module",
        "set-variable",
        "new-object",
    }
)

_NULL_SINKS = frozenset({"$null", "nul", "NUL"})


def _dynamic(reason: str) -> ShellAnalysis:
    return ShellAnalysis(dialect=ShellDialect.POWERSHELL, status=ShellParseStatus.DYNAMIC, dynamic=True, actions={"reason": reason})


def _unparsable(reason: str) -> ShellAnalysis:
    return ShellAnalysis(dialect=ShellDialect.POWERSHELL, status=ShellParseStatus.UNPARSABLE, unparsable=True, actions={"reason": reason})


def _tokenize(text: str) -> list[str]:
    """PowerShell-aware tokenizer：single quote、double quote 与 backtick 转义。"""
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if quote == "'" and char == "'" and index + 1 < len(text) and text[index + 1] == "'":
                current.append("'")
                index += 2
                continue
            if char == quote:
                quote = None
                index += 1
                continue
            if quote == '"' and char == "`" and index + 1 < len(text):
                current.append(text[index + 1])
                index += 2
                continue
            current.append(char)
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            index += 1
            continue
        if char in {";", "|", "&", ">", "<", "{", "}"}:
            if current:
                tokens.append("".join(current))
                current = []
            if char == ">" and index + 1 < len(text) and text[index + 1] == ">":
                tokens.append(">>")
                index += 2
                continue
            tokens.append(char)
            index += 1
            continue
        current.append(char)
        index += 1
    if quote:
        raise ValueError("unterminated PowerShell quote")
    if current:
        tokens.append("".join(current))
    return tokens


def _split_on(tokens: Sequence[str], separator: str) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token == separator:
            chunks.append(current)
            current = []
        else:
            current.append(token)
    chunks.append(current)
    return chunks


def _is_dynamic_token(token: str) -> bool:
    return token.startswith("$") or token in {"{", "}", "&"} or "@" in token and token.startswith("@")


def _parse_command(tokens: Sequence[str]) -> ShellSegment | ShellAnalysis:
    if not tokens:
        return _dynamic("empty command")
    if any(_is_dynamic_token(token) for token in tokens):
        return _dynamic("PowerShell variable, scriptblock, or call operator")
    program_raw, args = tokens[0], list(tokens[1:])
    program = _ALIASES.get(program_raw.lower(), program_raw.lower())
    if program in _DYNAMIC_COMMANDS:
        return _dynamic(f"{program_raw} can execute dynamic input")
    if program not in _READ_ONLY and program not in _WRITE_COMMANDS:
        return _dynamic(f"unclassified PowerShell command {program_raw}")

    positional: list[str] = []
    flags: list[str] = []
    redirects: list[ShellRedirect] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in {">", ">>"}:
            if index + 1 >= len(args):
                return _dynamic("PowerShell redirect target missing")
            target = args[index + 1]
            null_sink = target in _NULL_SINKS
            redirects.append(ShellRedirect(target=target, append=token == ">>", null_sink=null_sink))
            index += 2
            continue
        if token.startswith("-"):
            flags.append(token)
            if token in {"-File", "-Path", "-LiteralPath", "-Destination", "-OutFile", "-Encoding", "-Credential", "-Command"}:
                if index + 1 < len(args) and not args[index + 1].startswith("-"):
                    positional.append(args[index + 1])
                    index += 2
                    continue
            index += 1
            continue
        positional.append(token)
        index += 1

    write_paths = tuple(redirect.target for redirect in redirects if not redirect.null_sink and not redirect.fd_dup)
    # 只读 cmdlet 也可带写文件参数（`Sort-Object -OutputPath`、`Format-Table -OutFile`、`Tee-Object -FilePath` 等）
    # → 不能证只读。命中即不证（#155：旧实现把这类参数值当 positional、整段误判只读）。
    flagset = {f.lower() for f in flags}
    if flagset & _READ_ONLY_WRITE_PARAMS:
        return _dynamic(f"{program_raw} writes via file-writing parameter")
    if program in _WRITE_COMMANDS:
        if not positional and not write_paths:
            return _dynamic(f"{program_raw} requires an explicit target")
        return ShellSegment(
            program=program_raw,
            args=tuple(args),
            write_paths=tuple(dict.fromkeys([*positional, *write_paths])),
            redirects=tuple(redirects),
            destructive=True,
        )

    if write_paths:
        return ShellSegment(
            program=program_raw,
            args=tuple(args),
            read_paths=tuple(positional),
            write_paths=write_paths,
            redirects=tuple(redirects),
            destructive=True,
        )

    return ShellSegment(
        program=program_raw,
        args=tuple(args),
        read_paths=tuple(positional),
        redirects=tuple(redirects),
        read_only=True,
    )


def parse_powershell(command: str) -> ShellAnalysis:
    """解析一条 PowerShell 命令串；不可证明的命令一律 DYNAMIC/UNPARSABLE。"""
    if not command or not command.strip():
        return _unparsable("empty command")
    try:
        tokens = _tokenize(command)
    except ValueError as exc:
        return _unparsable(str(exc))

    segments: list[ShellSegment] = []
    for statement in _split_on(tokens, ";"):
        if not statement:
            continue
        for pipeline_part in _split_on(statement, "|"):
            if not pipeline_part:
                return _dynamic("empty pipeline segment")
            parsed = _parse_command(pipeline_part)
            if isinstance(parsed, ShellAnalysis):
                return parsed
            segments.append(parsed)

    read_paths = tuple(dict.fromkeys(path for segment in segments for path in segment.read_paths))
    write_paths = tuple(dict.fromkeys(path for segment in segments for path in segment.write_paths))
    return ShellAnalysis(
        dialect=ShellDialect.POWERSHELL,
        status=ShellParseStatus.PARSED,
        segments=tuple(segments),
        read_paths=read_paths,
        write_paths=write_paths,
    )


__all__ = ["parse_powershell"]
