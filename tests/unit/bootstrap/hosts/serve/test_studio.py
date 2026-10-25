"""studio 宿主镜像测试：握手行与默认形态目录。"""

from __future__ import annotations

import json

from questorharness.bootstrap.hosts.serve import auth, studio


def test_studio_module_exposes_runner() -> None:
    """run_studio_host 必须可调用（CLI --studio-host 的入口）。"""
    assert callable(studio.run_studio_host)


def test_handshake_round_trips_through_json() -> None:
    """握手行必须能被父进程直接 json.loads。"""
    credential = auth.LaunchCredential(token="x" * 32)
    payload = json.loads(auth.handshake_payload(8080, credential))
    assert payload == {"port": 8080, "token": "x" * 32}
