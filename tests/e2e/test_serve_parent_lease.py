"""父进程租约 e2e：stdin 关闭后，回环服务必须在 2s 内退出。

用真实子进程与真实 HttpServer（不拉起 runtime）：父进程写端关闭 → 子进程读 stdin
得到 EOF → ParentLease 触发 stop → 关监听 → 退出。
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

CHILD = textwrap.dedent(
    """
    import asyncio, sys
    from questorharness.bootstrap.hosts.serve import auth
    from questorharness.bootstrap.hosts.serve.http_server import HttpServer
    from questorharness.bootstrap.hosts.serve.transport import Response

    async def handler(request):
        return Response(status=200, body=b"ok")

    async def main():
        credential = auth.LaunchCredential.issue()
        server = HttpServer(handler, credential)
        stop = asyncio.Event()
        lease = auth.ParentLease(stop.set)
        port = await server.start()
        sys.stdout.write(str(port) + "\\n")
        sys.stdout.flush()
        lease.start()
        try:
            await stop.wait()
        finally:
            lease.stop()
            await server.close()

    asyncio.run(main())
    """
)


@pytest.mark.e2e
def test_parent_stdin_eof_shuts_the_server_down() -> None:
    """stdin EOF → 子进程在 2s 内退出，且监听端口已释放。"""

    async def scenario() -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            CHILD,
            cwd=str(REPO),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdout is not None
        line = await asyncio.wait_for(process.stdout.readline(), timeout=30)
        port = int(json.loads(line.decode().strip()))
        assert 1024 <= port <= 65535
        assert process.stdin is not None
        process.stdin.close()
        await asyncio.wait_for(process.wait(), timeout=2.0)
        assert process.returncode == 0

    asyncio.run(scenario())
