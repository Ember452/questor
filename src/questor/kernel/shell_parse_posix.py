"""POSIX shell → ShellAnalysis IR（ADR-0015/0017；T6）。

纯函数、无 IO/subprocess。目标不是“理解所有 shell”，而是把能被证明安全的命令与
动态、未识别、不可解析或破坏性命令严格分开。任何不能证明 read_only 的结果都不得自动 allow。

分隔/unwrap 表在本仓以 dialect-tagged IR 重新实现，不沿用外部返回语义。
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence

from questor.contracts.shell_analysis import (
    ShellAnalysis,
    ShellDialect,
    ShellParseStatus,
    ShellRedirect,
    ShellSegment,
)
from questor.contracts.tool_args import NULL_SINKS

_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "|&", "\n"})
_BACKTICK_RE = re.compile(r"(?<!\\)`([^`]*)`")
_COMMAND_SUB_RE = re.compile(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
_PROCESS_SUB_RE = re.compile(r"([<>])\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
_WRAPPERS = frozenset({"env", "nohup", "time", "timeout", "nice", "xargs", "setsid"})
_INTERPRETERS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "eval", "exec"})
_DYNAMIC_PROGRAMS = frozenset(
    {
        "awk",
        "perl",
        "python",
        "python2",
        "python3",
        "node",
        "ruby",
        "php",
        "curl",
        "wget",
        "docker",
        "sudo",
        "doas",
        "su",
        "ssh",
        "tar",
        "zip",
        "unzip",
        "rsync",
        "scp",
    }
)
_WRITE_PROGRAMS = frozenset({"rm", "unlink", "mv", "cp", "tee", "truncate", "dd", "ln", "install", "patch", "xargs"})
_READ_ONLY_PROGRAMS = frozenset(
    {
        "ls",
        "ll",
        "cat",
        "bat",
        "head",
        "tail",
        "nl",
        "wc",
        "less",
        "more",
        "tree",
        "file",
        "stat",
        "du",
        "df",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "pwd",
        "echo",
        "printf",
        "which",
        "type",
        "whereis",
        "locate",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "ag",
        "ack",
        "fd",
        "find",
        "diff",
        "cmp",
        "jq",
        "yq",
        "xxd",
        "od",
        "strings",
        "fold",
        "rev",
        "expand",
        "unexpand",
        "md5",
        "md5sum",
        "sha1sum",
        "sha256sum",
        "shasum",
        "cksum",
        "date",
        "cal",
        "whoami",
        "id",
        "groups",
        "hostname",
        "uname",
        "locale",
        "uptime",
        "ps",
        "free",
        "vm_stat",
        "sysctl",
        "lsof",
        "netstat",
        "ifconfig",
        "ip",
        "dig",
        "nslookup",
        "host",
        "sw_vers",
        "arch",
        "true",
        "false",
        "test",
        "seq",
        "sleep",
        "tty",
        "sort",
        "sed",
    }
)
_GIT_READ_ONLY = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "ls-files",
        "ls-tree",
        "ls-remote",
        "rev-parse",
        "rev-list",
        "describe",
        "blame",
        "shortlog",
        "cat-file",
        "reflog",
        "grep",
        "whatchanged",
        "name-rev",
        "symbolic-ref",
        "count-objects",
        "verify-commit",
        "version",
        "help",
    }
)
_GIT_DYNAMIC = frozenset({"push", "pull", "fetch", "clone", "checkout", "switch", "rebase", "merge", "reset", "restore", "clean", "stash", "worktree", "notes"})
_WRITE_FORM_FLAGS = {
    "find": frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint", "-fprintf", "-fprint0"}),
    "sort": frozenset({"-o", "--output"}),
    "xxd": frozenset({"-r", "--recover", "--revers.seek"}),
    "sed": frozenset({"-i", "--in-place"}),
}


def _dynamic(reason: str = "dynamic or unproven shell input") -> ShellAnalysis:
    """动态/未识别命令：不携带“安全路径”声明，只保留拒绝理由。"""
    return ShellAnalysis(
        dialect=ShellDialect.POSIX,
        status=ShellParseStatus.DYNAMIC,
        dynamic=True,
        actions={"reason": reason},
    )


def _unparsable(reason: str) -> ShellAnalysis:
    return ShellAnalysis(
        dialect=ShellDialect.POSIX,
        status=ShellParseStatus.UNPARSABLE,
        unparsable=True,
        actions={"reason": reason},
    )


def _extract_substitutions(text: str) -> tuple[str, list[str]]:
    bodies: list[str] = []

    def _record(pattern: re.Pattern[str]) -> None:
        nonlocal text

        def _replace(match: re.Match[str]) -> str:
            bodies.append(match.group(1))
            return "\x00"

        text = pattern.sub(_replace, text)

    _record(_BACKTICK_RE)
    _record(_COMMAND_SUB_RE)
    _record(_PROCESS_SUB_RE)
    return text, bodies


def _is_path_dynamic(token: str) -> bool:
    return "$" in token or "`" in token or "\x00" in token


def _flag_forms(token: str) -> frozenset[str]:
    """一个 flag 的**全部可能形式**：整串、长选项去 `=value`、短簇逐字符。

    `sed -ni` 是 `-n` + `-i`（in-place 写），`-i.bak` 是带附着值的 `-i`；只比对整串会
    把两者都归成“非写形式”，而拆开写（`-n -i`）却被识别——安全判定不得取决于用户
    敲不敲空格。方向是宁多拆不误放：多拆只会多要一次审批（ask），不拆则可能静默改写文件。
    """
    forms = {token}
    if token.startswith("--"):
        forms.add(token.split("=", 1)[0])
        return frozenset(forms)
    if token.startswith("-") and len(token) > 2:
        body = token[1:].split("=", 1)[0]
        forms.add(f"-{body}")  # -i.bak -> -i（单字母 + 附着值）
        forms.update(f"-{char}" for char in body if char.isalpha())  # -ni -> -n -i
    return frozenset(forms)


def _unwrap(tokens: Sequence[str]) -> tuple[str | None, tuple[str, ...]]:
    if not tokens:
        return None, ()
    program = tokens[0].lower()
    args = tokens[1:]
    if program == "env":
        index = 0
        while index < len(args) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[index]) or args[index].startswith("-")):
            index += 1
        return _unwrap(args[index:])
    if program in {"nohup", "setsid"}:
        index = 0
        while index < len(args) and args[index].startswith("-"):
            index += 1
        return _unwrap(args[index:])
    if program == "time":
        index = 0
        while index < len(args) and args[index].startswith("-"):
            index += 1
        return _unwrap(args[index:])
    if program == "timeout":
        index = 0
        while index < len(args):
            if args[index].startswith("-"):
                index += 1
                if index < len(args) and args[index - 1] in {"-s", "--signal", "-k", "--kill-after"}:
                    index += 1
                continue
            if re.match(r"^\d+(\.\d+)?[smhd]?$", args[index]):
                index += 1
                continue
            break
        return _unwrap(args[index:])
    if program == "nice":
        index = 0
        while index < len(args) and (args[index].startswith("-") or args[index].lstrip("-+").isdigit()):
            index += 1
        return _unwrap(args[index:])
    return program, tuple(args)


def _split_sequences(tokens: Sequence[str]) -> list[list[str]]:
    result: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if current:
                result.append(current)
                current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def _parse_segment(tokens: Sequence[str]) -> ShellSegment | ShellAnalysis:
    program, args = _unwrap(tokens)
    if program is None or program in _INTERPRETERS or program in _DYNAMIC_PROGRAMS:
        return _dynamic("dynamic or unproven program")
    if program not in _READ_ONLY_PROGRAMS and program not in _WRITE_PROGRAMS and program != "git":
        return _dynamic("unknown program")
    # 变量/替换检测不得豁免 `-` 前缀 token：`-exec$IFS` 的 `$IFS` 是真变量，绕不过检测才算安全。
    if any(_is_path_dynamic(x) for x in tokens):
        return _dynamic("shell variable or substitution")

    positional: list[str] = []
    flags: list[str] = []
    redirects: list[ShellRedirect] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            positional.extend(args[index + 1 :])
            break
        if token in {">", ">>", "2>", "2>>", "1>", "1>>"}:
            if index + 1 >= len(args):
                return _dynamic("redirect target missing")
            target = args[index + 1]
            index += 2
            null_sink = target in NULL_SINKS
            redirects.append(ShellRedirect(target=target, append=token.endswith(">>"), null_sink=null_sink))
            continue
        if "&" in token and ">" in token:
            # 区分 fd 复制/关闭（`>&2`、`2>&1`、`>&-`，非文件写）与 `>& file`/`&> file`（把输出写文件=写）。
            # shlex 常把 `>&` 与目标拆成相邻 token，故先看 token 内联尾巴，再看下一 token。
            if re.fullmatch(r"\d*>&[-\d]+", token):
                redirects.append(ShellRedirect(target=token, fd_dup=True))
                index += 1
                continue
            if index + 1 >= len(args):
                return _dynamic("redirect target missing")
            nxt = args[index + 1]
            if nxt.isdigit() or nxt == "-":
                redirects.append(ShellRedirect(target=token + nxt, fd_dup=True))
            else:
                redirects.append(
                    ShellRedirect(target=nxt, append=token.endswith(">>"), null_sink=nxt in NULL_SINKS)
                )
            index += 2
            continue
        if token.startswith("-"):
            flags.append(token)
            # `-o out` / `-k 1`：仅把紧跟 `-o/--output` 的值记为写路径。
            if program == "sort" and token in {"-o", "--output"}:
                if index + 1 >= len(args):
                    return _dynamic("sort output target missing")
                redirects.append(ShellRedirect(target=args[index + 1]))
                index += 2
                continue
            index += 1
            continue
        positional.append(token)
        index += 1

    if program == "sed":
        for token in args:
            if token.startswith("-") and re.search(r"(?:^|[/;])\s*w\s+\S", token):
                redirects.append(ShellRedirect(target="sed-w-script"))
            if not token.startswith("-") and re.search(r"(?:^|[/;])\s*w\s+\S", token):
                redirects.append(ShellRedirect(target="sed-w-script"))

    if program == "git":
        if not positional:
            return _dynamic("git command requires subcommand")
        sub = positional[0]
        if sub in _GIT_DYNAMIC:
            return _dynamic(f"git {sub} mutates repository state")
        if sub in _GIT_READ_ONLY:
            # 只读子命令也可能经 flags 写文件（`git diff/log --output=<file>`）；带写形态 flag 一律不证只读。
            if any(f == "--output" or f.startswith("--output=") or f == "-o" or f.startswith("-o=") for f in flags):
                return _dynamic(f"git {sub} writes via output flag")
            return ShellSegment(program=program, args=tuple(args), read_only=True, git_subcommand=sub, read_paths=tuple(positional[1:]))
        if sub == "branch":
            if any(flag in {"-l", "--list"} for flag in flags):
                return ShellSegment(program=program, args=tuple(args), read_only=True, git_subcommand=sub, read_paths=tuple(positional[1:]))
            if len(positional) == 1:
                return ShellSegment(program=program, args=tuple(args), read_only=True, git_subcommand=sub)
            return ShellSegment(program=program, args=tuple(args), destructive=True, git_subcommand=sub, write_paths=tuple(positional[1:]))
        if sub == "config":
            if "--get" in flags or any(flag.startswith("--get=") for flag in flags):
                return ShellSegment(program=program, args=tuple(args), read_only=True, git_subcommand=sub, read_paths=tuple(positional[1:]))
            return ShellSegment(program=program, args=tuple(args), destructive=True, git_subcommand=sub, write_paths=(".git/config",))
        return _dynamic(f"unclassified git subcommand {sub}")

    write_paths: list[str] = []
    for redirect in redirects:
        if not redirect.null_sink and not redirect.fd_dup:
            write_paths.append(redirect.target)
    if program == "dd":
        # dd 的 `of=` 不经过通用 positional 路径，必须单独识别为写目标。
        for token in args:
            if token.startswith("of="):
                write_paths.append(token.removeprefix("of="))

    write_flags = _WRITE_FORM_FLAGS.get(program, frozenset())
    # 先把 `-ni` / `-i.bak` / `--in-place=x` 展开成所有可能形式再比对，否则簇写形式会漏判只读。
    flag_forms = {form for flag in flags for form in _flag_forms(flag)}
    has_write_flag = bool(write_flags) and bool(flag_forms & write_flags)
    destructive = program in _WRITE_PROGRAMS or bool(write_paths) or has_write_flag

    if program in _WRITE_PROGRAMS:
        paths = tuple(positional)
        if not paths and not write_paths:
            return _dynamic(f"{program} requires an explicit target")
        return ShellSegment(
            program=program,
            args=tuple(args),
            write_paths=tuple(dict.fromkeys([*paths, *write_paths])),
            redirects=tuple(redirects),
            destructive=True,
        )

    if destructive:
        return ShellSegment(
            program=program,
            args=tuple(args),
            read_paths=tuple(positional),
            write_paths=tuple(write_paths),
            redirects=tuple(redirects),
            destructive=True,
        )

    if program in _READ_ONLY_PROGRAMS:
        return ShellSegment(
            program=program,
            args=tuple(args),
            read_paths=tuple(positional),
            redirects=tuple(redirects),
            read_only=True,
        )

    return _dynamic("program cannot be proven read-only")


def parse_posix_shell(command: str) -> ShellAnalysis:
    """解析一段 POSIX shell command 成安全 IR。"""
    if not command or not command.strip():
        return _unparsable("empty command")
    outer, bodies = _extract_substitutions(command)
    if bodies:
        return _dynamic("shell command substitution is dynamic")
    try:
        lexer = shlex.shlex(outer, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as exc:
        return _unparsable(str(exc))

    sequences = _split_sequences(tokens)
    if not sequences:
        return _dynamic("no executable segment")
    segments: list[ShellSegment] = []
    for sequence in sequences:
        parsed = _parse_segment(sequence)
        if isinstance(parsed, ShellAnalysis):
            return parsed
        segments.append(parsed)

    read_paths = tuple(dict.fromkeys(path for segment in segments for path in segment.read_paths))
    write_paths = tuple(dict.fromkeys(path for segment in segments for path in segment.write_paths))
    return ShellAnalysis(
        dialect=ShellDialect.POSIX,
        status=ShellParseStatus.PARSED,
        segments=tuple(segments),
        read_paths=read_paths,
        write_paths=write_paths,
    )


__all__ = ["parse_posix_shell"]
