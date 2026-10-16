"""刀1 缺陷 A④/A③（in-process 面）：configure_logging 幂等、绝不叠 handler、永不写 stdout。

重复调用 ``configure_logging`` 每条 msg 恰 1 次；console sink 绑 stderr，机器可读的 stdout
保持洁净。测试自行 snapshot/restore 根 handler，避免污染其它用例（直接调 interactive() 的
测试此后也需自行显式 configure——装配责任已上移组合根）。
"""

from __future__ import annotations

import logging
import sys

from questor.observability.logging import configure_logging


def _stderr_stream_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr
    ]


def test_configure_logging_idempotent_and_stderr_only(capsys) -> None:  # noqa: ANN001
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    # 起点：移除此前遗留的 stderr 流 handler，真正验证"重复调用不叠加"。
    for h in _stderr_stream_handlers(root):
        root.removeHandler(h)
    try:
        configure_logging(level=logging.INFO)
        configure_logging(level=logging.INFO)  # 重复调用不得再叠一个 stderr handler

        assert len(_stderr_stream_handlers(root)) == 1, "configure_logging must not stack stderr handlers"

        logging.getLogger("questor.idempotency").info("hello-exactly-once")
        captured = capsys.readouterr()

        assert captured.out == "", "console sink must never write to stdout"
        assert captured.err.count("hello-exactly-once") == 1, "each message must be emitted exactly once"
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
