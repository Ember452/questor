# 计划 04：personal 就绪（主动运行时与三个 runtime 位的消费方落地）

- Status: Draft Rev1（2026-10-27，自仓外分析文档采纳进仓；本文件自包含，仓外原文不再链接）
- 基线：`main` @ `396b862`（工作树干净，8 个本地分支全部已并入）
- 决策依据：[ADR-0006](../adr/0006-serve-host-and-wire-protocol.md)（事件只加不改）·
  [ADR-0008](../adr/0008-profile-driven-modes.md)（形态与 runtime 位）·
  [ADR-0009](../adr/0009-proactive-runtime.md)（主动运行时裁决本体）·
  [ADR-0010](../adr/0010-journal-write-order.md)（存储格式草案，实施在 B0）
- 形态映射：[mapping/questor-personal.md](mapping/questor-personal.md)
- 纪律：一刀一条短分支；每刀动手前先建**本条**红用例；L3 刀独占批次；行为变更与
  `docs/` 更新同一刀（CONVENTIONS §5.5）；评测场景只作周度参考信号，不进 CI 门禁。

## 0. 怎么用

- 影响面分级：**L0** 叶子包纯函数/纯数据（可批量）；**L1** 单层内加挂点（每条自带
  红用例）；**L2** 跨层接缝（Port + fake + 一个真实消费者，单独成刀）；**L3** 协议/
  执行拓扑/存储格式（每刀只做一件，独占批次，可一键回滚）。
- 来源分两类：**实现供体**（有完整 Python 实现，连测试一起移植，一个条目只认一个
  供体）；**机制证据**（只取机制、常数与踩坑结论，不搬代码也不搬测试）。判据：
  出错时能不能 diff 供体。
- 每刀交付三张对账表（§3 骨架）；台账（§6）任一刀三表缺失视为该刀未完成。
- 开工前：`uv run python scripts/check.py --fast` 看基线；交付前跑全量
  `uv run python scripts/check.py`。

## 1. 出口定义

| 轮 | 出口（可验证） |
| --- | --- |
| **A-1 最短闭环** | 手机上能收到一条真实提醒；工具调用台账逐条可回放；强杀进程后已提交回合不丢、遗留 running 全转 interrupted |
| **A-2 加固** | `personal.yaml` 三个 runtime 位（schedule/delivery/memory_consumption）全部有真实消费方；主动行为可被一句"降低主动等级"收敛；写坏的可用一条命令退回上一版 |

## 2. 刀序

### A-1 最短闭环（约 8–10 刀，按序）

| 刀 | 目标 | 唯一供体 | 层 | 判红一句话 |
| --- | --- | --- | --- | --- |
| **A0**（本刀，已完成裁决部分） | ADR-0009/0010 + 本计划 + `personal.yaml` 消费方登记 + 路由 | 无（裁决刀） | docs | 文档守卫全绿（可达性/死链/代码路径/结构基线） |
| **A1** 观测先行 | 工具调用台账落 JSONL 旁路（只记账不重放，字段含 `turn_kind`）；重复工具调用滑窗 + 重复回复阈值**只报不改**；成本归因加 `turn_kind` 维度 | 台账形状 = 机制证据（wuu toolledger）；循环检测 = 机制证据（AG2 LoopDetector / OpenManus） | L1 | 构造循环能被识别；无 provider 调用也记账；台账逐条可回放 |
| **A2** 时序纪律 + 写序 | 重启把遗留 `running`（任务/cron run）标 `interrupted` 不盲重放；快照写入点移到产出可见**之前**；投递晚于提交 | flow-agent（恢复语义，机制证据） | L1（行为时序，无 schema 变更） | 强杀进程后已提交回合不丢（`tests/fixtures/persistence/v1/session.json` 仍是活守卫）；投递失败不留半成品 |
| **A3d** 检索降级链 | keyword FTS5（ASCII）→ trigram FTS5（CJK，SQLite 3.34+）→ LIKE 兜底 →［可选］向量；四个边界处理照搬（可用性探测 / trigram 跨版本自动 detach / embedding 缺失静默降级 / 向量 BLOB 无 numpy 退纯 Python） | CowAgent `agent/memory/`（实现供体，连测试移植） | L1/L2 | 无 embedding key、无 numpy、无 sqlite-vec 时检索仍返回结果；删掉索引库能从文件全量重建 |
| **A4** 触发层升级 | `trigger: {kind: cron \| at \| every}`，`at` 跑完自动归档；跨进程原子 claim + run lease + 僵尸收割（防调度守护进程与宿主双触发）；**进程内回合 runner** 替换子进程 `--print` 执行 | 触发拓扑 = Reasonix（机制证据）；进程内回合执行形状 = CowAgent scheduler（实现供体） | L1→L3（本阶段唯一改执行拓扑，独占批次） | 双进程同 tick 不双触发；租约到期可回收；一次 `at` 只跑一次；进程内回合能读到同 session 记忆作用域 |
| **A4.5** actor 身份 | policy 判定上下文加可选 `actor`（现 `capabilities/policy/checker.py:75 evaluate()` 输入无身份概念）；角色映射数据落 `src/questor/gateway`（照 `managed_group_checker` 注入模式） | 无（仓内既有载体可选字段模式） | L2 | 同一"谁能用哪个工具"判定能按 sender 得出不同结果；非白名单角色的 privileged 命令被拒 |
| **A5-lite** 守门器 lite | 只做三条：每日上限 + 安静时段 + 跳过可观测；档位=参数组（定义落 `src/questor`，求值器落 `capabilities/policy`）；投递接 `gateway/notify.py:81` 已注册的 `feishu_dm` | **无实现供体**（CowAgent scheduler 的 quota/quiet 全 0）——按机制证据自研，一条一刀 | L2 | 配额耗尽静默跳过且跳过可观测；安静时段零投递；每条主动消息能指回 evidence |
| **A6-lite** 模型可见面 lite | 主动事件 + thinking 帧 + catalog kind 同刀进 `contracts/domain/events.py` / wire / schema / 双侧 codegen / `wire_view` / `apps/web`，同刀刷新 prompt_surface 与 tool_metadata golden；thinking 三处上限对齐（推流=落库=渲染），**只进 UI 不进回灌 messages** | thinking 上限与能力表 = CowAgent `agent/protocol/agent_stream.py`、`models/reasoning_capabilities.py`（实现供体） | L3（独占批次） | 新增 kind 在 codegen `--check` 下不陈旧；thinking 帧出现在 UI 但不在回灌 messages 里；旧快照仍可加载 |
| **A10-lite** 渠道里程碑 | feishu 适配器补齐 A5b 需要的契约字段，打通第一条真实投递闭环 | —— | L1 | 手机收到一条真实提醒；台账可回放该提醒从触发到投递的全链路 |

> A6-lite 即"思考过程不可见"的修复刀：provider 侧已抓到 `reasoning_content`
> （`providers/llm/openai_client.py` 流式累积，仅用于回灌），链路断在 events.py
> 无 thinking 类、wire 无帧——补传送不补发明。

### A-2 加固（有真实流量后，按需排期）

| 刀 | 目标 | 供体 | 层 |
| --- | --- | --- | --- |
| **A3a′** | `scan` 加 category/作用域过滤入参，接 A3d 查询参数 | CowAgent | L1 |
| **A3b′** | 写回决策 ADD/UPDATE/DELETE/NOOP 显式化 + `supersedes` 写入方（顶替旧值）+ 写入走 outbox | mem0 / hindsight（机制证据） | L1 |
| **A3c** | `usage.py:mark_memory_used` 接成 evidence 记录，供守门器强制引用 | 仓内已有 | L1 |
| **A5 完整版** | 降档（被忽略/负面回应 N 次）、语义近重、冷却、忙碌门——阈值用 A1 台账跑出的真实数据定 | 机制证据（akashic 五段管线 Gate→Fetch→Judge→Resolve→Deliver） | L2 |
| **A6 完整版** | 三个 runtime 位全接消费方，`personal.yaml` 逐键给档；provider 能力表（哪家能思考/effort 档位/hybrid 可关） | CowAgent `reasoning_capabilities.py` | L2 |
| **A7** 缓存与成本 | provider 缓存探针 → 断点策略；记忆冻结快照（session 起点冻结进 prompt，中途写盘不破前缀缓存）；微压缩编辑不破前缀 | hermes（机制证据） | L3 |
| **A9** | 写前快照 + undo + 保留窗口（`platform/` 原语，目标 <150 行） | CowAgent `agent/evolution/backup.py`（实现供体） | L1 |
| **A5b** | 渠道消息契约一次定宽（媒体/引用/@提及/群事件/回执/分段/语音/超时），此后一家渠道一个 PR | —— | L3 |

## 3. 三张对账表骨架（每刀交付时回填）

**B-1 条目对账**（条目 → 实现位置 / commit）

| 条目 | 实现位置 | commit |
| --- | --- | --- |
| （待 A1 起回填） | | |

**B-2 影响面对账**（被改文件 → 上下游消费者）

| 被改文件 | 上下游 | 是否 L3 |
| --- | --- | --- |
| （待回填） | | |

**B-3 判红对账**（红用例 → `测试文件::用例`）

| 刀 | 红用例 | 命令 |
| --- | --- | --- |
| （待回填） | | |

## 4. 裁决记录（2026-10-27 采纳，全部取分析默认值）

1. 来源按两类对待：实现供体连测试移植，机制证据只取机制——采纳。
2. 主供体为 CowAgent（同语言、同形态、渠道/记忆/定时全供得起，测试可搬）——采纳。
3. MemoryPort 契约化排在 personal 语义做实之后（没有真实消费者的 Port 不建，
   ADR-0002 第 13/17 条）——采纳。
4. A4 进程内回合约入本轮（否则每条提醒都是冷启子进程、无会话连续）——采纳。
5. ADR-0010 与 A0 同期起草、实施推迟 B0——采纳（本文档配套已起草）。
6. KG 实体图排在 A7 之后、B 之前——采纳（本计划内不动）。
7. 终端/前端其余工作顺延；前序"脏树"阻塞已解除（PR #225 已并入 main）——记录。
8. A5 无实现供体，先做 lite（每日上限 + 安静时段 + 跳过可观测），完整版等真实
   流量——采纳。
9. A 段分两轮（A-1 约 8–10 刀先上线，A-2 加固靠真实数据定参）——采纳。

## 5. 非目标（本轮不做）

- durable spine 完整版与 journal/append-only 实施（ADR-0010 草案已立，实施在 B0，
  需单独预算排期；A2 的写序是行为时序，不在此列）。
- rewind / 会话树 / fork / clone / FTS5 历史搜索——属存储迁移，ADR-0010 实施后另排。
- 多 agent 新开包——`runtime/swarm` 等四个包已存在，只需 B4 接线体检，不再开第五个包。
- best_of_n / DAG 规划 / A2A / ACP / codemode / BM25 工具推荐——编码形态远期。
- OS 沙箱 / 容器沙箱——personal 用不上，归编码段。
- 融合检索 + rerank + 知识图谱——等 embedding 真跑起来、A3d 三级链稳定后再谈。
- 多租户 / 计费席位 / 反检测浏览器 / 远程会话 / gRPC 分布式——部署形态不匹配。
- 空壳测试、为指标达标而做的拆分——一律拒绝，指标差距如实上报。

## 6. 总验收表（每刀回填）

| 刀 | 分支 | 绿验收 commit | 红验收 commit | 备注 |
| --- | --- | --- | --- | --- |
| A0 | （待授权后开短分支 docs/personal-readiness-a0） | 待回填 | ——（无行为变更，无红用例） | ADR-0009/0010 + 本计划 + personal.yaml 登记 + AGENTS.md 路由 |
