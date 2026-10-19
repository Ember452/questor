"""L0' 唯一脱敏 filter：作用于 ``msg`` + ``fields`` 值 + ``traceback`` 三面（DESIGN §8）。

三层归属（DESIGN §3）：**内核文件**——运行时 import 图只含 stdlib（``re``/``dataclasses``/
``difflib``）；类型标注走 ``TYPE_CHECKING``（不产生运行时耦合，抽包时随包走）。

为什么全系统**唯一一处**（D12）：构造时脱敏要两个构造点、且覆盖不到 msg/fields/traceback
三个面；放在 ``LogEntry`` 构造后、fan-out 前一处，两条通道都被守住。

设计要点：pattern 簇遵循“绝不执行凭据”（如 Azure Entra bearer 只标记不 refresh）；
fail-closed 为本设计自加。prompt 回显剥离为 Questor 自写纯函数，**已在 ``kernel/loop`` 接线**（见 ``strip_prompt_echo`` docstring）。
"""

from __future__ import annotations

import re
from dataclasses import replace
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型：运行时不 import questor.*，保持内核零外部依赖（G-L1）。
    from questor.observability.entry import LogEntry

#: 命中脱敏后注入 fields 的标记键（与 ``context`` 撞键时优先保留它，见 ``_drop_context_clash``）。
_REDACTED_FLAG = "redacted"

#: pattern 簇（非穷举）：(编译正则, 替换)。顺序应用、任一命中即标 ``redacted``。
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # OpenAI/Anthropic 风格密钥。
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "sk-***"),
    # ``Bearer <token>``（含 Authorization 头里的）。
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-/+=]{6,}"), r"\1***"),
    # ``*api_key*=value`` / secret/token/password/passwd 形式的键值赋值。
    (
        re.compile(
            r"(?i)\b([a-z0-9_]*(?:api[_-]?key|secret|token|password|passwd)[a-z0-9_]*\s*[:=]\s*['\"]?)[\s\S]+?(?=['\"]?[\s,;}]|$)"
        ),
        r"\1***",
    ),
    # URL 内嵌凭据 ``scheme://user:pass@``。
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)([^/\s:@]+):([^/\s@]+)@"), r"\1***:***@"),
    # PEM 私钥块。
    (re.compile(r"-----BEGIN [A-Z ]*-----[\s\S]*?-----END [A-Z ]*-----"), "<PEM-REDACTED>"),
    # 常见云厂商长期密钥前缀（AWS AKIA…）。
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***"),
)


def _redact_text(text: str) -> tuple[str, bool]:
    """对一段文本顺序应用 pattern 簇，返回 ``(脱敏后文本, 是否命中)``。

    这是 ``redact()`` 的脱敏原语；测试 fail-closed 时会 monkeypatch 本函数抛异常来验整条降级。
    """
    hit = False
    out = text
    for pattern, repl in _PATTERNS:
        out, n = pattern.subn(repl, out)
        hit = hit or n > 0
    return out, hit


def _drop_context_clash(context: dict[str, str | int | float | bool | None]) -> dict:
    """从 ``context`` 里去掉与待注入标记键 ``redacted`` 同名的项（不变式 5 禁同键）。

    为什么弃关联键而不是弃标记键：标记键（``redacted``）是"这条日志被脱敏过"的安全信号，
    排障时不可缺；关联键少一个只影响归属，而 ``replace`` 一旦抛 ``ValueError`` 会直接把整行弄没。
    脱敏绝不能反过来造成丢日志（Issue #132）。
    """
    return {k: v for k, v in context.items() if k != _REDACTED_FLAG}


def redact(entry: LogEntry) -> LogEntry:
    """对一条 ``LogEntry`` 做唯一一处脱敏：``msg``/``fields`` 值/``traceback`` 三面全覆盖。

    命中任一 → 返回新实例并置 ``fields["redacted"]=True``（使"这次排障是否被脱敏挡住"可查询）；
    未命中 → 原样返回（不复制）。**fail-closed**：脱敏自身抛异常 → 整条替换 ``<unredactable>``，
    原文绝不穿过（DESIGN §8）。
    """
    try:
        msg, h_msg = _redact_text(entry.msg)
        tb = entry.traceback
        h_tb = False
        if tb is not None:
            tb, h_tb = _redact_text(tb)
        new_fields: dict[str, str | int | float | bool | None] = {}
        h_fields = False
        for key, value in entry.fields.items():
            if isinstance(value, str):
                nv, h = _redact_text(value)
                new_fields[key] = nv
                h_fields = h_fields or h
            else:
                new_fields[key] = value
        if h_msg or h_tb or h_fields:
            new_fields[_REDACTED_FLAG] = True
            return replace(entry, msg=msg, traceback=tb, fields=new_fields, context=_drop_context_clash(entry.context))
        return entry
    except Exception:  # noqa: BLE001 - fail-closed：判不了敏感就按敏感处理，宁可丢信息不可漏凭据
        # fail-closed 分支自身也绝不能抛（否则异常会冒过 pipeline，Issue #132）。
        return replace(
            entry,
            msg="<unredactable>",
            traceback=None,
            fields={_REDACTED_FLAG: True},
            context=_drop_context_clash(entry.context),
        )


def strip_prompt_echo(text: str, prompts: list[str], min_len: int = 24) -> str:
    """纯函数：把 ``text`` 中与任一 prompt 共享的、长度 ``>= min_len`` 的片段替换为 ``<prompt>``。

    provider 4xx 常把请求体（含用户 prompt）整段回显；除 pattern 脱敏外，再对错误文本做一次
    "与本轮 prompt 的长公共片段→``<prompt>``"处理（DESIGN §8）。

    **接线现状（#162B）**：已在 ``kernel/loop`` 的 provider 异常归一点接入——以 ``run.context``
    里的用户消息为 prompt 基准剥离回显，使 ``run_failed``/账本/前端不再携带 prompt。端到端真实
    回显脱敏效果仍需带 key 的 live 验证（无 key 环境下标 UNVERIFIED）。
    """
    out = text
    for prompt in prompts:
        if not prompt:
            continue
        matcher = SequenceMatcher(None, out, prompt, autojunk=False)
        pieces: list[str] = []
        last = 0
        for a, _b, size in matcher.get_matching_blocks():
            # get_matching_blocks 末尾恒有一 size==0 哨兵块，靠 min_len 天然过滤。
            if size >= min_len:
                pieces.append(out[last:a])
                pieces.append("<prompt>")
                last = a + size
        pieces.append(out[last:])
        out = "".join(pieces)
    return out
