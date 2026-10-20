# ADR-0045: PolicyRegistry 落地 + `run_started.policy_ref`（状态/协议 additive + AB 分桶）

- 状态：✅（2026-10-18，P9 已实现并验证；实现见 [`../plan-archive/09-p9-openai-plugin-host.md`](../plan-archive/09-p9-openai-plugin-host.md) T1/T2/T3/T4）
- 背景：[`05-policy`](../design/05-policy.md) §2 定 `PolicyRegistry`（注册/发现/降级）归 P9、§3 定三条语义、§6 留"AB 分桶算法"待定；[`ADR-0009`](./0009-policy-pluggable.md) 已定"热替换=run 内快照冻结、换=新 run、AB 按 fingerprint、`run_started` 带 `policy_ref{id,fingerprint}`（只增字段）"。现状：`contracts/policy.py` 有 `PolicyPort`（`id`/`fingerprint`/`propose_action`/`init`/`dispose`），但**无 `PolicyRegistry`**；策略在 `surfaces/cli.py:133` 硬编码 `ReActPolicy()` 注入 loop；`run_started` 由 `state/reduce.py:191` 发、data 仅 `{run_id}`。既有可注册策略：`ReActPolicy`/`NullPolicy`/`MemoryAwareReActPolicy`。矛盾：registry 落哪层不破 C1、发现边界是否含磁盘扫描（防过度工程）、`policy_ref` 是状态+协议 additive 如何不 bump `v`。
- 决策：
  1. **`PolicyRegistry` 落 L4 `policy/registry.py`**（`check_layering_ast` rank 4）：只 import `contracts`；**kernel(L2) 绝不 import 它**——loop 仍只认注入的 `PolicyPort`（`loop.py:50/229`）。registry 的**解析发生在 surface/组合根**（`cli.py:133` 现装配点），解析得 `PolicyPort` 再注入 loop（C1 依赖方向不破）。
  2. **条目与解析**：`PolicyEntry{id, factory, trust(system|user|project), tools?, broken?}`；`register(entry)`/`resolve(policy_id, bucket_key)->PolicyPort`；**trust 优先级 project>user>system、最近根覆写重名**（design/05 §2）。
  3. **错误二分（留名不静默）**：`UnknownPolicyError`（id 写错，附名册）vs `BrokenPolicyError`（加载/部署错，附 reason、**破损项留名不静默消失**）。
  4. **降级 fail-open（C10）**：目标策略不可用 → 回落默认策略 + WARN，**绝不让 run 起不来**。
  5. **发现边界钉死 = 组合根注册固定名册，无磁盘扫描/HMR**（防过度工程，AGENTS §2）：cordis/DeepCode 的目录发现/HMR 属形状参照，本 Phase **不实现**运行时扫盘加载用户插件（那是 speculative infra、且触 IO/信任边界，非"能力热插拔不崩内核" DoD 所必需）。热插拔走 ADR-0046 的进程内 register/deregister + freeze 语义。
  6. **`policy_ref` 是状态+协议 additive、不 bump `v`**：新增 `PolicyRef{id, fingerprint}` frozen 值对象（`contracts/policy.py`）；`Run` 增 optional `policy_ref`（**默认 None=旧快照 `from_snapshot` 读得出、`store_schema_version` 不破坏性升版**）；创建 run 时（assembly 解析后）写入 → `reduce.py:191` 的 `run_started` data 带出 `policy_ref`；`EXTERNAL_EVENT_FIELDS[RUN_STARTED]` 加 `policy_ref`、`event.schema.json` `run_started.$defs` 加**可选** `policy_ref` 对象（先 schema→代码→TS codegen，C6/C15，design/02 §6）。
  7. **热替换 = 新 run 快照冻结、活 run 不 mid-swap（承 ADR-0009，不重决语义）**：换 registry 内容只影响**新 run 解析**；活 run 持其创建时注入的 `PolicyPort` + `Run.policy_ref` 快照不变。`--resume`（`rebuild_run`）从快照**恢复** `policy_ref`、**绝不重新解析**（否则撕裂，见 plan §4.3 M2）。
  8. **A/B 按 fingerprint 路由 + 分桶算法定死（design/05 §6 待定项落地）**：分桶键 = 内容 `fingerprint`（非版本号，ADR-0009 决策 2）；`bucket = stable_hash(fingerprint) % n`，`n` 默认 1（单桶=不分流的安全默认），算子可覆写**显式 split 表**（policy_id→权重）做灰度。回归网用 `run_started.policy_ref` 做同任务多策略对比，全程不动内核。
- 后果：
  - 正面：换/灰度/AB 策略只动 L4、不碰内核；错误不静默、破损可诊断；fail-open 保证 run 必起（C10）；`v` 不 bump、协议只增；发现边界不养投机基建。
  - 代价 / 需持续守：活 run 不能中途换策略（本就该如此，ADR-0009）；`Run` 多一 additive 字段 → 快照 round-trip 测试必须覆盖"旧快照无字段仍可读 + 新快照带字段"；AB 默认 n=1 = 不分流（保守，防误路由），要灰度需算子显式配置。
- 备选(被否)：
  1. registry 落 L6 surfaces 或组合根 → 否：策略解析是 L4 领域职责，塞进 surfaces 违分层且让"换策略动外层"。
  2. 现在就做磁盘扫描/HMR 加载用户策略插件 → 否：投机基建（AGENTS §2），且引入信任/IO/崩溃面；本 DoD 用进程内热插即可证伪。
  3. `policy_ref` 每次 propose 现算不快照 → 否：违"整 run 同一份"（ADR-0009），活 run 会因 registry 中途变化撕裂。
  4. AB 用版本号分桶 → 否：ADR-0009 明定按内容 fingerprint 非版本号。
- 关联：`ADR-0009`（本 ADR 落地其语义、不重决）；`05-policy.md` §2/§3/§6（§6 由此转"已定")；`ADR-0020`/`ADR-0021`（快照/resume）；`ADR-0046`（能力热插拔宿主，registry 之外的 plugin host）；HARD-CONSTRAINTS C1/C6/C10/C11/C12/C15；`contracts/policy.py:91` `PolicyPort`、`kernel/loop.py:389-395`（policy 故障隔离已存）。
