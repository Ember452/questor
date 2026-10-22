# Questor Memory Provider Contract（v1 设计记录）

- 状态：设计记录（Design），Phase 3 才实施；当前不写代码
- 日期：2026-10-22
- 相关：[STRUCTURE](STRUCTURE.md)、[ADR-0004](../adr/0004-memory-provider-contract.md)、[MIGRATION](MIGRATION.md)
- 目标：让一个外部 memory 项目（库、服务、或自研实现）可以接入 questor，并且**不破坏作用域、不阻塞 turn、不制造第二真相**

---

## 0. 结论

1. **memory 不是“插件直接挂到 loop 上”**。它是三层：`Policy`（宿主策略）→ `MemoryPort`（契约）→ `Provider`（外部实现）。
2. **宿主拥有真相与作用域，provider 只拥有索引与检索**。当前真相载体是**会话快照**（不预设事件溯源）；memory 是派生索引，必须可审计；能重建则声明 `rebuild`，不能则显式标 `derived=false`。
3. **“不出问题”不靠接口定义，靠四件事**：作用域由宿主构造、失败可降级、写入可重放、契约有 conformance。
4. **personal / coding 的差异在 Policy，不在 Provider**。同一个 provider 可以被两种模式复用；否则一定会出现两套 memory 分叉。

---

## 1. 参考项目：它们各自怎么接 memory

| 项目 | memory 的形态 | 扩展缝 | 最值得抄 | 不要抄 |
|---|---|---|---|---|
| **Cordis** | 不是 memory，是服务宿主 | `Service`、`ctx.inject/provide`、`ctx.isolate`、`ctx.effect`、`Fiber` 状态机、loader 配置树 | 生命周期、依赖注入、作用域隔离、配置校验、失败状态 | 整套 meta-framework |
| **Pi** | 没有 memory 抽象；session tree + compaction 是原生记忆 | extension API：`before_agent_start`、`agent_end`、`session_start/shutdown`、`registerTool`、`appendEntry` | 核心与 memory 解耦；插件可关、可降级 | 只靠 prompt 注入；没有宿主级作用域/事务 |
| **Claude Code** | 文件型 auto memory：`MEMORY.md` + 主题文件；4 类（user/feedback/project/reference） | hooks + plugins + MCP + skills | 可检查、索引化、Dream 整理、门控/锁、文件即真相 | 每个 agent 各写一套；没有 provider 契约 |
| **Codex** | 原生 `memories/read` + `memories/write` 两条流水线 | 内部 crate + hooks/plugins | 读写分离、两阶段后台整理、citation/usage、rate-limit guard、symlink 防护 | 绑定自家 rollout/模型的 pipeline |
| **Reasonix** | 本地 memory 域模型：`Memory{ID, Revision, Scope, Type, SubjectKey, ExpiresAt, LastVerifiedAt, Keywords}` + `MEMORY.md` 索引 | `state/memory` + `Set/Compose` + `Queue` + `memory` 工具 | 单一写入口、project/global 作用域、typed queue、freshness/expiry/audit、迁移 | 纯文件、无多端同步 |
| **mem0** | 外部 memory 服务 + 插件 SDK | `agent-plugin-core` 共享核心 + 每宿主 adapter + manifest + hooks + MCP + skills + conformance | 适配器层、共享核心、能力矩阵、自包含包、离线/在线 conformance | 每个 host 复制一套实现 |
| **Hindsight** | 独立 memory 服务 | `retain / recall / reflect` + banks + MCP + 多宿主集成 | 服务边界、租户/银行隔离、跨 agent 复用 | 重服务、非本地优先 |
| **CowAgent** | 本地混合检索 memory | `manager/service/storage/conversation_store/chunker/reranker/embedding/rebuild` | chunk、vector+keyword、rerank、summarize、rebuild 的内部分层 | 没有 Port；换后端要改调用方 |
| **DeerFlow** | feature flag + middleware + backend | `RuntimeFeatures.memory: bool \| AgentMiddleware`；`memory/backends/{mem0,honcho,deermem}` | 配置驱动选择后端；backend 按子目录拆 | `middlewares` 平铺；memory 策略不要塞进 middleware 堆 |

三条判断：

- **内建**（Codex/Reasonix/Claude/CowAgent）强在一致性和可调试，弱在不可插；
- **外部服务**（Hindsight/mem0）强在可复用和跨 agent，弱在网络、超时、作用域、双写；
- **扩展钩子**（Pi、mem0 的 Pi/Claude 插件）最容易接，但作用域、幂等、写入重放全靠插件自觉。

questor 要的是“内建的一致性 + 外部的可插拔”，所以必须把 **Policy / Port / Provider** 分开。

---

## 2. 三层架构

```text
runtime/turn
  before_agent_start / turn_end / session_start / session_end
        │
        ▼
capabilities/memory            ← 宿主策略（Policy）
  scope 解析 · top_k/max_chars · 召回门控 · 脱敏 · citation
  写入纪律 · outbox · 熔断 · 降级
        │
        ▼
MemoryPort                     ← 契约（Port，放 contracts/ports/memory.py）
  start/stop/health/capabilities/write/search/get/forget
        │
        ▼
providers/memory/<provider>    ← 适配器（外部 memory 项目）
  file · sqlite · mem0 · hindsight · 自研
```

谁调谁：

| 调用方 | 被调方 | 说明 |
|---|---|---|
| `runtime/turn` | `ContextAssemblerPort` / `TurnSettlerPort` | runtime 不认 memory；只认上下文装配与结算端口 |
| `capabilities/context` | `MemoryPort.search` | 召回作为上下文的一个贡献者 |
| `capabilities/memory` | `MemoryPort.write/forget/consolidate` | 写入、删除、整理 |
| `providers/memory/<id>` | 实现 `MemoryPort` | 只做存储/检索/映射，不碰领域状态 |
| `bootstrap` | 构造并注入 | 唯一装配点 |

`runtime` 永远不知道 memory 存在；模式差异落不到循环里。

---

## 3. `MemoryPort` v1

核心接口只保留最小集合；整理/重建是可选维护能力，不强迫简单 provider 实现。

> 下面只列契约形状；`MemoryContext`、`ConsolidateRequest`、`Event` 等辅助类型在同文件定义，代码块假定 `from __future__ import annotations`。

```python
class MemoryScope(StrEnum):
    GLOBAL = "global"
    USER = "user"
    PROJECT = "project"
    SESSION = "session"
    RUN = "run"

class MemoryKind(StrEnum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"
    LESSON = "lesson"

@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: Literal["user", "assistant", "tool", "system"]
    session_id: str
    run_id: str
    turn_id: str
    event_id: str
    message_id: str | None = None

@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: str
    revision: int
    scope: MemoryScope
    kind: MemoryKind
    title: str
    body: str
    subject: str | None
    keywords: tuple[str, ...]
    source: SourceRef
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    last_verified_at: datetime | None = None

@dataclass(frozen=True, slots=True)
class RecallQuery:
    text: str
    scope: MemoryScope
    kinds: frozenset[MemoryKind] = frozenset()
    limit: int = 5
    max_chars: int = 4_000
    min_score: float = 0.0
    session_id: str | None = None
    as_of: datetime | None = None

@dataclass(frozen=True, slots=True)
class RecallHit:
    record: MemoryRecord
    score: float
    snippet: str
    citation: Citation

@dataclass(frozen=True, slots=True)
class MemoryWrite:
    scope: MemoryScope
    kind: MemoryKind
    title: str
    body: str
    subject: str | None
    keywords: tuple[str, ...]
    source: SourceRef
    ttl: timedelta | None = None

@dataclass(frozen=True, slots=True)
class WriteResult:
    id: str
    revision: int
    created: bool

@dataclass(frozen=True, slots=True)
class ForgetResult:
    deleted: int
    tombstones: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class Health:
    state: Literal["ok", "degraded", "unavailable"]
    detail: str = ""

@dataclass(frozen=True, slots=True)
class Citation:
    memory_id: str
    source: SourceRef
    snippet: str

@dataclass(frozen=True, slots=True)
class Capabilities:
    contract: str                 # "questor.memory/v1"
    scopes: frozenset[MemoryScope]
    kinds: frozenset[MemoryKind]
    maintenance: frozenset[str]   # {"consolidate", "rebuild", "export"}
    consistency: Literal["read-your-writes", "eventual"]
    max_body_chars: int
    max_query_chars: int
    max_results: int
    p95_budget_ms: int

class MemoryPort(Protocol):
    async def start(self, ctx: MemoryContext) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> Health: ...
    def capabilities(self) -> Capabilities: ...

    async def write(self, req: MemoryWrite, *, idempotency_key: str) -> WriteResult: ...
    async def search(self, query: RecallQuery) -> list[RecallHit]: ...
    async def get(self, ids: Sequence[str]) -> list[MemoryRecord]: ...
    async def forget(self, ids: Sequence[str], *, reason: str) -> ForgetResult: ...

class MemoryMaintenancePort(Protocol):
    async def consolidate(self, req: ConsolidateRequest) -> ConsolidateResult: ...
    async def rebuild(self, events: Iterable[Event], *, scope: MemoryScope) -> RebuildResult: ...
```

错误分类固定，provider 不要抛裸异常：

```python
class MemoryError(Exception): ...
class MemoryUnavailable(MemoryError): ...
class MemoryTimeout(MemoryError): ...
class MemoryRateLimited(MemoryError): ...
class MemoryInvalidRequest(MemoryError): ...
class MemoryConflict(MemoryError): ...
class MemoryUnauthorized(MemoryError): ...
```

`Capabilities` 的作用：**启动时校验、运行时降级、UI 显示三态**（`ready / declared / absent`）。provider 不支持 `rebuild`，就明确标 `derived=false`，不要假装它能重建。

---

## 4. Manifest、注册与配置

外部 memory 项目不需要改写成 questor 的形状，写一个薄 adapter：

```text
my-memory-provider/
├─ pyproject.toml
│    [project.entry-points."questor.memory"]
│    my_memory = "my_memory.manifest:MANIFEST"
├─ src/my_memory/
│  ├─ manifest.py      # id / contract / version / factory / config_schema
│  ├─ provider.py      # 实现 MemoryPort，内部调你已有的 memory API
│  ├─ mapping.py       # scope/kind/error 映射
│  ├─ store.py         # 你原来的存储
│  └─ health.py
└─ tests/
   └─ test_conformance.py
```

```python
MANIFEST = MemoryManifest(
    id="memory:my_memory",
    contract="questor.memory/v1",
    version="1.0.0",
    factory=build_provider,
    config_schema=MyMemoryConfig,
    requires=frozenset({"filesystem", "secret:MY_MEMORY_KEY"}),
)
```

宿主配置：

```yaml
memory:
  provider: memory:my_memory
  required: false          # true 则启动失败即拒绝启动
  policy: memory:personal
  config:
    endpoint: ...
```

`profiles` 只选 policy；`bootstrap` 选 provider。两者分开，模式就不会绑死后端。

---

## 5. 宿主侧必须做的 10 件事

1. **契约版本 + manifest + capability 协商**：contract 不匹配，启动即失败；能力不匹配，降级而不是崩。
2. **作用域由宿主构造**：`MemoryScope` 由 `capabilities/memory` 根据 session/project/config 生成；模型不能自己指定 global。
3. **单一写入口 + 幂等键**：`write` key = hash(scope + kind + subject + body + source_event)；重复写收敛为一条。
4. **写入 outbox**：turn 结束时只写 `MemoryWriteIntent`，后台 worker 调 provider；provider 挂了也不阻塞 turn。
5. **召回 fail-open**：`search` 超时/500/限流 → 返回空 + 指标 + 熔断，不把异常抛给 loop；只有 `required=true` 的 profile 在启动时 fail-closed。
6. **预算**：`top_k`、`max_chars`、`max_tokens`、`p95_budget_ms` 四道闸；截断要带显式标记，不能静默。
7. **脱敏 + 提示词注入防护**：写入前 redaction；召回内容当不可信数据，带 citation，不允许其中的指令触发工具。
8. **citation / provenance**：每条 hit 带 `SourceRef`（session / run / turn / message 指针；若将来立项 durable，再扩展为 `event_id`）；UI 能展开；审计能追到原始 turn。
9. **删除/墓碑/重建**：`forget` 幂等 + 墓碑；`rebuild` 必须尊重墓碑，不能把删掉的记忆重建回来。
10. **隔离与安全**：provider 不能 import `kernel`、不能读事件流、不能写领域状态；文件 provider 防 symlink/path traversal；HTTP provider 防 SSRF、限制响应大小。

---

## 6. 失败语义

| 失败 | 前台影响 | 行为 |
|---|---|---|
| provider 未配置 / 未实现 | 无 | `absent`，UI 显示；profile 不要求就继续 |
| 启动健康检查失败 | 无（可选）/ 拒绝启动（required） | `declared` 或 fail-closed |
| 召回超时 / 500 / 限流 | 无记忆注入 | fail-open + 指标 + 熔断，半开重试 |
| 写入超时 / 500 | turn 正常结束 | 进 outbox，后台重试；幂等键防重 |
| 重复写 | 无 | 幂等键收敛 |
| 整理失败 | 无 | 后台退避重试，不阻塞 |
| provider 崩溃 | 无 | supervisor 重启；outbox 重放 |
| 契约不匹配 | 启动失败 | 硬失败，不允许半兼容 |
| 单条记录损坏 | 无 | 跳过 + quarantine + 指标 |
| `forget` 后重建 | 无 | 墓碑生效，不得复活 |
| 跨 scope 查询 | 无 | 宿主层拒绝，不依赖 provider 自觉 |

---

## 7. Conformance 套件

provider 必须通过以下测试，才能进入 `providers/memory/`：

- CRUD + 幂等；
- scope 隔离（A 的 project 不可见 B；global 只有显式授权才可见）；
- 召回 limit / min_score / max_chars / 稳定排序；
- `forget` 后不可见，rebuild 后仍不可见；
- 超时/500/畸形响应 → 宿主降级，不抛到 loop；
- 重启/重载 → 无重复写，outbox 排空；
- schema 版本旧记录可读；
- 性能 p95 在预算内。

建议目录：tests/conformance/memory/（当前不存在，随第一个 provider 一起建），provider 包把它作为 dev dependency 引入。

---

## 8. 上线顺序

```text
NullMemory（no-op）
  → FileMemory（MEMORY.md + 主题文件，Claude/Reasonix 风格）
  → SQLiteMemory（结构化、可索引、可迁移）
  → 外部 adapter（mem0 / Hindsight / 自研）
```

每个新 provider 都走：

1. **conformance**：离线全绿；
2. **shadow**：只读，和旧 provider 对比同一 query 的命中，不写；
3. **canary**：按 profile/session 灰度 5%，配置一键回滚；
4. **cutover**：旧 provider 保留一个版本窗口，支持回滚。

---

## 9. 映射到 questor 包结构

下面的路径都是**目标位置，当前均不存在**（Phase 3 才建；`contracts` 也是其中之一）：

```text
契约（MemoryPort / MemoryRecord / RecallQuery / 错误）
  -> src/questorharness/contracts/ports/memory.py
召回写入整理策略 / scope / outbox / citation
  -> src/questorharness/capabilities/memory/
provider 实现
  -> src/questorharness/providers/memory/<provider>/
模式选择（profile）
  -> src/questorharness/profiles/<mode>/profile.yaml
装配
  -> src/questorharness/bootstrap/compose.py
契约测试
  -> tests/conformance/memory/
```

审计与去重：由 `capabilities/memory` 自己写轻量审计日志（JSONL：provider id、record id、内容 hash、scope、SourceRef、结果）+ 幂等键。**不依赖事件流，也不进 kernel**；recall 全文不落盘，只记指标。

---

## 10. 非目标

- **provider 拥有领域真相**：不允许；当前真相是会话快照，provider 只拥有自己的索引与存储。
- **依赖 durable 事件流做审计**：不允许（durable 未立项）；审计走 memory 自己的日志。
- **同步远程召回**：默认不允许；必须经过 timeout + circuit breaker。
- **跨设备 exactly-once**：当前只保证 at-least-once + 幂等；跨进程租约单独 ADR。
- **模型自选 global scope**：不允许；global 必须由配置/用户显式授权。
- **memory 内容触发工具**：不允许；memory 是不可信数据，只做上下文。
- **一次做完所有 provider**：先 Null/File/SQLite，外部 adapter 后置。

---

## 11. 待定问题

1. `FileMemory` 的文件格式：`MEMORY.md` 索引 + 主题文件（Claude/Reasonix），还是单文件 SQLite？
2. 审计日志的字段清单：只记元数据 + hash，还是记正文摘要？（不依赖事件流，见 §9）
3. embedding/rerank 由宿主提供还是 provider 自备：建议 `EmbedderPort` 在 contracts，provider 可选注入。
4. personal / coding 的默认 policy 参数：top_k、max_chars、consolidation 时机。
5. 是否允许 provider 直接读写工作区文件（FileMemory 需要）：建议只允许 `memory` 目录，路径由宿主注入。

---

## 12. 参考文件

以下都是**外部仓库的路径**（供查阅，不在本仓），故意不加反引号以免当成仓内引用：

```text
Cordis      packages/core/src/{service.ts, fiber.ts, registry.ts}; packages/loader/src/config/entry.ts
Pi          packages/coding-agent/docs/extensions.md
mem0        integrations/agent-plugin-core/README.md; integrations/pi-agent-plugin/src/entry.ts;
            integrations/claude-code-plugin/hooks/hooks.json
Claude Code docs/features/auto-dream.md
Codex       codex-rs/memories/read/src/lib.rs; codex-rs/memories/write/src/lib.rs
Reasonix    internal/state/memory/{store.go, memory.go, recall.go, queue.go};
            internal/assembly/boot/memoryset.go
Hindsight   README.md（retain / recall / reflect、banks、MCP）
CowAgent    agent/memory/{manager.py, storage.py, conversation_store.py}
DeerFlow    backend/packages/harness/deerflow/agents/memory/; agents/features.py 的 RuntimeFeatures.memory
```
