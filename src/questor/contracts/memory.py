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

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from questor.contracts.common import JsonObject, freeze, require_aware, require_non_empty


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


#: 归因位取值域（B9 纪律⑤；写入必标其一，使“用户说的”与“模型推的”可分别处理）。
ATTRIBUTION_VALUES: frozenset[str] = frozenset({"user", "assistant"})


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
    #: 软删位（B9 纪律⑥）：撤回不删真源、不建历史表，只在派生索引上抹除（默认 False = 旧行为）。
    is_deleted: bool = False
    #: 硬过期时刻（B9 纪律⑦）：与衰减排序分离；None = 永不过期。
    expires_at: datetime | None = None
    #: 归因位（B9 纪律⑤）：从真源节头 `attributed=` 恢复，无标记时 None（不猜）。
    attributed_to: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.id, "MemoryChunk.id")
        require_non_empty(self.path, "MemoryChunk.path")
        require_non_empty(self.hash, "MemoryChunk.hash")
        if self.start_line < 0 or self.end_line < self.start_line:
            raise ValueError("MemoryChunk requires 0 <= start_line <= end_line")
        if self.attributed_to is not None and self.attributed_to not in ATTRIBUTION_VALUES:
            raise ValueError(f"MemoryChunk.attributed_to must be one of {sorted(ATTRIBUTION_VALUES)}")
        if self.expires_at is not None:
            require_aware(self.expires_at, "MemoryChunk.expires_at")
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
    #: 归因/过期位随命中一起外发（有界枚举，无正文），供消费打点与面板显示。
    attributed_to: str | None = None
    expires_at: datetime | None = None

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
    #: 归因位（B9 纪律⑤）：用户声明的事实优先于模型推断；未知/未给时按 ``assistant`` 写。
    attributed_to: str | None = None
    #: 硬过期时刻（B9 纪律⑦）：与时间衰减**分离**——衰减只排序，过期才退出检索。
    expires_at: datetime | None = None
    metadata: JsonObject | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.text, "MemoryWrite.text")
        if self.attributed_to is not None and self.attributed_to not in ATTRIBUTION_VALUES:
            raise ValueError(f"MemoryWrite.attributed_to must be one of {sorted(ATTRIBUTION_VALUES)}")
        if self.expires_at is not None:
            require_aware(self.expires_at, "MemoryWrite.expires_at")
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

    async def soft_delete(self, entry_id: str, *, idempotency_key: str) -> JsonObject:
        """按条目级 id（``path:start-end``）置软删位并从检索索引摸掉（B9 纪律⑥）。

        **不删真源 md 文件**、**不建历史表**：撤回史只有 durable `memory_deleted` 事件一份；
        重复 ``idempotency_key`` 必须幂等。返回有界 receipt（命中条数与 path）。
        """
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


@dataclass(frozen=True, slots=True)
class CitationEntry:
    """一条**条目级**引用（§6.3）：粒度到 `path:start_line-end_line`，不是文件级。

    为什么必须到行区间：只到文件就分不清“模型真读了哪段”与“只是命中过”，
    写入噪声率（§10 指标）会假清零（命中 = 消费的错觉）。
    """

    path: str
    line_start: int
    line_end: int
    note: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.path, "CitationEntry.path")
        if self.line_start < 0 or self.line_end < self.line_start:
            raise ValueError("CitationEntry requires 0 <= line_start <= line_end")

    @property
    def entry_id(self) -> str:
        """条目级 id（与消费打点/索引共用同一粒度）。"""
        return f"{self.path}:{self.line_start}-{self.line_end}"

    def to_payload(self) -> JsonObject:
        body: dict[str, object] = {"path": self.path, "line_start": self.line_start, "line_end": self.line_end}
        if self.note:
            body["note"] = self.note
        return body


@dataclass(frozen=True, slots=True)
class MemoryCitation:
    """模型自报的“本轮引用了哪些记忆”（§6.3；仿 codex `memory_citation.rs`）。

    它是**事件字段**，不是 provider 输入：解析后从 assistant 正文剥掉，不进下一轮请求体。
    """

    entries: tuple[CitationEntry, ...] = ()
    rollout_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "rollout_ids", tuple(self.rollout_ids))

    @property
    def entry_ids(self) -> tuple[str, ...]:
        return tuple(entry.entry_id for entry in self.entries)

    def to_payload(self) -> JsonObject:
        return {
            "entries": [entry.to_payload() for entry in self.entries],
            "rollout_ids": list(self.rollout_ids),
        }


def citation_from_payload(payload: object, *, max_entries: int = 10) -> MemoryCitation | None:
    """把解析好的 dict 转成 typed 引用；非法/超上限条目**丢弃不猜**（宁缺不假归因）。

    上限与 `protocol/event.schema.json` 的 `maxItems` 同源，避免一条回答把引用面撞成堆。
    """
    if not isinstance(payload, dict):
        return None
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        return None
    entries: list[CitationEntry] = []
    for item in raw_entries[:max_entries]:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        start = item.get("line_start")
        end = item.get("line_end")
        if not isinstance(path, str) or not isinstance(start, int) or not isinstance(end, int):
            continue
        note = item.get("note")
        try:
            entries.append(CitationEntry(path=path, line_start=start, line_end=end, note=note if isinstance(note, str) else None))
        except ValueError:
            continue  # 行区间非法：丢掉这一条，不修正、不猜
    if not entries:
        return None
    rollouts = payload.get("rollout_ids")
    ids = tuple(str(item) for item in rollouts if isinstance(item, (str, int))) if isinstance(rollouts, list) else ()
    return MemoryCitation(entries=tuple(entries), rollout_ids=ids)


@dataclass(frozen=True, slots=True)
class RecallBlock:
    """一段可注入的召回正文（档2：**永不进 system**，只作 user-role 前缀消息）。

    ``entry_ids`` 是条目级 id，专给 ``memory_injected`` 做消费可归因用（§6.3）。
    """

    text: str
    entry_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.text, "RecallBlock.text")
        object.__setattr__(self, "entry_ids", tuple(self.entry_ids))

    def event_data(self, *, kind: str = "recall", max_ids: int = 40) -> JsonObject:
        """``memory_injected`` 载荷：只 kind/条目 id/计量，**无正文**（C18/C20）。"""
        return {
            "kind": kind,
            "entry_ids": list(self.entry_ids[:max_ids]),
            "lines": len(self.text.splitlines()),
            "bytes": len(self.text.encode("utf-8")),
            "truncated": len(self.entry_ids) > max_ids,
        }


@runtime_checkable
class EmbeddingPort(Protocol):
    """向量生成接缝（§6.2）：**只产向量，不管存储**（§20 C-3 单库约束）。

    入库仍必须走同一个 :class:`MemoryStorePort` 与同一份 `memory_chunks.embedding` 列；
    不得起第二 store/第二索引表。CI 无密钥时由 `providers/fake.py` 的确定性 fake 顶。
    """

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """一批文本 → 等长向量元组（一次调用处理 N 条，不逐条往返）。"""
        ...


#: 消费打点的层级枚举（与 wire `memory_consumed.kind` 同源；§6.3 要求 kind 级 + 条目级两层）。
CONSUMPTION_KINDS: frozenset[str] = frozenset({"memory_md", "index", "raw", "summary", "skills"})


def consumption_kind_for(path: str) -> str:
    """把记忆真源路径归到消费层级（“读了 MEMORY.md”与“读了 daily 原文”不是同一回事）。

    不确定时归 ``raw``（保守）；本函数入 L0 是因为 kernel（发事）与评测环（读数）都要用
    同一口径，两处各写一套就会分叉。
    """
    norm = (path or "").replace("\\", "/").lower()
    if norm.endswith("memory.md"):
        return "memory_md"
    if "skills" in norm:
        return "skills"
    if norm.startswith("dreams/") or "/dreams/" in norm:
        return "summary"
    if norm.startswith("index/") or "/index/" in norm:
        return "index"
    return "raw"


#: 模型自报引用的协议块标记（§6.3）；harness 解析后**从正文剥掉**，永不回送 provider。
CITATION_OPEN = "<citation_entries>"
CITATION_CLOSE = "</citation_entries>"

#: 引用条目上限（与 `protocol/event.schema.json` 的 `maxItems` 同源）。
CITATION_MAX_ENTRIES = 10


def parse_citation(
    text: str, *, max_entries: int = CITATION_MAX_ENTRIES
) -> tuple[str, MemoryCitation | None]:
    """从模型正文里剥出 ``<citation_entries>…</citation_entries>`` → (干净正文, 引用)。

    解析失败/形状非法 → 返回原正文 + ``None``（**不猜**：宁可少一份归因，也不记一条假的）；
    未闭合只剥标记、不动用户可见正文。解析成功则整块删除，不进下一轮请求体。
    入 L0 是因为 kernel（剥）、评测环（读数）与 surface 要用同一份解析口径。
    """
    if not text or CITATION_OPEN not in text:
        return text, None
    start = text.index(CITATION_OPEN)
    tail = text[start + len(CITATION_OPEN) :]
    if CITATION_CLOSE not in tail:
        return text.replace(CITATION_OPEN, ""), None
    body, rest = tail.split(CITATION_CLOSE, 1)
    cleaned = (text[:start] + rest).strip()
    try:
        payload: object = json.loads(body.strip())
    except (json.JSONDecodeError, ValueError):
        return cleaned, None
    citation = citation_from_payload(payload, max_entries=max_entries)
    return cleaned, citation


def recall_skipped_by_flags(flags: Mapping[str, object] | None) -> bool:
    """提交方 ``flags.skip_recall`` 的**唯一**谓词（B8 门控③）。

    放在 L0 是因为两头都要用：内核从 ``SubmitMessage.flags`` 读它，召回侧从自己的入口读它。
    不定义一份就会两处各写一套真值判定（开放词表里“什么算 true”很易漂）。
    未知 key 一律忽略（与 §20 C-6 的 source 口径一致）。
    """
    if not flags:
        return False
    value = flags.get("skip_recall")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@runtime_checkable
class RecallPort(Protocol):
    """记忆召回接缝（B8；§6.2）：内核只持本端口，不 import ``memory/``、不持 store 裸句柄。

    “三通道 + 三门控 + 终选”全部住在实现侧（`memory/recall.py`）；内核只问“本轮该注入什么”，
    拿回一个**已定界、已弹足计量**的块（或 ``None`` = 不注入）。返回块必须带 ``entry_ids``
    才能发 ``memory_injected``——**不可归因的召回不得注入**（门控②）。
    """

    async def recall(
        self, query: str, *, scope: MemoryScope | None = None, skip: bool = False
    ) -> RecallBlock | None: ...


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
    "ATTRIBUTION_VALUES",
    "VectorBackend",
    "MemoryStorePort",
    "CitationEntry",
    "MemoryCitation",
    "citation_from_payload",
    "EmbeddingPort",
    "RecallBlock",
    "RecallPort",
    "recall_skipped_by_flags",
    "CONSUMPTION_KINDS",
    "consumption_kind_for",
    "CITATION_MAX_ENTRIES",
    "CITATION_CLOSE",
    "CITATION_OPEN",
    "parse_citation",
]
