"""凭据五件套单测：token 长度、cookie、Host/Origin、父租约。"""

from __future__ import annotations

import asyncio
import os

import pytest

from questorharness.bootstrap.hosts.serve import auth, refusals


def test_credential_is_long_enough_and_unique() -> None:
    """token ≥32 字节，且每次启动不同。"""
    first = auth.LaunchCredential.issue()
    second = auth.LaunchCredential.issue()
    assert len(first.token) >= auth.TOKEN_MIN_BYTES
    assert first.token != second.token


def test_cookie_header_is_httponly_and_strict() -> None:
    """cookie 必须 HttpOnly + SameSite=Strict。"""
    header = auth.cookie_header("tok")
    assert "HttpOnly" in header
    assert "SameSite=Strict" in header
    assert header.startswith(f"{auth.COOKIE_NAME}=tok;")


def test_host_and_origin_validation() -> None:
    """只允许回环主机名；端口与 scheme 被忽略。"""
    auth.validate_host("127.0.0.1:1234")
    auth.validate_host("localhost:9")
    with pytest.raises(refusals.Refusal) as host_exc:
        auth.validate_host("evil.example.com")
    assert host_exc.value.code == refusals.AUTH_HOST
    auth.validate_origin("http://127.0.0.1:1234")
    with pytest.raises(refusals.Refusal) as origin_exc:
        auth.validate_origin("https://evil.example.com")
    assert origin_exc.value.code == refusals.AUTH_ORIGIN
    with pytest.raises(refusals.Refusal):
        auth.validate_origin(None)


def test_cookie_validation_compares_token() -> None:
    """缺失或错误 token 都必须拒绝。"""
    credential = auth.LaunchCredential.issue()
    with pytest.raises(refusals.Refusal):
        auth.validate_cookie({}, credential)
    with pytest.raises(refusals.Refusal):
        auth.validate_cookie({auth.COOKIE_NAME: "wrong"}, credential)
    auth.validate_cookie({auth.COOKIE_NAME: credential.token}, credential)


def test_handshake_line_is_single_json_line() -> None:
    """握手必须是单行 JSON（父进程读首个换行）。"""
    credential = auth.LaunchCredential(token="t" * 32)
    payload = auth.handshake_payload(4321, credential)
    assert payload.endswith(b"\n") is False
    assert b"\n" not in payload
    assert payload.startswith(b'{"port":4321,"token":"')


def test_parent_lease_fires_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """父 pid 变化即触发一次退出回调。"""
    calls: list[int] = []

    async def scenario() -> None:
        original = os.getppid()
        lease = auth.ParentLease(lambda: calls.append(1))
        monkeypatch.setattr(auth.os, "getppid", lambda: original + 1)
        await asyncio.wait_for(lease.watch_parent(interval=0.01), timeout=1.0)

    asyncio.run(scenario())
    assert calls == [1]
