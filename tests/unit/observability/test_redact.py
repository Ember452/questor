"""T2.4 脱敏 ``observability/redact.py`` 判例（DESIGN §8；G-L3）。

覆盖：pattern 簇在 ``msg``/``fields`` 值/``traceback`` 三面的掩蔽；命中加 ``redacted=True``；
未命中不改；**fail-closed**（脱敏自身抛异常→整条替换 ``<unredactable>``）；``strip_prompt_echo``
纯函数（仅测函数本体，接线后置 P5/刀 3——诚实边界）。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from questor.observability import redact as redact_mod
from questor.observability.entry import LogEntry, LogLevel
from questor.observability.redact import redact, strip_prompt_echo

_SECRET = "sk-abcdef1234567890WXYZ"


def _entry(msg: str = "hi", fields: dict | None = None, traceback: str | None = None) -> LogEntry:
    return LogEntry(
        ts=datetime.now(UTC),
        level=LogLevel.INFO,
        logger="questor.test",
        msg=msg,
        fields=fields or {},
        traceback=traceback,
        source="inline",
        context={},
    )


def test_clean_text_untouched_no_flag() -> None:
    e = redact(_entry(msg="normal message", fields={"n": 1}))
    assert e.msg == "normal message"
    assert "redacted" not in e.fields


def test_sk_token_masked_in_msg() -> None:
    e = redact(_entry(msg=f"using key {_SECRET} now"))
    assert _SECRET not in e.msg
    assert e.fields.get("redacted") is True


def test_authorization_bearer_masked_in_msg() -> None:
    e = redact(_entry(msg="header Authorization: Bearer tok_9fe3ab1c2d"))
    assert "tok_9fe3ab1c2d" not in e.msg
    assert e.fields.get("redacted") is True


def test_secret_masked_across_all_three_faces() -> None:
    # G-L3 三面：msg / fields 值 / traceback 都不得留原串。
    e = redact(_entry(msg=f"call failed {_SECRET}", fields={"detail": f"retry {_SECRET}"}, traceback=f"Traceback .. key={_SECRET}"))
    assert _SECRET not in e.msg
    assert _SECRET not in e.fields["detail"]
    assert _SECRET not in (e.traceback or "")
    assert e.fields.get("redacted") is True


def test_pem_block_masked() -> None:
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANB....\n-----END PRIVATE KEY-----"
    e = redact(_entry(msg=pem))
    assert "MIIEvQIBADANB" not in e.msg
    assert e.fields.get("redacted") is True


def test_url_credentials_masked() -> None:
    e = redact(_entry(msg="connect postgres://admin:s3cr3t@db.internal:5432/app"))
    assert "s3cr3t" not in e.msg
    assert "admin:" not in e.msg
    assert e.fields.get("redacted") is True


def test_apikey_assignment_masked() -> None:
    e = redact(_entry(msg="LITELLM_API_KEY=supersecretvalue123"))
    assert "supersecretvalue123" not in e.msg
    assert e.fields.get("redacted") is True


def test_redact_returns_replaced_instance_original_untouched() -> None:
    orig = _entry(msg=f"leak {_SECRET}")
    out = redact(orig)
    assert out is not orig
    assert _SECRET in orig.msg  # 输入不被就地改（frozen 语义）


def test_fail_closed_on_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # 脱敏自身抛异常 → 整条替换 <unredactable>，原文绝不穿过。
    def _boom(_text: str) -> tuple[str, bool]:
        raise RuntimeError("redactor crashed")

    monkeypatch.setattr(redact_mod, "_redact_text", _boom)
    e = redact(_entry(msg=f"secret {_SECRET}", traceback=f"tb {_SECRET}"))
    assert e.msg == "<unredactable>"
    assert _SECRET not in e.msg
    assert e.traceback is None
    assert e.fields.get("redacted") is True


def _entry_with_context(msg: str, context: dict) -> LogEntry:
    return LogEntry(
        ts=datetime.now(UTC), level=LogLevel.INFO, logger="questor.test", msg=msg,
        source="inline", context=context,
    )


def test_fail_closed_path_does_not_raise_when_context_clashes_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """#132：fail-closed 重建自己也不能抛。

    旧写法 ``replace(entry, fields={"redacted": True})`` 会在 ``context`` 已有 ``redacted`` 时撞
    不变式 5 再抛 ``ValueError``，直接从 ``redact()`` 冒到 pipeline 之外——而 ``pipeline.emit`` 当时
    没有顶层兜底，带外投影的调用点在宿主 await 循环里。
    """

    def _boom(_text: str) -> tuple[str, bool]:
        raise RuntimeError("redactor crashed")

    monkeypatch.setattr(redact_mod, "_redact_text", _boom)
    out = redact(_entry_with_context(f"secret {_SECRET}", {"redacted": "stale"}))  # 不得抛
    assert out.msg == "<unredactable>"
    assert out.fields["redacted"] is True
    assert "redacted" not in out.context, "安全标记优先，让位的只能是关联键"


def test_hit_path_does_not_raise_when_context_clashes_flag() -> None:
    """#132：命中脱敏的正常路径同样不能因撞键而抛。"""
    out = redact(_entry_with_context(f"leak {_SECRET}", {"redacted": "stale"}))
    assert _SECRET not in out.msg
    assert out.fields["redacted"] is True
    assert "redacted" not in out.context


# ---------------- strip_prompt_echo：纯函数（接线后置，仅测函数本体）----------------

def test_strip_prompt_echo_removes_long_overlap() -> None:
    prompt = "please summarize the following annual financial report for Q3 2025 in detail"
    echo = f"provider 400: request body contained '...{prompt}...' which is invalid"
    out = strip_prompt_echo(echo, [prompt], min_len=24)
    assert prompt not in out
    assert "<prompt>" in out


def test_strip_prompt_echo_keeps_short_incidental_overlap() -> None:
    # 公共片段 < min_len 不视为回显，不误删（避免把普通词也吞掉）。
    out = strip_prompt_echo("the the value is ok", ["the quick brown"], min_len=24)
    assert "<prompt>" not in out
