# R05 · PolicyPort 可插拔性 —— 外部参考扫描与决策建议

> 这是一份**参考扫描 + 决策报告**（R 前缀，非承重接缝文档），服务于一个具体问题：
> **questor 的 L4 策略（`PolicyPort`）要不要单开一份 `design/05-policy.md`，还是并入 `design/04-turn-loop.md`？**
> 目标设计口径（用户给定）：**策略 = 只读状态视图 → 返回 Command 意图；策略可注册 / 热替换 / A-B；进程内默认、远程预留。**
> 本报告只做设计输入，不含实现代码。所有结论尽量落到 `文件:行号`。

---

## 0. 结论先行（TL;DR）

1. **单开 `design/05-policy.md`，但把它定位为「04 的姊妹/纵深文档」，不是第六道承重接缝。**
   - 理由：`PolicyPort` 的**契约**（L0 接口 + 注册表 + 热替换/灰度/AB + 生命周期/故障隔离 + 远程预留）是 **L4 关注点**；`04` 明确是 **L2 Kernel「只调度不思考」**（`04:4`）。把 L4 契约塞进 L2 文档会破坏 questor 自己立的「变更域隔离」纪律（`00 §3.2`、`C1/C14`）。
   - 但**不重排**「五道接缝」这个既有口径：`ROADMAP §0`、`VISION §8`、`04 §74` 都写死「五接缝齐全=可开发门槛」。05 是**在门槛之上的纵深**，不新增承重墙。
2. **P1 只需 05 的「最小进程内」子集**（`propose_action(view)->intent` + 非法意图不崩 + panic 回滚），**注册表/热替换/AB/远程全部后置 P9**（对齐 `ROADMAP` P9 插件宿主、`C12` 预留非现在）。因此 05 **不阻塞 P1 开工**。
3. **三家实扒高度收敛到同一条设计主轴**（可直接抄「形状」，不抄代码）：
   - 策略是**声明式组合数据**（persona/allowlist/工具/输出 schema），不是散落的 if-else；
   - **解析一次、按值快照、run/会话内冻结**（换算法只影响新 run）——三家一致；
   - 注册表**按内容指纹寻址**、**破损留名不静默消失**、**未知 id 是调用方的错**；
   - 策略**只能收窄能力、只能提议**，写/执行/记账全在 Harness（dispatch-side 白名单 + 强制 capture + Command 总线）。
4. 建议随 05 落一条 **ADR-0009「策略可插拔机制」**（记录「run 内快照冻结 / 热替换=新 run / AB=按 fingerprint 路由」这三条硬决策 + 被否方案）。

---

## 1. 阅读范围与方法（按 `AGENTS §0`：读全/别偷懒，越界处明说）

**读全（整文件读）：**
- MetaGPT：`metagpt/roles/role.py`、`metagpt/actions/action.py`、`metagpt/actions/action_outcls_registry.py`、`metagpt/context.py`、`metagpt/context_mixin.py`、`metagpt/environment/base_env.py`、`metagpt/strategy/base.py`、`metagpt/strategy/planner.py`、`metagpt/strategy/solver.py`。
- DeepCode：`core/agent_presets/__init__.py`、`core/harness/agents/__init__.py`、`core/harness/agents/structured_result.py`、`core/harness/agents/control.py`、`workflows/__init__.py`、`workflows/workflow_context.py`。
- hermes：`agent/learn_prompt.py`、`agent/learning_graph.py`。

**采样（超大文件，只精读「策略外置」相关区，其余用签名索引定位）：**
- `MetaGPT/metagpt/actions/action_node.py`（877 行）：读 `1-230`（枚举/模板/`ActionNode` 字段与注册），其余 `230-877` 为 fill/parse/review/revise 提示词组装，**与 PolicyPort 契约相关性低，未逐行读**。
- `hermes/agent/background_review.py`（1342 行）：读 `1-120 / 228 / 957-1180 / 1302-1342`（模块 docstring、fork、dispatch-side 白名单、spawn），中间提示词/统计未逐行读。
- `hermes/agent/curator.py`（1213 行）：读 `1-90` 头部 + `160/209/915/1198` 关键函数签名（`should_run_now / apply_automatic_transitions / run_curator_review / maybe_run_curator`），主体生命周期算法未逐行读。
> 采样目标：只取「策略=数据/注册/快照/受限/生命周期/隔离」证据；这三者的完整算法不在本次 PolicyPort 决策的关键路径上，故按需精读。若后续实现 05，需回到这些文件补全相关算法。

**先读的 questor 文档**：`design/00/01/02/03/04`、`HARD-CONSTRAINTS`、`VISION`、`STRUCTURE`、`ROADMAP`、`adr/0004/0008`、`AGENTS`、`CLAUDE`。

---

## 2. 实扒证据 —— 三家怎么把「策略」外置

### 2.1 MetaGPT：策略=可切换的 react 模式 + 消息总线解耦协调

| 机制 | 证据（文件:行号） | 对 questor 的启发 |
|---|---|---|
| **一个 Role 内挂三种策略**（REACT / BY_ORDER / PLAN_AND_ACT），用枚举 + 一个 `react()` 入口分发 | `role.py:82-89`（`RoleReactMode`）、`role.py:512-523`（`react()` 三选一）、`role.py:261-282`（`_set_react_mode` 设策略与 `max_react_loop`） | 「换 ReAct→ToT」= 切一个字段，不动循环骨架——正是 `00 §3` 表「换算法只 L4」的现实版 |
| **策略「读状态→出意图」的最小形状**：`_think` 读 `history` 让 LLM 选下一状态；`propose(current_state)->str` 是 ToT 求解原语 | `role.py:340-379`（`_think`：`STATE_TEMPLATE` `role.py:54-69` + `next_state = await self.llm.aask(prompt)` `role.py:367`）；`strategy/base.py:16-17`（`BaseParser.propose(current_state)`，配套 `sample:19`、`value:22`） | `propose(view)->intent` 就是 `PolicyPort.propose_action` 的抽象原型；`propose/sample/value` 三原语可作 ToT 类策略的注册契约 |
| **求解策略是同一接口的多实现**（`BaseSolver.solve()`：Naive/ToT/ReAct/CoT/…） | `strategy/solver.py:15-31`（抽象 `solve`）、`35/45/59/73`（Naive/TOT/ReAct/COT 各自实现） | 「策略可注册」= 面向一个 `solve/propose` 协议多实现；questor 的 `PolicyPort` 需同样能承载多种算法族 |
| **策略与执行分离**：`_act` 只跑 Action 产 Message，不碰沙箱/持久化 | `role.py:381-397`（`todo.run(history)`→`AIMessage`→入 `rc.memory`）；`action.py:110-114`（`Action.run` 只 fill/parse） | 对应 `03 §0`「策略只 `ProposeAction`，校验/权限/沙箱/记账全在 Harness」 |
| **协调走消息总线，不直改彼此状态**：`publish_message`→`env.publish_message`→按地址路由→`role.put_message`（私有缓冲）→`_observe` 过滤 | `role.py:429-452`（publish/put）、`role.py:399-427`（`_observe` 从 `msg_buffer.pop_all` 按 `watch/cause_by` 过滤）；`base_env.py:175-195`（`publish_message` 遍历 `member_addrs`+`is_send_to`→`put_message`，`history.add` 仅 debug） | 印证 questor「改状态只走 Command 总线、Event 不反哺」（`C5`）：角色之间也是**投递意图**而非互相写 |
| **读写分离注册表**：外部环境的 read / write API 各一张注册表，按名查函数 | `base_env.py:37-50`（`env_read/write_api_registry` + `mark_as_readable/writeable`）、`73-104`（`read_from_api` / `write_thru_api`） | 「只读视图 vs 写意图」两条通道，可在 05 用两个不同注册面表达 |
| **依赖注入用 Context + Mixin（私有覆盖共享）** | `context.py:58-100`（`Context` 持 `config/cost_manager/_llm`、`llm()` 工厂、`serialize/deserialize:102-127`）；`context_mixin.py:28-33`（`private_context/config/llm`）、`66-96`（`config/context/llm` 属性：私有 > 共享） | questor 的 Port 注入（`ProviderPort/StorePort`）就是这套的规整版；策略拿 context 只拿授权视图，不给裸句柄（`C4`） |
| **策略的输出结构=声明式数据 + 按内容指纹去重注册** | `action.py:38`（`node: ActionNode`）；`action_node.py:135-180`（`ActionNode` 字段 `key/func/params/expected_type/instruction/example/content/instruct_content`）；`action_outcls_registry.py:11-42`（把 schema 排序后拼 `outcls_id` 当键，**同结构=同一个类**，避免 `create_model` 重复生成） | 「策略产出的意图用 schema 声明」+「注册表按内容指纹寻址」——直接对应 AB/缓存键/fingerprint |
| **规划策略把「多步计划」存进外部状态、每步只取当前** | `planner.py:58-101`（`Planner.update_plan`）、`102-117`（`process_task_result`）、`155-167`（`get_useful_memories` 只喂必要上下文） | 印证 questor「计划进任务树、接口是单步」（`01 §3`、决策①）——策略读 plan 视图，返回「做哪个 task」 |

**一句话**：MetaGPT 用 **`react_mode` 枚举 + `propose/solve` 协议多实现 + 消息总线 + Context 注入 + ActionNode 声明式输出**，把「策略」从执行里剥离成「可切换、可注册、按指纹寻址的数据/算法族」。它的**弱点**（引以为戒）：策略字段（`react_mode`、`state`、`todo`）与 Role 私有状态**混在同一个 `RoleContext`**（`role.py:92-122`）——questor 明确要区分 `Domain_State`（权威持久）与 `LoopState`（循环临时）（`04 §11 L2`）。

### 2.2 DeepCode：策略=按值快照的声明式预设（preset）+ 强制结构化提交

| 机制 | 证据（文件:行号） | 对 questor 的启发 |
|---|---|---|
| **preset 只捆绑「该策略拥有的」**：persona、工具 allowlist、可否 spawn；**模型路由/审批/沙箱仍是会话级独立旋钮** | `agent_presets/__init__.py:1-34`（docstring：preset 拥有 persona/tool-allowlist/allow_spawn；model route/approval/sandbox 独立、不变） | 精确定义 L4 的边界：**策略 = 提示词 + 能力选择**，权限/模型/沙箱不归它（对齐 `03`/`C9`）；避免策略膨胀 |
| **解析一次 + 按值快照进会话元数据 + 编辑文件不影响已有会话** | `agent_presets/__init__.py:24-27`（"resolved once at Session creation, snapshotted into canonical metadata"）；`AgentPresetSnapshot` `122-131`；`to_metadata`/`from_metadata` `132-163` | **热替换的正解**：换策略=新 run 生效，**活 run 内冻结**。questor 04 §6「工具面冻结」同构，05 应把这条上升为「策略版本 run 内冻结」 |
| **快照宽容解码：读不懂就退回默认，绝不让会话打不开** | `from_metadata:141-163`（"anything unreadable means no preset"，degrade 而非抛） | 远程/持久化的 view/intent 解码要 fail-safe（对应 `hermes curator` never raises、`load_background_review_settings` fail-open） |
| **按内容指纹做运行时键比较** | `fingerprint()` `165-167`（"hashable identity for runtime-key comparison"） | **AB/缓存/一致性**：用 fingerprint 而非版本号判定「是不是同一策略」 |
| **组合系统提示词用 append / replace 两模式** | `PROMPT_MODE_APPEND/REPLACE` `51-53`；`compose_system_prompt` `169-175`（append 走 `## Persona` 段，base 保留） | 策略注入提示词应是「叠加/替换」而非覆盖——基础纪律（工具规范）不被策略抹掉 |
| **工具清单只会「收窄注册表」、从不禁用必需提交通道** | `tool_filter` `177-186`（"only ever narrows"）；`control.py:582-593`（allowlist 绝不能把 `submit_result` capture 工具锁出去） | 策略能力**只减不增**（安全默认）；且约束「策略不能自废关键控制」 |
| **破损预设留在名册带 reason；未知 id 是调用方的错（带 roster）；broken 是部署方的错** | `list_agent_presets` `220-241`（broken included）；`resolve_agent_preset` `244-262`（`UnknownPresetError` vs `BrokenPresetError`）；`_parse_preset_file` `265-340`（坏文件→带 `broken` 返回，不抛） | **策略注册表的错误二分**：找不到=你写错、坏掉=运维错；两者都不静默消失。questor 05 的 `PolicyRegistry` 照抄 |
| **信任优先级 project > user > system，最近根覆盖重名** | `PresetRoot`/`TRUST_*` `47-49`、`discover_preset_roots` `204-217`、`list_agent_presets` nearest-wins `220-241` | 策略多来源（内置/用户/远程）时的**覆盖与去重规则**；questor 后期热插拔宿主直接需要 |
| **策略产出用「强制 capture 工具：参数即 schema」提交，而非从最终文本里刮** | `structured_result.py:1-13`（docstring）、`validate_output_schema` object-rooted 拒坏 `29-44`、`_CaptureTool.parameters returns schema` `108-110`、`execute` 捕获 kwargs `116-120`、`reset` 在 turn 边界清旧 `59-67` | 意图应是**类型化、schema 可校验**的结构（映射 questor「非法意图被 reduce 拒绝、不靠自觉」`04 §11 L1`、`I1`）；`reset` 防「本轮没提交却复用上一轮结果」 |
| **子 agent 编排：spawn 非阻塞、结果走 Turn 信箱/injection 注入、不改父状态；深度封顶** | `control.py:1-21`（docstring）、`_post` 走 mailbox `675-720`、`send_message` 注入下一 turn `222-253`、`allow_spawn=False` 深度上限 `600`、`_run_subagent` 用 hooks `agent_context=(id,"subagent")` 触发 SubagentStart/Stop `602` | 多 agent（P8）时策略=「一个可被 spawn 的 PolicyPort 实现 + 一份 composition」；结果回流走总线不直改（`C5`）；hooks 即 `C10` 生命周期 |
| **workflow 是「纯数据上下文」，副作用全在别处** | `workflow_context.py:9-19`（"Pure data + derived path; no I/O, no LLM, no business logic"）、`61-68`（早期填充、之后 effectively immutable） | 策略视图应是纯数据、早建后不可变（`C2` COW）；编排（`workflows/` 巨型 pipeline）是**反面教材**——策略一旦硬编码成固定流水线就不可插拔 |

**一句话**：DeepCode 把「策略」做成 **preset（按值快照、run 内冻结、指纹寻址、破损留名、信任优先级）+ structured_result（用 schema 化工具强制提交意图）**。这是三家中最贴近 questor「策略可注册/热替换/AB + 只读→意图」的蓝本。

### 2.3 hermes：策略=后台只读快照重放 + 严格受限 + 生命周期状态机

| 机制 | 证据（文件:行号） | 对 questor 的启发 |
|---|---|---|
| **反思/记忆策略在「fork 的只读快照」上重放，主会话与 prompt 缓存绝不被碰** | `background_review.py:1-6`（docstring：spawn daemon 线程 replay conversation snapshot；writes 直连 memory/skill store；main conversation & prompt cache never touched） | 正是 questor「策略拿只读视图、副作用不污染权威状态」（`01 §0`、`C2`）；反思类策略应在**分支快照**上跑（`C3` 全量快照只用于回放/分支试验） |
| **持久化彻底隔离**：fork `_persist_disabled`/`_session_db=None`/跳过 MCP refresh，只 in-place 压缩 | `build_cache_parity_fork:957-1037`（`994-996` persistence detachment；`988-994` 注释"PERSISTENCE ISOLATION curator-takeover root cause"：共享 session_id 会把它这轮 harness 写进真会话） | 血泪教训：**策略跑在与权威态隔离的沙箱**，否则后台策略「接管」主状态。questor 策略异常回滚（`04 §11 X4`）的动机 |
| **能力受限 = dispatch-side 白名单：只「准入」、不「广播」；写工具仍 deny，改动必经 `skill_manage` 校验** | `_review_tool_whitelist:1080-1120`（`1083-1084` DISPATCH-side only；`1096-1120` "can only admit, never advertise"；`1105-1107` write tools stay denied，走 skill_manage validation）；`_run_review_fork` `set_thread_tool_whitelist` + deny 文案 `1162-1170` | 策略可调用面**只收窄不扩面**（DeepCode `tool_filter` 同律）；questor 策略只发 `ProposeAction`、执行在校验层（`03 §0`）——白名单是它的机器强制形态 |
| **读-校验-写门（read-before-write guard）**：先 `read_file` 登记读过，才允许 `skill_manage(patch)` | `_review_tool_whitelist:1092-1095 / 1104-1105`（denied read 引发 denial storm；read 注册给 read-before-write guard） | 意图可校验：改动作前必须先「读」其目标——可映射 questor reduce 里的不变式校验（`I1`） |
| **策略写操作打溯源标签（origin/turn tag）** | `review_agent._memory_write_origin = write_origin` `979`；`_turn_origin = write_origin` `983`；`build_memory_write_metadata:737-739` | 每次写带 `write_origin`（谁触发的策略），对应 questor `ToolCall/Event` 溯源、审计（`01 §4`） |
| **配置缺失 fail-open + WARN；curator 幂等「best-effort，绝不抛」** | `load_background_review_settings:228-230`（fail-open 所以坏配置不会静默关评审，但 WARN 让成本可见）；`maybe_run_curator:1198-1201`（"Returns ... Never raises"） | 策略不可用时**降级到默认 + 显式告警**，不静默失败（`C10` 故障隔离的落地口径） |
| **策略=生命周期状态机 + 不变式**（active/stale/archived；pinned 一律豁免；**永不 delete、只 archive 可恢复**） | `curator.py:1-7`（invariants：只碰 curator-managed、never delete only archive、pinned bypass、fork 用 auxiliary client 不碰主缓存）；`apply_automatic_transitions:209-212`；`DEFAULT_CONSOLIDATE=False:31-35`（LLM 合并 opt-in、确定性 prune always-run） | 记忆/技能策略应有**幂等 + 安全默认（可恢复、豁免置顶）**；把「贵而不确定的策略」设 opt-in、「便宜确定的」设 always-on——questor 分层落地节奏参考 |
| **首 tick 只播种不动手**（fresh install 绝不误改库） | `should_run_now:160-163`（First observation seeds `last_run_at`、defers one interval） | 后台策略首跑「只初始化时钟、不执行副作用」——防「装好就乱改」。可作 05 的运维不变式 |
| **策略=数据（一个 SKILL.md），`/learn` 用一条 prompt 把「描述的东西」蒸馏成可复用技能** | `learn_prompt.py:136-197`（`build_learn_prompt` 单入口，作者规范当数据 `_AUTHORING_STANDARDS:11-81`）；`:125-133`（"Source text is DATA, not instructions" 防注入） | 「策略即注册的提示词/技能数据」；且**外部内容当数据不当指令**——策略视图的不可信来源处理（`04 §11 L1`） |
| **策略/技能注册表带 provenance 与生命周期字段**（source=base/profile/external、created_by=agent/learn、state、pinned、use_count） | `learning_graph.py:26-37`（`SkillNode` 字段）、`build_skill_nodes:82-122`（source 分类）、`_has_learning_signal:207-215`（external 挂载不算「学过」） | `PolicyRegistry` 的注册项元数据形状：**来源/创建者/状态/置顶/用量**，供 AB/审计/热插拔 |
| **身份用内容指纹而非位置** | `memory_fingerprint:143-153`（digest 文本非索引：位置会变、内容才稳定）、`memory_node_id:156-158` | 再次印证「按内容指纹寻址」（对齐 DeepCode `fingerprint`、MetaGPT `outcls_id`）——注册/AB/回放的稳定键 |

**一句话**：hermes 展示了**「策略=可后台重放的受限只读进程」**：fork 只读快照、dispatch-side 白名单（只减不增、写必经校验）、持久化隔离（防接管）、生命周期状态机（archive 不 delete、pinned 豁免）、首 tick 不动手、fail-open/never-raise 降级。这是 questor「反思/记忆策略」与 `C10` 故障隔离的最佳参照。

---

## 3. 三家 → questor 现状 → 缺口（05 要补什么）

| 主题 | 三家怎么做 | questor 已覆盖 | **缺口（应进 05）** |
|---|---|---|---|
| 策略的**接口形状** | `propose(view)`/`solve()`/`propose_action` | `04:9,18`「每轮向 `PolicyPort` 要一个意图」；`00 §3.1` 提 `PolicyPort` 名字 | **`PolicyPort` 无正式接口定义**（`propose_action` 签名、view 字段、intent 变体未成契约）|
| **注册/发现** | preset 名册 + 信任优先级；solver 多实现注册 | `00 §3`「L4 策略注册表」一句；`STRUCTURE:42` 经注册表挂进内核 | **注册表无结构**（id/factory/trust/broken/Unknown-vs-Broken 错误二分）|
| **热替换语义** | resolve-once + 快照 + run 内冻结 | `04 §6`「工具面冻结」（同类，但只讲工具）| **未定义「策略版本 run 内冻结 / 换=新 run」**（易被误解为可中途 swap）|
| **灰度 / AB** | fingerprint 作 runtime-key；per-agent override 提示词 | `00 §3.2`「换/灰度/AB 不动内核」一句 | **无 AB 路由键与评测关联**（用 fingerprint 绑定 run、把决策落事件流）|
| **进程内默认 / 远程预留** | MetaGPT env-API 序列化、DeepCode snapshot `to/from_metadata` | `C12`「默认进程内 + 只读视图，远程后期、不为它序列化一切」；`01 §11` 天花板 | **view/intent 的「可序列化但 v1 不传输」边界**没写成约束（应纯 frozen dataclass）|
| **生命周期 / 故障隔离** | hooks、白名单、持久化隔离、never-raise 降级 | `C10`（init/load/unload/异常隔离）、`04 §11 X4`（panic→回滚）| **`PolicyPort` 生命周期方法 + 非法意图/panic 的降级矩阵**未成接口级规定 |
| **只读视图（COW）** | 快照重放、纯数据 ctx | `01 §0`/`C2/C3`（字段暴露的只读视图，靠 COW/结构共享）| **`PolicyView` 具体暴露哪些字段**（context/task_tree/tool_results/memory/budget；不含 checkpoint/permission/LoopState）未定 |
| **策略边界不膨胀** | preset 只管 persona/tools/spawn，model/审批/沙箱独立 | `03 §0`（策略只 `ProposeAction`）、`C8` | **明确「策略不拥有模型路由/权限/沙箱」**（防 preset 之外的东西漏进 L4）|

---

## 4. 决策：单开 05 还是并入 04？

**建议：单开 `docs/design/05-policy.md`，定位「L4 策略契约 + 注册/生命周期」，作为 04（L2 机制）的姊妹文档；同时新增 ADR-0009。**

**为什么不是并入 04：**
1. **层不同**：04 标题即「L2 Kernel · Harness 只调度不思考」（`04:1,4`）。PolicyPort 是 **L4 契约**，`00 §2`/`C1/C14` 要求 L2 与 L4 各自独立、内层不 import 外层。把 L4 契约写进 L2 文档，等于文档层面复刻被禁止的耦合。
2. **读者不同**：写循环的人只需 `propose_action(view)->intent` 一个调用点；写策略的人需要注册/热替换/AB/生命周期/远程边界——两组信息量差一个数量级，合在一起会稀释 04 的「机制单一职责」。
3. **变更频率不同**：`00 §3.2` 说 L4 是**唯一高频区**（不断加算法/调提示词），L1-L2 低频。「高频改动的契约」应与「低频稳定的骨架」**分文件**，减少误触承重墙（`C11`）。

**为什么不升格为「第六道接缝」：**
- `ROADMAP §0`、`VISION §8`、`04 §74` 三处把「五接缝(00-04)齐全」定为**可开发门槛**。05 若被当作承重接缝，会误导「不开 05 就不能开工」。
- 事实：**P1 用一个硬编码进程内策略即可跑通**（`ROADMAP §2.5`：P1 验证 PolicyPort 返非法意图「不崩」即可）。注册表/热替换/AB/远程属 P9。
- 所以 05 的定位是**「纵深/契约细化」**：门槛已达成，05 把 04 §9/§11 刻意推迟的策略细节补齐，**不阻塞、不重排**。

**折中方案（若极度怕文档膨胀）**：把「`PolicyPort` 最小接口 + view/intent 形状」补进 **`contracts`(L0) 层**并以 4-6 行内联在 04 §9；把「注册/热替换/AB/生命周期/远程预留」写进 05。**本报告采此折中**：接口下沉 L0、机制放 05。

---

## 5. 具体接口（可落地契约草案，供 05/`contracts/policy.py` 直接采用）

> 全部**纯数据 + Protocol**，落 `src/questor/contracts/policy.py`（L0，只放抽象与数据，`S4/C14`）；具体策略实现落 `src/questor/policy/`（L4）。frozen + 不可变集合（`C2`）。

### 5.1 只读视图 `PolicyView`（策略唯一能读的东西）

```python
@dataclass(frozen=True, slots=True)          # 靠 COW/结构共享产新实例，不靠浅 frozen（C2）
class PolicyView:
    context:      tuple[MessageView, ...]    # 已含压缩后 summary（01 §2）
    task_tree:    TaskTreeView               # 只读森林：node.status/result（01 §3）
    tool_results: tuple[ToolResultView, ...] # 本 run 账本可读项（01 §4）
    memory:       MemoryView                 # 经 StorePort 授权检索，无裸句柄（C4）
    budget:       BudgetView                 # 剩余额度，供策略自限（只读）
    # 明确不暴露：checkpoints / permission_ctx / error_stack 内部 / LoopState 瞬态 / provider 句柄
```
- 视图**按字段暴露**，不是可变引用；结构共享但**禁原地 mutate**（reduce 产新实例，`X3`）。
- 全量快照只在**回放 / 分支试验**生成（`C3`）；反思类策略（记忆/技能维护）应在**分支快照**上重放，绝不写权威态（hermes `background_review.py:1-6`、持久化隔离 `994-996`）。

### 5.2 单步意图 `PolicyIntent`（策略唯一能产出的东西，= 不可信输入）

```python
# 均为 frozen 数据；每个 intent 一对一映射到一条 Command（02 §5）
@dataclass(frozen=True) class ProposeToolCall: name:str; args:Mapping; node_id:str|None=None
@dataclass(frozen=True) class ProposePlanUpdate: ops:tuple[PlanOp,...]        # 计划进任务树（01 §3）
@dataclass(frozen=True) class AdviseCompact: reason:str                        # 仅 advisory，不强制（01 I2）
@dataclass(frozen=True) class SuggestFinish: final_ref:str|None=None
@dataclass(frozen=True) class SuggestCancel: reason:Literal["user","timeout","resource","safety"]
PolicyIntent = ProposeToolCall|ProposePlanUpdate|AdviseCompact|SuggestFinish|SuggestCancel
```
- **终止权在 Harness**：`Suggest*` 只是建议，全局终止由内核判（`C7`）。
- **策略不拥有执行/权限/沙箱**：只发意图，校验/权限/沙箱/超时/记账全在 Harness（`03 §0`、`C8`）；策略**不含**模型路由/审批/denylist 决策字段（DeepCode `agent_presets:1-34` 的边界教训）。

### 5.3 `PolicyPort`（L4 面向 L0 实现的协议）

```python
class PolicyPort(Protocol):
    @property
    def id(self) -> str: ...                  # 注册键：寻址 / AB / 灰度
    @property
    def fingerprint(self) -> str: ...         # 内容指纹（persona+tools+算法版本哈希）；同 DeepCode fingerprint:165 / MetaGPT outcls_id
    async def propose_action(self, view: PolicyView) -> PolicyIntent: ...  # 每轮唯一调用点（04:18）
    # —— 可选钩子（默认 no-op）——
    async def on_tool_result(self, view: PolicyView, tr: ToolResultView) -> None: ...
    def init(self, cfg: PolicyConfig) -> None: ...     # 生命周期（C10）
    def dispose(self) -> None: ...
    # —— 禁止出现的方法 ——
    # execute()/sandbox 句柄/StorePort 写句柄/直接改 state：一律不给策略（C1/C4/C8）
```

### 5.4 `PolicyRegistry`（注册 / 发现；P9 完整，P1 用进程内最小集）

```python
@dataclass(frozen=True)
class PolicyDescriptor:
    id: str; factory: Callable[[], PolicyPort]
    trust: Literal["system","user","project"]   # 信任优先级（DeepCode:47-49/204-217）
    tools: tuple[str,...] | None                 # 能力收窄面（只减不增，DeepCode tool_filter:177）
    broken: str | None = None                    # 坏掉留在名册带 reason（DeepCode:220-241）

class PolicyRegistry(Protocol):
    def register(self, d: PolicyDescriptor) -> None: ...
    def resolve(self, id: str) -> PolicyPort: ...        # UnknownPolicyError（调用方的错，带 roster）
    def list(self, *, only_healthy: bool=False) -> tuple[PolicyDescriptor,...]: ...  # broken 默认可见
    def bind_for_run(self, run_id: str, policy_id: str) -> PolicySnapshot: ...       # 创建时快照，run 内冻结
```
- **错误二分**：`UnknownPolicyError`（你写错 id，附 roster）vs `BrokenPolicyError`（部署/加载错，附 reason）——照抄 DeepCode `resolve_agent_preset:244-262`。
- **降级**：目标策略不可用 → 回落**默认进程内策略** + WARN，**绝不静默禁用、绝不让 run 起不来**（hermes `load_background_review_settings:228-230` fail-open、`maybe_run_curator:1198-1201` never raises、DeepCode `from_metadata:141-163` degrade-to-default）。

### 5.5 与 04 turn 循环的接缝

- 循环每轮**只调一次** `propose_action(view)`（`04:18`），拿到 `PolicyIntent` → 映射 Command → `permission_gate → validate → reduce`（`04:21-23`）。
- 循环**不感知**策略是哪个实现、从哪注册：它只认注入的 `PolicyPort`（`STRUCTURE:42`、`S3`：kernel 禁直接 import policy 具体实现，由 import-linter 守）。

---

## 6. 三条关键语义（05 的核心决策，建议写进 ADR-0009）

### 6.1 热替换 / 灰度 = run 内快照冻结，换 = 新 run
- **创建 run 时解析一次、按值快照**（`policy_id + fingerprint + 参数`），整 run 用同一份；编辑注册项/换算法**只影响新 run**。
- 依据：DeepCode "resolve once, snapshot"（`agent_presets:24-27`）+ questor 已有的「工具面冻结」（`04 §6`）。**严禁活 run 中途 swap 策略**——会撕裂状态/回放/审计（`C2/C11`）。
- 「热替换」在 v1 = **热替换默认绑定**（新 run 立即用新策略），非「热替换正在跑的 run」。

### 6.2 A/B = 按 fingerprint 路由，评测落事件流
- AB 分桶键 = `fingerprint`（内容指纹）而非版本号：同结构=同策略（MetaGPT `outcls_id`、hermes `memory_fingerprint:143-153`）。
- 一个 run **稳定绑定一个** policy_id/fingerprint；`run_started` 事件带上 `policy_ref{ id, fingerprint }`（`02` 只增字段，兼容）。
- 灰度/评测：按 session/user 尾桶选 policy_id；任务级回归网（`ROADMAP` P10）用 `policy_ref` 关联同任务下不同策略的结果对比。**全程不动内核**（`00 §3.2` 的兑现点）。

### 6.3 进程内默认，远程只「预留」不「预做」
- v1：策略 = 直接注册进内核的**进程内 Python 对象**实现 `PolicyPort`（`00 §3.1`、`C12`）。
- 远程化前置条件**只做一件便宜事**：`PolicyView`/`PolicyIntent` 保持**纯 frozen 数据**（天然可序列化），但 **v1 不引入任何 RPC/序列化传输**。
- 真到远程时再加一个 `RemotePolicyAdapter`（把 view 序列化下发、把 intent 收回），并补鉴权/新鲜度一致性——那是独立硬骨头（`01 §11` 天花板、`C12`）。**不为远程提前序列化一切**。

---

## 7. 红线对齐自检（05 不得违反）

| 红线 | 05 如何守 |
|---|---|
| `C1/C14` 分层依赖 | `PolicyPort` 契约在 L0 `contracts/`；实现 L4 `policy/`；kernel 只经端口注入，不 import 具体策略 |
| `C2/C3` 只读视图 | `PolicyView` frozen + 不可变集合；全量快照仅回放/分支试验 |
| `C4` Store 走接口 | `MemoryView` 经 StorePort 授权返回，策略无裸句柄 |
| `C5/C7` Command 单写者/终止权 | intent→Command 才改状态；`Suggest*` 仅建议，全局终止在内核 |
| `C8/C9` 工具/权限边界 | 策略无 execute/沙箱/审批字段；能力只收窄（`tools` allowlist） |
| `C10` 生命周期/故障隔离 | `init/dispose` + `propose_action` panic→回滚 turn 前态 + 降级默认 + WARN |
| `C11` 接缝早锁字段后锁 | 本文件把「接口形状/注册/快照语义」当接缝早锁；`PolicyView` 精确字段、`PlanOp` 细节按 01 后锁 |
| `C12` 远程预留 | view/intent 纯数据可序列化即止，不提前传输 |

**非法意图 / panic 的降级矩阵（补 `04 §11 L1/X4` 到接口级）：**
1. 非法 intent（未知工具名/坏参数/违不变式）→ reduce 拒绝、包成被拒 Command + error 事件、`verdict=continue`、错误回填上下文让下轮自纠，**不崩循环**。
2. `propose_action` 抛异常/panic → Harness 捕获、回滚 `Domain_State` 到 turn 前一致态、发 error 事件；**已发的 `*_delta`/外部事件不撤回**（`C10` 回滚边界）。
3. 策略整体不可用（加载失败）→ 回落默认策略 + WARN；默认也没有 → `run_failed`（`retryable=true`）。

---

## 8. 建议的 `design/05-policy.md` 骨架（定稿时用）

```
0. 定位：L4 策略契约（04 的姊妹，非第六接缝）；策略=只读视图→意图
1. 边界：策略拥有什么（提示词/能力选择/算法）· 不拥有什么（模型路由/权限/沙箱/持久化）
2. PolicyView / PolicyIntent / PolicyPort（本文件 §5 直接搬入）
3. PolicyRegistry：注册/发现/信任优先级/错误二分/降级
4. 热替换·灰度·AB 语义（§6.1/6.2）
5. 生命周期与故障隔离（init/dispose/panic/降级矩阵）
6. 进程内默认 + 远程预留（§6.3）
7. 反思/记忆类策略的「分支快照重放」模式（hermes 借鉴，P4/P10 用）
8. 待定（v0 后锁）：PolicyView 精确字段、PlanOp 形态、AB 分桶算法
```

**落地节奏（不阻塞 P1）：**
- **P0/P1**：`contracts/policy.py` 落 `PolicyView/PolicyIntent/PolicyPort` 最小形状 + 一个硬编码 `InProcessReActPolicy`；验证「非法意图不崩」。
- **P9**：`PolicyRegistry` + 信任优先级 + 热替换/AB（插件宿主，cordis 式 Fiber 生命周期）。
- **P4/P10**：反思/记忆策略（后台分支快照重放，hermes 借鉴）。
- **远程**：仅当出现真实跨机需求，单独 ADR + 传输适配器。

---

## 9. 待你拍板（3 点）

1. **05 归属**：采纳本报告建议——单开 `design/05-policy.md`（04 姊妹、非承重第六接缝、接口下沉 L0）？还是你更愿保守到「只在 04 §9 扩写 + contracts 落接口」不出独立文档？
2. **ADR-0009**：是否为「run 内快照冻结 / 热替换=新 run / AB=按 fingerprint」这三条硬决策新开一条 ADR？（它们难以回退，符合 ADR 门槛。）
3. **P1 范围确认**：P1 是否就锁定「进程内单策略 + 非法意图不崩」，注册表/AB/远程明确划到 P9？（`ROADMAP` 现无「策略可插拔」独立 Phase，P9 只写「插件宿主/热插拔」，建议把策略注册表归入 P9 或在 plan 里显式点名。）

> 未改任何现有承重文档（00-04/HARD-CONSTRAINTS/ROADMAP/VISION）；本报告为纯新增输入。确认后再落 `05-policy.md` 与 ADR-0009。
