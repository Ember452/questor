"""T2.10 装配 ``observability/configure.py`` 判例（DESIGN §11；G-L8；DoD B⑥）。

覆盖：``configure_logging`` 幂等不叠 handler（每 msg 恰 1 次，G-L8）、console 落 stderr 不污染 stdout、
参数注入生效（console/file level、log_dir）、``logging_status`` 聚合可查、只读目录降级不崩。
每个用例 save/restore root handler + exporter 注册表 + 管线态，防全局泄漏。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from questor.observability import configure as configure_mod
from questor.observability import exporter as exp_mod
from questor.observability import pipeline
from questor.observability.configure import configure_logging, logging_status
from questor.observability.entry import LogLevel


@pytest.fixture
def clean() -> Iterator[None]:
    root = logging.getLogger()
    first_party = logging.getLogger("questor")
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_fp_level = first_party.level  # configure 会显式给 questor 子树定级，不还原会泄给后续用例
    saved_registry = list(exp_mod._registry)
    pipeline.reset()
    configure_mod._state = None
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        first_party.setLevel(saved_fp_level)
        exp_mod._registry[:] = saved_registry
        pipeline.reset()
        configure_mod._state = None


def test_idempotent_no_duplicate_line(clean: None, capsys, tmp_path) -> None:  # noqa: ANN001
    # G-L8：重复调用不叠加 handler / 不重复注册 sink；单条 msg 恰落 1 行。
    configure_logging(log_dir=tmp_path / "logs", force=True)
    configure_logging(log_dir=tmp_path / "logs", force=True)
    bridges = [h for h in logging.getLogger().handlers if type(h).__name__ == "BridgeHandler"]
    assert len(bridges) == 1  # force 重配必须先拆旧桥，否则叠 handler
    consoles = [e for e in exp_mod.current_exporters() if getattr(e, "name", "") == "console"]
    assert len(consoles) == 1  # 旧 console exporter 必须被注销，否则 fan-out 双打
    logging.getLogger("questor.x").info("uniq-line")  # 唯一 msg、只发一次
    cap = capsys.readouterr()
    assert cap.err.count("uniq-line") == 1  # 若叠了 2 个 console sink → 会变 2 行


def test_console_never_stdout(clean: None, capsys, tmp_path) -> None:  # noqa: ANN001
    configure_logging(log_dir=tmp_path / "logs")
    logging.getLogger("questor.x").info("to-stderr")
    cap = capsys.readouterr()
    assert "to-stderr" not in cap.out
    assert "to-stderr" in cap.err


def test_non_force_keeps_single(clean: None, tmp_path) -> None:  # noqa: ANN001
    configure_logging(log_dir=tmp_path / "logs", force=False)
    configure_logging(log_dir=tmp_path / "logs", force=False)  # 已初始化 + 非 force → no-op
    bridges = [h for h in logging.getLogger().handlers if type(h).__name__ == "BridgeHandler"]
    assert len(bridges) == 1


def test_console_level_filter(clean: None, capsys, tmp_path) -> None:  # noqa: ANN001
    configure_logging(console_level=LogLevel.WARNING, log_dir=None)
    logging.getLogger("questor.x").info("below-console")
    cap = capsys.readouterr()
    assert "below-console" not in cap.err  # console INFO→WARNING，DEBUG/INFO 不上终端


def test_logging_status_reports_files(clean: None, tmp_path) -> None:  # noqa: ANN001
    logs = tmp_path / "logs"
    configure_logging(log_dir=logs)
    logging.getLogger("questor.x").error("landed-error")
    st = logging_status()
    assert st["initialized"] is True
    assert st["degraded"] is False
    assert any(name.startswith("errors-") for name in st["files"])
    assert "dropped_records" in st and "disabled_exporters" in st


def test_logging_status_degraded_no_crash(clean: None, tmp_path) -> None:  # noqa: ANN001
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    configure_logging(log_dir=blocker / "logs")  # 不可建目录
    logging.getLogger("questor.x").info("still-console-only")  # 绝不抛
    st = logging_status()
    assert st["degraded"] is True


def test_configure_is_env_free(clean: None, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    # 内核绝不读 env：设了 QUESTOR_LOG_DIR 也无效（log_dir=None → console-only、无文件面）。
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "should-be-ignored"))
    configure_logging(log_dir=None)
    assert not (tmp_path / "should-be-ignored").exists()
    assert logging_status()["log_dir"] is None


def test_configure_does_not_lower_root_to_debug(clean: None, tmp_path) -> None:  # noqa: ANN001
    """#126：装配不得把 root 降到 DEBUG——那等于替全仓第三方库打开参数级日志。

    root 已由其它组件定级时也不得覆写；一方子树自己开到 DEBUG 就能进桥（``callHandlers``
    不遍历祖先级别）。
    """
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    configure_logging(log_dir=tmp_path / "logs", console_level=LogLevel.INFO, file_level=LogLevel.DEBUG)
    assert root.level == logging.WARNING, "不得擅改调用方给 root 定的级别"
    assert logging.getLogger("questor").level == logging.DEBUG, "一方 DEBUG 仍要能进桥"


def test_third_party_debug_does_not_land_in_main_file(clean: None, tmp_path) -> None:  # noqa: ANN001
    """#126 端到端：第三方 DEBUG（带 prompt 形状的参数）不得落进主干 JSONL，一方 DEBUG 照落。

    用一个**不在降噪名单里**的外来 logger 名（``thirdparty.db``），确保拦下它的是 pipeline 的来源门
    而不是 stdlib 级别门或降噪白名单——否则本用例会因为"错误的原因"而变绿。
    """
    import json

    logs = tmp_path / "logs"
    configure_logging(log_dir=logs, console_level=LogLevel.CRITICAL, file_level=LogLevel.DEBUG)
    outsider = logging.getLogger("thirdparty.db")
    saved = outsider.level
    outsider.setLevel(logging.DEBUG)  # 保证记录一定能进桥，只考来源门这一道
    try:
        outsider.debug("executing INSERT INTO checkpoints VALUES (%s)", ("run1", '{"text":"user-prompt"}'))
        logging.getLogger("questor.store").debug("first-party-detail")
        pipeline.flush()
    finally:
        outsider.setLevel(saved)
    content = "".join(p.read_text(encoding="utf-8") for p in logs.glob("*.jsonl"))
    assert "user-prompt" not in content, "外来 DEBUG 穿透了来源门"
    assert "first-party-detail" in content, "一方 DEBUG 被误杀"
    loggers = {json.loads(line)["logger"] for line in content.splitlines() if line.strip()}
    assert "thirdparty.db" not in loggers


def test_reconfigure_flushes_pending_throttle_windows(clean: None, tmp_path, capsys) -> None:  # noqa: ANN001
    """#136：窗尾补行不能只存在于测试里——重配/拆装配时必须先 flush。

    旧行为：``_teardown`` 直接 ``reset()`` 把抑制计数连同窗一起清掉，``repeated N times`` 永不出现。
    """
    configure_logging(console_level=LogLevel.DEBUG, log_dir=None)
    log = logging.getLogger("questor.spam")
    for _ in range(3):
        log.info("same-line-for-flush-check")  # 同形状同窗 → 后两条被抑制
    configure_logging(console_level=LogLevel.DEBUG, log_dir=tmp_path / "logs2")  # force 重配→拆旧
    cap = capsys.readouterr()
    assert "repeated=2" in cap.err, f"拆装配时应补发窗尾，实际 stderr:\n{cap.err}"
