"""sidecar bootstrap 落盘权限收紧（W6-008）。"""

from __future__ import annotations

import os
import sys

from questor.surfaces.serve import read_bootstrap, write_bootstrap


def test_write_bootstrap_restricts_permissions(tmp_path) -> None:  # noqa: ANN001
    boot = tmp_path / "sidecar-bootstrap.json"
    data = write_bootstrap(boot, host="127.0.0.1", port=1234, generation=1, pid=os.getpid(), token="secret-token")
    assert data["token"] == "secret-token"
    # 回读契约不变：文件仍是合法 JSON 且含 token。
    assert read_bootstrap(boot)["token"] == "secret-token"
    if not sys.platform.startswith("win"):
        # POSIX：仅属主可读写（0600），同机其他用户不得读会话 token。
        mode = boot.stat().st_mode & 0o777
        assert mode == 0o600, f"bootstrap 权限过宽：{oct(mode)}"
