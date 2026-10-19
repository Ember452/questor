"""L0 记忆词汇表（design/06；ADR-0023/0024/0026）。P4 固定接缝形状。

归属边界（ADR-0023）：记忆是与 ``state/`` 分离的**独立子系统**，本模块只放它跨层共享的
"词表"——数据类（chunk / 检索结果 / 恢复指针 / 写载荷）与 Port 抽象（存储 / 向量后端 /
策略旋钮）。**只放抽象 + 数据**，实现留在 ``providers``/``memory``（STRUCTURE §7 S4）。

依赖方向（HARD C1/C14）：``contracts`` 是最内层，**绝不 import 外层**（state/kernel/
providers/policy/surfaces），故本文件只依赖 :mod:`questor.contracts.common`。

不可变纪律（HARD C2）：数据类一律 ``frozen=True, slots=True`` + 不可变集合；dict 叶经
:func:`freeze` 深冻结，避免 COW 共享实例被就地篡改。落盘 JSON 禁 NaN/Inf（HARD C18）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from questor.contracts.common import JsonObject, freeze, require_non_empty


class MemoryScope(StrEnum):
    """记忆可见范围。"""

    SHARED = "shared"
    USER = "user"
    SESSION = "session"


class MemorySource(StrEnum):
    """记忆来源层（design/06 §1 三层 + knowledge）。

    ``DREAMS`` 是蒸馏产物、**不进检索索引**（防近重复噪声，design/06 §1）。"""

    CORE = "core"  # MEMORY.md 常绿精华
    DAILY = "daily"  # memory/YYYY-MM-DD.md 流水
    DREAMS = "dreams"  # Deep Dream 蒸馏日记（不索引）
    KNOWLEDGE = "knowledge"  # knowledge/**.md，与 memory 同索引不同 source


class MemoryWriteKind(StrEnum):
    """``MemoryWrite`` 载荷的写入意图类别（design/06 §1/§3）。

    ``DISTILL`` 是压缩丢弃区/Deep Dream 的固化写；其原文区经 covered_* 引用、
    **只写浓缩文本、绝不写 delta**（design/06 I3）。"""

    CORE = "core"
    DAILY = "daily"
    DISTILL = "distill"


#: 写 kind → 记忆 source 层（distill 浓缩固化进 daily，design/06 §3）。L0 词汇映射，
#: 供 ``reduce``（发 memory_written 事件）与 store（落库）共用，避免 kind/source 语义漂移。
_WRITE_KIND_TO_SOURCE: dict[MemoryWriteKind, MemorySource] = {
    MemoryWriteKind.CORE: MemorySource.CORE,
    MemoryWriteKind.DAILY: MemorySource.DAILY,
    MemoryWriteKind.DISTILL: MemorySource.DAILY,
}


def source_for_write(kind: MemoryWriteKind) -> MemorySource:
    """把 ``MemoryWrite`` 的写意图 kind 映射为真实记忆 ``source`` 层（emit 事件/落库共用）。"""
    return _WRITE_KIND_TO_SOURCE[kind]


@dataclass(frozen=True, slots=True)
class MemoryChunk:
    """索引里的一条记忆片段（派生投影；文件/md 才是真源，design/06 §0）。

    候选 shape 用 ``(path, start_line, end_line)`` 表示记忆侧的 recovery pointer 形态。"""

    id: str
    scope: MemoryScope
    source: MemorySource
    path: str  # 相对记忆根的真源路径，如 MEMORY.md / memory/2026-10-16.md
    start_line: int
    end_line: int
    text: str  # 已浓缩的块正文（非 delta）
    hash: str  # 内容哈希，用于 sync 去重 / stale reconcile
    embedding: tuple[float, ...] | None = None  # 缺省 None → 检索降级关键词-only（ADR-0026）
    metadata: JsonObject | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.id, "MemoryChunk.id")
        require_non_empty(self.path, "MemoryChunk.path")
        require_non_empty(self.hash, "MemoryChunk.hash")
        if self.start_line < 0 or self.end_line < self.start_line:
            raise ValueError("MemoryChunk requires 0 <= start_line <= end_line")
        if self.metadata is not None:
            object.__setattr__(self, "metadata", freeze(self.metadata))


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    """检索命中回给策略/工具的**有界**片段（design/06 §0；ADR-0026）。

    只回 ``(path, start_line, end_line, snippet)`` + 归一分；命中原文超阈时经字段级白名单
    截断、全文以 ``artifact_ref`` 外置，绝不把内部绝对路径/未截断原文外发（HARD C18/0019）。"""

    path: str
    start_line: int
    end_line: int
    score: float  # rank-normalize 融合 + 时间衰减后的归一分（(0,1] 量纲）
    snippet: str  # 有界片段（size cap 由检索侧强制）
    source: MemorySource
    scope: MemoryScope = MemoryScope.USER
    artifact_ref: str | None = None  # 超阈全文的外置引用（ADR-0019 语义）

    def __post_init__(self) -> None:
        if self.end_line < self.start_line:
            raise ValueError("MemorySearchResult requires start_line <= end_line")
        # score 有限性：NaN/Inf 会污染下游排序与 wire（HARD C18 卫生）。
        if self.score != self.score or self.score in (float("inf"), float("-inf")):
            raise ValueError("MemorySearchResult.score must be finite")


@dataclass(frozen=True, slots=True)
class RecoveryPointer:
    """指向被压缩原文区间的恢复指针（ADR-0024；design/01 §13）。

    形态定为 ``(seq_from, seq_to)`` + ``covered_hash`` 锚，指向 events/messages 的
    append-only 序号区间（非字节偏移、非 UUID，取序号侧）；读取前必须以
    :meth:`matches` 校验覆盖区语义哈希，**历史被改写/分叉即 fail-closed**（绝不返回旧内容）。
    """

    seq_from: int
    seq_to: int
    covered_hash: str

    def __post_init__(self) -> None:
        if self.seq_from < 0 or self.seq_to < self.seq_from:
            raise ValueError("RecoveryPointer requires 0 <= seq_from <= seq_to")
        require_non_empty(self.covered_hash, "RecoveryPointer.covered_hash")

    def matches(self, content_hash: str) -> bool:
        """纯函数校验：给定覆盖区重算出的语义哈希是否与锚一致。调用方在 ``False`` 时 fail-closed。"""
        return content_hash == self.covered_hash


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    """``WriteMemory`` 命令的 typed 载荷（ADR-0024；取代旧的裸 ``JsonObject``）。

    经 Command→reduce→StorePort 单写路径落库（HARD C4/C16）。``distill`` 类写可携带被压
    区的 ``(covered_from, covered_to, covered_hash)`` 引用，但正文只放**浓缩文本**（I3）。"""

    kind: MemoryWriteKind
    scope: MemoryScope
    text: str  # 有界浓缩文本；空文本被拒（空哨兵由蒸馏侧"跳过不写"处理，不进此路径）
    covered_from: int | None = None  # 仅 distill：被压原文区起点（**压缩前 context 快照索引**，非 event seq；compaction 与 RecoveryPointer 同一编号空间）
    covered_to: int | None = None  # 同上，被压原文区终点（context 快照索引）
    covered_hash: str | None = None  # 仅 distill：覆盖区语义哈希锚（读取 fail-closed 校验）
    note: str | None = None  # 有界来源说明（勿塞原始 transcript）
    metadata: JsonObject | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.text, "MemoryWrite.text")
        if self.kind is MemoryWriteKind.DISTILL:
            # distill 写必须成对给出可校验的覆盖区锚，否则读回无法 fail-closed（ADR-0024）。
            if self.covered_from is None or self.covered_to is None or not self.covered_hash:
                raise ValueError("distill MemoryWrite requires covered_from/to/hash")
            if self.covered_from < 0 or self.covered_to < self.covered_from:
                raise ValueError("MemoryWrite requires 0 <= covered_from <= covered_to")
        elif self.covered_from is not None or self.covered_to is not None:
            raise ValueError("only distill MemoryWrite may carry a covered region")
        if self.metadata is not None:
            object.__setattr__(self, "metadata", freeze(self.metadata))


@dataclass(frozen=True, slots=True)
class MemoryStrategyConfig:
    """检索/蒸馏的可调旋钮（DoD④：算法可插拔、不耦合 Kernel）。

    默认值承 design/06 §2/§4 与 ADR-0026；实现期经配置覆盖（HARD C18"阈值经配置、只增不改"）。
    换一个 ``config`` = 换检索行为，全程不动 ``kernel/loop.py``（05 §5）。"""

    half_life_days: float = 30.0  # daily 时间衰减半衰期；core/knowledge 常绿不衰减
    vector_weight: float = 0.7  # rank-normalize 融合权重（与 keyword 归一防 NaN/负）
    keyword_weight: float = 0.3
    rerank_enabled: bool = False  # 默认关、后置（ADR-0026）
    popularity_boost: bool = False  # 命中热度 boost 默认关（design/06 §2）
    snippet_max_bytes: int = 2048  # 命中片段进 prompt/事件的字节上限（ADR-0019 有界）
    top_k: int = 8

    def __post_init__(self) -> None:
        if self.half_life_days <= 0:
            raise ValueError("MemoryStrategyConfig.half_life_days must be positive")
        if self.vector_weight < 0 or self.keyword_weight < 0:
            raise ValueError("fusion weights must be non-negative")
        if self.vector_weight == 0 and self.keyword_weight == 0:
            raise ValueError("fusion weights must not both be zero")
        if self.top_k <= 0 or self.snippet_max_bytes <= 0:
            raise ValueError("MemoryStrategyConfig top_k/snippet_max_bytes must be positive")


@runtime_checkable
class VectorBackend(Protocol):
    """向量后端抽象（design/06 §4）。

    实现（SQLite cosine）住 ``providers``，不出本模块边界（HARD C4"向量库实现不越界"）。
    无 embedding 时上层须能仅靠关键词通道工作（ADR-0026）。"""

    async def upsert(self, chunk_id: str, embedding: tuple[float, ...]) -> None: ...

    async def delete(self, chunk_ids: tuple[str, ...]) -> None: ...

    async def search(
        self, query_embedding: tuple[float, ...], k: int
    ) -> list[tuple[str, float]]:
        """返回 ``[(chunk_id, cosine_score), ...]``，按分降序。"""
        ...


@runtime_checkable
class MemoryStorePort(Protocol):
    """记忆读写收口接口（design/06 §0/§4；HARD C4；ADR-0023）。

    **Harness 持有**此接口；策略/工具/离线蒸馏均经它读写、无裸句柄。实现=
    ``providers/store_memory_sqlite.py``（独立 ``memory.db``，文件真源 + 派生索引）。"""

    async def write(
        self, write: MemoryWrite, *, idempotency_key: str
    ) -> JsonObject:
        """把一条浓缩记忆写入真源（md 文件）并更新派生索引。

        返回 bounded receipt（如 ``{"path", "start_line", "end_line", "chunk_count"}``）；
        重复 ``idempotency_key`` 须幂等（claim-then-commit，ADR-0025）。"""
        ...

    async def search(
        self,
        query: str,
        *,
        k: int,
        scope: MemoryScope | None = None,
        query_embedding: tuple[float, ...] | None = None,
    ) -> tuple[MemorySearchResult, ...]:
        """混合检索：向量(cosine)+FTS5 → rank-normalize 融合 → 时间衰减（ADR-0026）。

        无 ``query_embedding``/向量后端不可用时静默降级关键词-only、不抛。"""
        ...

    async def sync(self) -> JsonObject:
        """扫盘重建索引、reconcile stale 行（文件为真源、索引可重建，design/06 §0）。"""
        ...

    async def delete(self, chunk_ids: tuple[str, ...]) -> None:
        """归档/删除索引条目（rotation 等）；真源文件的修剪后置 P10。"""
        ...

    # ---- 离线维护路径（Deep Dream / run-边界 flush；ADR-0025：同一收口、无旁路）----
    async def read_memory_text(self, rel_path: str) -> str:
        """读一个真源 md 文件内容（相对 memory root）；不存在返回空串。越界路径 fail-closed。"""
        ...

    async def list_memory_paths(self) -> tuple[str, ...]:
        """列出真源 md 文件的相对路径（供离线蒸馏定位 core/daily）。"""
        ...

    async def write_memory_text(self, rel_path: str, content: str, *, idempotency_key: str) -> JsonObject:
        """**原子全量重写**一个真源 md（Deep Dream 重写 core）；``idempotency_key`` 命中则 no-op（claim-then-commit）。

        写后不自动索引；调用方经 :meth:`sync` 从文件重建派生索引（文件为真源）。越界路径 fail-closed。"""
        ...

    async def append_memory_text(self, rel_path: str, content: str, *, idempotency_key: str) -> JsonObject:
        """**原子追加**到真源 md（run-完成→daily flush、梦境日记）；``idempotency_key`` 命中则 no-op、失败可重试。

        只写浓缩文本、绝不写 delta（design/06 I3）。越界路径 fail-closed。"""
        ...


__all__ = [
    "MemoryScope",
    "MemorySource",
    "MemoryWriteKind",
    "source_for_write",
    "MemoryChunk",
    "MemorySearchResult",
    "RecoveryPointer",
    "MemoryWrite",
    "MemoryStrategyConfig",
    "VectorBackend",
    "MemoryStorePort",
]
