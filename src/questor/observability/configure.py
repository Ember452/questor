"""L0' 装配：``configure_logging(...)`` 参数化幂等装配 + ``logging_status()``（DESIGN §11；G-L8）。

三层归属（DESIGN §3）：**内核文件**——运行时 import 只在 observability 包内。**env-free**：所有参数由
调用方（组合根 T2.14）传入，绝不读 config/env（守 ``config ⟂ observability`` independence 契约；
配置由容器注入，内核不知道 env 的存在）。

幂等口径：默认 ``force=True`` 重配——**先拆旧再建新**（移除旧 ``BridgeHandler``、注销旧 sink、
重置管线），故反复调用不叠 handler/sink（G-L8）。``force=False`` 且已初始化则 no-op。

级别口径（Issue #126）：**root 不被下调到 DEBUG**。以前把 root 拉到 DEBUG 是为了让一方 DEBUG 能进
桥，但副作用是把**所有**第三方库的 DEBUG 一起打开（aiosqlite 会把 SQL 参数元组——即账本内容与
prompt 原文——整个打进日志）。正确做法：root 保持 INFO（只要求未设时显式定住），只对 ``questor``
子树开低级别——``Logger.callHandlers`` 不遍历祖先级别，所以一方记录仍能进桥，而第三方默认安静。

窗尾刷新（Issue #136）：装配时注册 ``atexit`` 跑一次 ``pipeline.flush()``，否则被节流抑制的条数
会随进程直接丢掉（“窗尾补 repeated N times”就只存在于测试里）。
"""

from __future__ import annotations

import atexit
import logging
from pathlib import Path

from questor.observability.bridge import BridgeHandler, quiet_noisy_loggers
from questor.observability.entry import LogLevel
from questor.observability.exporter import register
from questor.observability.pipeline import flush as _pipeline_flush
from questor.observability.pipeline import reset as _pipeline_reset
from questor.observability.pipeline import stats as _pipeline_stats
from questor.observability.sink_console import ConsoleSink
from questor.observability.sink_file import FileSink

_ROOT = logging.getLogger()
#: 一方 logger 子树根：只它降到文件/console 的较低门，不碰 root（Issue #126）。
_FIRST_PARTY = "questor"

# 模块级单例装配态；force 重配据此拆旧。
_state: dict | None = None
# atexit 只注册一次（重配不叠加回调）。
_atexit_registered = False


def _register_atexit_flush() -> None:
    global _atexit_registered
    if _atexit_registered:
        return
    atexit.register(_pipeline_flush)
    _atexit_registered = True


def _teardown() -> None:
    global _state
    if _state is None:
        return
    bridge = _state.get("bridge")
    if bridge is not None and bridge in _ROOT.handlers:
        _ROOT.removeHandler(bridge)  # 1) 先断新记录来源
    _pipeline_flush()  # 2) 再补窗尾——此时 sink **仍在注册表里**，补行才真的落得出得去
    for unreg in _state.get("unregs", ()):
        unreg()  # 3) 最后才拆 sink
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
    # root 只要求“未设时定在 INFO”，绝不降到 DEBUG（Issue #126：那会把第三方参数日志全部打开）。
    if _ROOT.level == logging.NOTSET:
        _ROOT.setLevel(logging.INFO)
    # 一方子树开到 console/file 两门的较低值，保证 questor.* 的 DEBUG 能进桥并落主干文件。
    # 真正的分级收录由各 sink 的 min_level 把关；外来记录另受 pipeline 来源门封顶 INFO。
    logging.getLogger(_FIRST_PARTY).setLevel(min(console_level, file_level))
    quiet_noisy_loggers()
    _register_atexit_flush()

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
