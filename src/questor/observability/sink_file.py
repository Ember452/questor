"""L0' file sink：按记录 ``ts`` 推日期的 JSONL + ``errors``/``llm`` 分流 + 懒清理 + 降级（DESIGN §10）。

三层归属（DESIGN §3）：**内核文件**——运行时 import 只在 observability 包内（``entry.LogLevel``）。

三个落点、三档独立门（这是 D7/§16.3 的落点）：
- ``questor-<YYYYMMDD>.jsonl``：主干，受 ``self.min_level``（= file_level，默认 DEBUG）门；软阈值
  ``max_size_bytes`` 越线 → 追加一条自告警 + 把 ``min_level`` **抬到 INFO**（主动降级，封顶磁盘）。
- ``errors-<YYYYMMDD>.jsonl``：WARNING+ 分流，**独立于主干门**——故提级后错误/警告永不丢（§16.3）。
- ``llm-<YYYYMMDD>.jsonl``：仅 ``llm_file=True`` 且 ``logger=="questor.llm"`` 时承载（隐私独立通道）。

按日无 rename（D7）→ 跨进程安全；文件名天然可 GC（删过期文件）。**best-effort**：目录不可建/不可写
→ 降级 console-only（一次性 stderr WARNING、``degraded=True``、绝不抛）；
teardown 期 ``ValueError/OSError`` 吞掉。JSONL 单行：``json.dumps`` 转义换行，异常链栈完整仍一物理行。
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from questor.observability.entry import LogLevel

if TYPE_CHECKING:  # 仅类型。
    from questor.observability.entry import LogEntry

_MAIN = "questor"
_ERRORS = "errors"
_LLM = "llm"

#: 预览专用 logger（P10/ADR-0049 刀 3；C20 不越界款）：携 prompt/响应截断 preview。
#: **绝不进主干**（保 D4 零原文）、只进独立 `llm-<date>.jsonl`（单独授权/单独排除于分享）。
_LLM_PREVIEW_LOGGER = "questor.llm.preview"


def _entry_to_dict(entry: LogEntry) -> dict:
    """LogEntry → JSONL 记录 dict（字段全量、机器可断言，D9）。"""
    return {
        "ts": entry.ts.isoformat(),
        "level": entry.level.name,
        "logger": entry.logger,
        "msg": entry.msg,
        "fields": entry.fields,
        "traceback": entry.traceback,
        "source": entry.source,
        "context": entry.context,
        "msg_truncated": entry.msg_truncated,
    }


class FileSink:
    """按日 JSONL 文件出口。属性 ``min_level`` 供 pipeline 过滤并在软阈值时被本类自抬（§16.3）。"""

    name = "file"

    def __init__(
        self,
        log_dir: str | Path,
        *,
        file_level: LogLevel = LogLevel.DEBUG,
        keep_days: int = 14,
        llm_file: bool = False,
        max_size_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self.min_level = file_level  # 主干门（= file_level）；软阈值越线时被抬到 INFO
        self._base_level = file_level  # 调用方要求的门——提级只对**当日**生效，换日自动回归
        self.keep_days = keep_days
        self.llm_file = llm_file
        self._max_bytes = max_size_bytes
        self._dir = Path(log_dir)
        self.degraded = False
        self._degrade_warned = False
        # 预算按**记录日期**分桶，且三个 lane 的写入都计入（Issue #135）：
        # 旧写法是跨日累计的单计数器 + 一个永不复位的 _raised 布尔，后果是一天日志多就
        # 把此后所有分片永久降到 INFO（长跑 sidecar 上等于“第一天很噪 → 以后再也看不到 DEBUG”）。
        self._bytes_by_day: dict[str, int] = {}
        self._raised_days: set[str] = set()
        self._current_day: str | None = None
        self._ensure_dir()

    # --- 目录/降级 ---------------------------------------------------------

    def _ensure_dir(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # 只读挂载 / CWD 只读 / 装到 Program Files 非管理员
            self._degrade(exc)

    def _degrade(self, exc: BaseException) -> None:
        self.degraded = True
        if not self._degrade_warned:
            self._degrade_warned = True
            try:  # 一次性出声：让"日志没写"本身不至于变成一个待排故障。
                sys.stderr.write(f"questor.observability: file logging degraded (not writable: {self._dir}): {exc!r}\n")
                sys.stderr.flush()
            except Exception:  # noqa: BLE001
                pass

    # --- 落盘 --------------------------------------------------------------

    def emit(self, entry: LogEntry) -> None:
        if self.degraded:
            return
        try:
            line = json.dumps(_entry_to_dict(entry), ensure_ascii=False) + "\n"
            day = f"{entry.ts:%Y%m%d}"
            self._roll_day(day)
            # errors lane：WARNING+ 独立分流，不看主干门（提级后仍收错误/警告，§16.3）。
            if entry.level >= LogLevel.WARNING:
                self._append(self._fname(entry, _ERRORS), line)
                self._account(day, line)
            # llm lane：仅开启时承载 questor.llm（元数据）与 questor.llm.preview（有界 preview，P10 刀 3）。
            if self.llm_file and entry.logger in ("questor.llm", _LLM_PREVIEW_LOGGER):
                self._append(self._fname(entry, _LLM), line)
                self._account(day, line)
            # main lane：受当前 min_level 门；**preview 行绝不落主干**（C20 不越界款；preview 只走 llm lane）。
            if entry.level >= self.min_level and entry.logger != _LLM_PREVIEW_LOGGER:
                self._append(self._fname(entry, _MAIN), line)
                self._account(day, line)
        except (ValueError, OSError):
            # 磁盘写失败/文件在 teardown 期被关（ValueError("I/O on closed file")）→ 吞 + 降级。
            self._degrade(sys.exc_info()[1])

    def _roll_day(self, day: str) -> None:
        """换日则重置主干门：前一日的软阈值提级不该泄漏到新的一日（Issue #135）。"""
        if day == self._current_day:
            return
        self._current_day = day
        if day not in self._raised_days:
            self.min_level = self._base_level

    def _account(self, day: str, line: str) -> None:
        """累计当日写入字节，越软阈值则提主干门一次（按日记账，不在写路径做多余 IO）。"""
        total = self._bytes_by_day.get(day, 0) + len(line.encode("utf-8"))
        self._bytes_by_day[day] = total
        if total >= self._max_bytes and day not in self._raised_days:
            self._raise_file_level(day)

    def _fname(self, entry: LogEntry, prefix: str) -> str:
        return f"{prefix}-{entry.ts:%Y%m%d}.jsonl"  # 文件名从记录自身 ts 推得（D7，无 rename）

    def _append(self, name: str, line: str) -> None:
        with open(self._dir / name, "a", encoding="utf-8") as f:
            f.write(line)

    def _raise_file_level(self, day: str) -> None:
        """软阈值越线：抬主干 ``min_level`` 到 INFO + 追一条自告警（主干 + errors 各一）。

        只对**触发的那一天**生效：次日预算从 0 重新开始、门回到调用方要求的级别。
        """
        self._raised_days.add(day)
        self.min_level = LogLevel.INFO
        now = datetime.now().astimezone()
        alarm = json.dumps(
            {
                "ts": now.isoformat(),
                "level": LogLevel.WARNING.name,
                "logger": "questor.observability",
                "msg": "main log exceeded max_size; file_level raised to INFO for this day (errors lane unaffected)",
                "fields": {"file_level_raised": True},
                "traceback": None,
                "source": "inline",
                "context": {},
                "msg_truncated": False,
            },
            ensure_ascii=False,
        ) + "\n"
        try:
            self._append(f"{_MAIN}-{day}.jsonl", alarm)
            self._append(f"{_ERRORS}-{day}.jsonl", alarm)  # 走 errors 分流以作"被降级"标记
        except OSError:
            self._degrade(sys.exc_info()[1])

    # --- 懒清理 & 状态 -----------------------------------------------------

    def gc(self, keep_days: int | None = None) -> list[str]:
        """删早于保留期的日分片（按文件名日期判定，无需读内容）。返回被删文件名。"""
        if self.degraded or not self._dir.is_dir():
            return []
        days = self.keep_days if keep_days is None else keep_days
        cutoff = date.today() - timedelta(days=days)
        removed: list[str] = []
        for path in self._dir.glob("*-*.jsonl"):
            stamp = path.stem.rsplit("-", 1)[-1]
            try:
                file_date = datetime.strptime(stamp, "%Y%m%d").date()
            except ValueError:
                continue  # 非日期后缀文件不动。
            if file_date < cutoff:
                try:
                    path.unlink()
                    removed.append(path.name)
                except OSError:
                    pass
        return removed

    def status(self) -> dict:
        """文件面自我观测（供 ``configure.logging_status`` 聚合，DESIGN §13）。"""
        files: list[str] = []
        if not self.degraded and self._dir.is_dir():
            files = sorted(p.name for p in self._dir.glob("*.jsonl"))
        return {
            "degraded": self.degraded,
            "file_level": self.min_level.name,
            "base_file_level": self._base_level.name,
            "llm_file": self.llm_file,
            "max_size_bytes": self._max_bytes,
            "written_bytes": sum(self._bytes_by_day.values()),
            "raised_days": sorted(self._raised_days),
            "log_dir": str(self._dir),
            "files": files,
        }
