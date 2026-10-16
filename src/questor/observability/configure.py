"""L0' 装配：``configure_logging(...)`` 参数化幂等装配 + ``logging_status()``（DESIGN §11；G-L8）。

三层归属（DESIGN §3）：**内核文件**——运行时 import 只在 observability 包内。**env-free**：所有参数由
调用方（组合根 T2.14）传入，绝不读 config/env（守 ``config ⟂ observability`` independence 契约；
cordis ``_resolveConfig`` 同构——配置由容器注入，内核不知道 env 的存在）。

幂等口径：默认 ``force=True`` 重配——**先拆旧再建新**（移除旧 ``BridgeHandler``、注销旧 sink、
重置管线），故反复调用不叠 handler/sink（G-L8）。``force=False`` 且已初始化则 no-op。
"""

from __future__ import annotations

import logging
from pathlib import Path

from questor.observability.bridge import BridgeHandler, quiet_noisy_loggers
from questor.observability.entry import LogLevel
from questor.observability.exporter import register
from questor.observability.pipeline import reset as _pipeline_reset
from questor.observability.pipeline import stats as _pipeline_stats
from questor.observability.sink_console import ConsoleSink
from questor.observability.sink_file import FileSink

_ROOT = logging.getLogger()

# 模块级单例装配态；force 重配据此拆旧。
_state: dict | None = None


def _teardown() -> None:
    global _state
    if _state is None:
        return
    bridge = _state.get("bridge")
    if bridge is not None and bridge in _ROOT.handlers:
        _ROOT.removeHandler(bridge)
    for unreg in _state.get("unregs", ()):
        unreg()
    _pipeline_reset()  # 清节流窗/禁用集/丢弃计数，避免重建后残留态。
    _state = None


def configure_logging(
    *,
    console_level: LogLevel = LogLevel.INFO,
    file_level: LogLevel = LogLevel.DEBUG,
    log_dir: str | Path | None = None,
    keep_days: int = 14,
    llm_file: bool = False,
    force: bool = True,
) -> None:
    """装配带内桥 + console/file sink（DESIGN §11）。参数全由调用方传入，内核不读 env/config。

    ``log_dir=None`` → 仅 console（不建文件面）；给定目录则建按日 JSONL 主干 + ``errors`` 分流
    （WARNING+）+ 可选 ``llm`` 通道。目录不可写时 file sink 自动降级、``configure`` 不抛。
    """
    global _state
    if _state is not None and not force:
        return
    _teardown()  # force 重配：先拆旧的（首次 _state=None 为无害空操作）。

    console = ConsoleSink(min_level=console_level)
    unregs = [register(console)]

    file_sink: FileSink | None = None
    if log_dir is not None:
        file_sink = FileSink(log_dir, file_level=file_level, keep_days=keep_days, llm_file=llm_file)
        unregs.append(register(file_sink))
        file_sink.gc(keep_days)  # 启动懒清理一次（不在写路径删文件，DESIGN §10）。

    bridge = BridgeHandler()
    _ROOT.addHandler(bridge)
    # root 级别设到足够低，让记录能进桥；真正的 console/file 分级由各 sink 的 min_level 把关。
    if _ROOT.level == logging.NOTSET or _ROOT.level > logging.DEBUG:
        _ROOT.setLevel(logging.DEBUG)
    quiet_noisy_loggers()

    _state = {
        "bridge": bridge,
        "console": console,
        "file": file_sink,
        "unregs": unregs,
        "console_level": console_level,
        "log_dir": str(log_dir) if log_dir is not None else None,
    }


def logging_status() -> dict:
    """查询当前装配/健康态（降级、软阈值提级、禁用 exporter、丢弃计数、文件清单）——DESIGN §13。

    "日志没写"本身不该变成一个待排故障，故降级状态必须可查。未初始化时返回 ``{initialized: False}``。
    """
    if _state is None:
        return {"initialized": False}
    status: dict = {
        "initialized": True,
        "console_level": _state["console_level"].name,
        "log_dir": _state["log_dir"],
        "degraded": False,
        "file_level": None,
        "llm_file": False,
        "files": [],
    }
    file_sink = _state["file"]
    if file_sink is not None:
        status.update(file_sink.status())  # 覆盖 degraded/file_level/files/log_dir。
    status.update(_pipeline_stats())  # 并入 dropped_records / disabled_exporters。
    return status
