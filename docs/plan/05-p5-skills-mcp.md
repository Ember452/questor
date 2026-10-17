# Phase 5 详细计划 — Skills / MCP 接入

> 起手**必读**：[`AGENTS.md §4.5/§5/§5.5/§6`](../../AGENTS.md) · [`docs/ROADMAP.md §1/§1.5/§2.5`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)（**C1–C20 全量**）· [`docs/pitfalls.md`](../pitfalls.md)（第 1/3/4 条直接命中 P5）· [`docs/log/DESIGN.md §16.4`](../log/DESIGN.md) · [`docs/adr/0027`](../adr/0027-observability-logging-foundation.md)（**复审修正节**）· [`docs/adr/0028`](../adr/0028-pairing-gate-and-provider-fault-normalization.md)（C19 两条 seam 出处）
> **§0 未填完 = 本 Phase 计划未就绪、不能开工**（ROADMAP §0 硬门槛 / AGENTS §4.5 peer-scan gate）。
>
> **性质：READ-ONLY 规划。** 本文只落这一份文档，**不改任何代码、不建分支、不 commit、不 push**。实现需用户**逐轮明确许可**（AGENTS §6：`git commit`/`git push` 每次都要 ask-and-yes）。

---

## 0. 基线确认 + Peer-Repo 扫描（硬门槛）

### 0.0 基线（2026-10-17 实测，非凭记忆）

开工前用 `git` 与文件系统核实，结果如实记录：

| 项 | 实测值 | 证据 |
|---|---|---|
| 当前分支 | **`main`** | `git rev-parse --abbrev-ref HEAD` |
| HEAD 短 hash | **`68a225b`** | `git rev-parse --short HEAD` |
| **PR #140 是否已合入 main** | **是** | `68a225b (HEAD -> main, origin/main, origin/HEAD) Merge pull request #140 from Ember452/fix/log-blade2-audit` |
| C20 / pitfalls.md 引入 | **已在基线内** | `d364862 docs: turn the bug archive into docs/pitfalls.md and add red line C20`（#140 merge 前的分支尾提交） |
| 红线区间 | **C1–C20**（含新增 C20；C6 有"折叠/合并同罪"例外款延伸） | `docs/design/HARD-CONSTRAINTS.md:110-116`（C20 存在）、`:42`（C6 例外延伸） |
| `docs/pitfalls.md` | **存在**（可观测性分区 4 条） | `docs/pitfalls.md:1-81` |
| 工作树 | clean | `git status -s` 空输出 |

> **结论**：本计划基线 = **`main` @ `68a225b`**。因 PR #140 已合入，C20 与 `docs/pitfalls.md` 均为**当前有效基线的一部分**，P5 必须在其约束下规划（而非照"可能不存在 C20"的旧基线）。日志骨架刀 2（ADR-0027）的进入条件已在 #140 落地；但**其完成度以 ADR-0027「复审修正」节 + `docs/pitfalls.md` 为准，绝不引用 `docs/log/PLAN.md §7` 的自报**（详见 §1 进入条件）。

### 0.1 现场重列 `project-main/`（新增自动纳入，排除本仓自身）

以 `Get-ChildItem -Directory` 当下为准（2026-10-17）。**参考源 = 12 仓**；**排除** `questor`、`questor-log-foundation`（本仓自身与刀 2 worktree，非参考源）与 `.ruff_cache`：

`hermes-agent-main · wuu-main · DeepCode-main · CowAgent-master · MetaGPT-main · cordis-main · EvoFlow-main · autogen-main · crewAI-main · OpenManus-main · GenericAgent-main · Agent-S-main`

**LICENSE 核对（本轮实读各仓 LICENSE 首行）**：

| 仓 | 许可 | 搬码边界 |
|---|---|---|
| DeepCode / hermes / CowAgent / MetaGPT / cordis / wuu / GenericAgent / crewAI | **MIT**（版权行后接 MIT 授权段） | 复用=改造思路 + 文件内标 provenance + CHANGELOG 注（AGENTS §5.6） |
| autogen | 文档 `LICENSE` = **CC-BY-4.0**（Attribution）；代码 `LICENSE-CODE` = **MIT** | 仅搬**代码**（MIT），搬文档/图需署名 |
| Agent-S | **Apache-2.0** | 兼容，保留 NOTICE/专利条款意识 |
| **EvoFlow** | **PolyForm Noncommercial 1.0.0** | **`evopanel` 禁止搬码**——只参考交互/命令形状（本计划不触碰其代码） |

> **所有 `file:line` 均为「扫描快照（2026-10-17），开工当天必重验」**（§0 行号 stale 是本项目 P3 审计 F 类已知教训）。

### 0.2 逐能力扫描表（**每能力 ≥2 仓**）

| 能力 | 扫描仓（`repo:path:line`，扫描快照） | 结论 | 说明 · 许可/署名注意 |
|---|---|---|---|
| **MCP server 生命周期 / 连接 / 握手 / 超时 / 失败恢复** | DeepCode `core/mcp/connection.py:33-80`（一 transport 一 task 独占、`_serve` 同 task 进出、tool call 用子 task 使超时/取消可撤单请求而不坏 teardown、`start(timeout_seconds=…)`、`MAX_DISCOVERED_TOOLS=256`）；CowAgent `agent/tools/mcp/mcp_client.py:167-168`（`initialize()`=connect+handshake 返 bool）、`:326 / :510 / :612`（`_handshake()`/recovery 握手走正常 HTTP 路径）、测试 `tests/test_mcp_failed_handshake_cleanup.py`、`tests/test_mcp_session_recovery.py`；OpenManus `app/tool/mcp.py:54-60`（多 server：`sessions`/`exit_stacks` 字典管理）；hermes `tools/mcp_tool_lifecycle.py:240`（`_close_mcp_stderr_logs(scope=…)` 停止后释放句柄） | 改造 | 采 DeepCode"transport 独占 task + 子 task 撤单"形状（超时/取消不撕裂 transport）与 CowAgent"handshake 失败即清残留、不半初始化"。**本项目落点**：MCP client 的连接生命周期属 `capabilities/mcp`（L3）→ 经 `providers/process_runner.py`（L5，ADR-0018 Harness-owned process runner）起子进程，**不得在 kernel 直接管 transport**。MIT，改造处文件内标 provenance |
| **远程工具描述 → `ToolSpec` 归一与净化**（含"只识别不暴露原始 args"的形状） | DeepCode `core/mcp/tools.py:42-56`（`sanitize_description(description, name, max_chars=8000)` + `normalize_schema_for_openai(inputSchema)` + `approval_mode=policy_for(raw_name)`、`:71-74` read_only "annotations are hints, not grants，unknown→mutating 向确认失败"、`:80-84` `presentation_detail` 返 `""`——"远程工具可能在无害参数名下藏凭据/签名 URL，raw args 只留在受保护观测面"）；DeepCode `core/mcp/schema.py:8-39`（递归 nullable/oneOf/anyOf 归一、object 补 properties/required）；DeepCode `core/agent_runtime/tools/base.py:50-72`（`sanitize_description` 句界截断 + 退化回退"tool (no description provided)"，绝不空）；DeepCode `core/mcp/naming.py:12-35`（`visible_tool_name` 定长 64、冲突加 sha256 后缀）；OpenManus `app/tool/mcp.py:14-46`（对照：仅透传 name/output，无净化/无界——**质量不足**，不作来源） | 改造 | 直接对齐本仓既有件：`capabilities/tools/registry.py:21-37`（`_sanitize_description`：去控制字符/折叠空白/截上限 `description_max_chars`）已具雏形，P5 把"远程描述"也纳入同一 sanitize；`contracts/tool.py:52` `read_only` 缺省 false=非只读 fail-closed，与 DeepCode "hints not grants" 同向；`contracts/tool.py:55` `approval_mode`「MCP 只收紧不放宽、unknown→deny」沿用。命名沿用本仓钉死的 `mcp_<server>_<tool>`（**非** DeepCode `mcp__server__tool`，见 §0.5）。MIT |
| **Skills / `SKILL.md` 加载与解析**（发现/校验/坏文件降级/渐进披露） | crewAI `lib/crewai/src/crewai/skills/parser.py:30-127`（`SKILL_FILENAME="SKILL.md"`、`parse_frontmatter` 用 `yaml.safe_load` 且缺 `---`/非法 YAML/非 mapping 全抛 `SkillParseError`、`_MAX_BODY_CHARS=50_000` 超阈告警"注入 prompt 吃上下文"、METADATA→INSTRUCTIONS→RESOURCES 渐进披露）；crewAI `skills/validation.py:13-56`（name 正则 `^[a-z0-9]+(?:-[a-z0-9]+)*$`、≤64、`validate_directory_name` 目录名须等于声明名）；crewAI `skills/loader.py:44-117`（`discover_skills`：逐子目录试 `load_skill_metadata`，**单文件 except→log warning + 发 `SkillLoadFailedEvent` + continue**——坏文件不拖垮发现）；hermes `tools/skills_tool_setup.py:46`（`_get_required_environment_variables(frontmatter)` 声明 skill 所需 env）、hermes `tools/write_approval.py:272-273`（`_frontmatter_description` 取 `description:` ≤140 字符） | 改造 | 采 crewAI"safe_load + 逐文件降级 + 有告警事件"与"目录名==skill 名"校验；采 hermes "≤140 desc" 有界思想并入 `description_max_chars`。**本项目落点**：skills 发现产出的"工具/指令"经同一 `ToolRegistry` freeze（`capabilities/skills/README.md` 已钉：目录空是 S2 有意为之，`ToolSpec`/registry 形状已容 skill 工具）。坏 `SKILL.md` = 归一结构化错误（§2 T8），**绝不静默、绝不拖垮整批发现**（C6 + pitfalls 第 2 条精神）。MIT |
| **MCP/Skills 凭据与 env 处理、远程描述投毒防护**（提示注入/超长/伪装内置名） | hermes `hermes_cli/mcp_security.py:1-40`（`validate_mcp_server_entry` 拦 3 类窄形状 + IOC 名单；**save 时与 spawn 时双门**——手改/预植 `config.yaml` 条目执行前也拦；shell 解释器/egress（curl/wget/nc/`/dev/tcp/`）/exfil（`.env`/`--data-binary`/POST）/持久化（authorized_keys/`.ssh/`/sudoers/cron）模式）；DeepCode `core/mcp/connection.py:25-30`（`CredentialResolver` 注入式解凭据 + `${VAR}` 占位正则，凭据不落明文配置）；hermes `tools/computer_use/cua_backend_session.py:235`（`_sanitize_subprocess_env(child_env)` 起子进程前擦 env） | 改造 | **本仓已有更权威的复用件**：`providers/env_safety.py:31-75`（`is_provider_credential`/`scrub_environment`/`build_child_env`——provider 凭据即使 declare 也抛 `PermissionError`），env 处理一律走它，不新造擦除逻辑。投毒防护采 hermes"双门（载入 + spawn 前）"纪律：远程描述**过 registry sanitize**（§2 T5）+ **命名冲突拒绝**（§2 T6）+ **有界**（`description_max_chars=2000`）。MIT |
| **子进程 stderr 捕获与重定向**（DESIGN §16.4 决策一的形状来源） | hermes `tools/mcp_tool_config.py:22-63`（`_get_mcp_stderr_log`：**append 模式、`encoding=utf-8`、`errors="replace"`、`buffering=1` 行缓冲**，缓存句柄至 shutdown per-profile-home，失败退 `os.devnull` 再退 `sys.stderr`；`_StderrTee` 尾 16 KB 可读、逐行盖戳）；hermes `tools/mcp_tool_transport.py:399-401`（"Subprocess stderr goes to `~/.hermes/logs/mcp-stderr.log` so banners can't corrupt the TUI"，`stderr=_StderrTee(...)`）；hermes `tools/mcp_tool_discovery.py:233-240`（状态消息单行、全文只在 mcp-stderr.log）；GenericAgent `frontends/genericagent_acp_bridge.py:10-31`（对照形状：把文本模式 stdout fd 重定向到 stderr，让 ACP JSON-RPC 独占 stdout、agent 打印不外泄） | 改造 | 采 hermes"append + 行缓冲 + errors=replace + 不可写退 devnull/stderr + 关闭时释放"整套句柄治理。**关键差异见 §0.3**：hermes 是**单一共享 `mcp-stderr.log`、不带 per-run 关联**，本 P5 必须**自写 `run_id` 注入**才能满足 DoD⑤。MIT |

### 0.3 必须显式落成的两条 DESIGN §16.4 前置决策（P5 前置，不假装 contextvar 能解决）

> 出处：`docs/log/DESIGN.md:327`（§16 攻击点 4）、ADR-0027 复审修正 ④（`docs/adr/0027…:65-67`）、`docs/pitfalls.md:55-66`（第 3 条：`contextvars` 不过线程/进程边界——真 run 80/85 行来自 aiosqlite 工作者线程、`context` 恒空；明写"子进程侧 `run_id` 注入方式（文件名/首行前缀）**必须在 `plan/05` 的 §0 扫描表里先定案**"）。

**决策 D-16.4-A — MCP server 的 stderr 重定向到独立文件**（形状：hermes `mcp-stderr.log`）。
- 子进程 stderr **绝不进主干 `questor-<date>.jsonl`**，也绝不混进 stdout（stdout 洁净红线 G-L10 / pitfalls 第 4 条）。它落**独立目录**的专用文件，句柄治理照 hermes（append / 行缓冲 / `errors="replace"` / 不可写退 devnull）。
- 理由：MCP server banner/traceback 是"装进账本不合适的那类信息"（ADR-0027 背景），且第三方进程输出内容不受我们控——若并入主干文件即把 C20"观测面不得成为载荷第二载体"的口子开到远程侧。独立文件 = 独立通道 = 可单独 GC、可单独授权。

**决策 D-16.4-B — 由 spawn 侧把 `run_id` 注入「文件名」（主）+「首行标记」（辅），实现跨进程关联**。
- **定案：文件名注入为主**。文件命名从 hermes 的 `mcp-stderr.log`（单一共享）改为 **`mcp-stderr-<run_id>.log`**（或按 run 分目录 `<log_dir>/mcp/<run_id>/stderr.log`）。**辅**：spawn 时向子进程 stderr 通道的 tee 先写一行 `# questor run_id=<id> server=<name> ts=<iso>` 标记，供人读定位。
- **为什么文件名而非 ambient `bind()`**：`contextvars` **不出进程**（pitfalls 第 3 条实测），子进程里的 MCP server 打任何日志都拿不到我们的 `run_id`。因此关联**只能在 spawn 边界显式注入**——文件名是跨进程唯一"天然带外、不经第三方日志栈"的载体，首行标记次之。**绝不为 contextvar 自建跨进程传播层**（pitfalls 第 3 条纪律③：语言事实，认它）。
- **判据（DoD⑤ / §4）**：给定 `run_id`，能从**主日志文件**（带内 inline 行携 `run_id`）与 **MCP stderr 独立文件**（文件名/首行含同 `run_id`）**两处分别定位该 run 的全部相关记录**。不接受"代码里写了注入"这种完成感——必须真起子进程、真 grep canary。
- **许可/自写说明**：hermes 未做 per-run 关联（单一共享文件），故"注入 `run_id`"是**自写**——原因：参考实现形状（共享 stderr 文件）与本项目"按 `run_id` 可定位"的关联判据不兼容，拿过来不能直接用，只能采其 stderr 句柄治理部分（D-16.4-A）。

### 0.4 已知观测缺口（P5 必须评估取舍，收口点写死）

- **缺口**：带外投影（`Envelope`→`LogEntry` 的只读旁路，`observability/projection.py`）目前**只挂在 CLI 消费者**（`cli._stream` 消费点调 `log_envelope`），**HTTP sidecar（`surfaces/http_sse.py`）路径未覆盖**。证据：`docs/log/PLAN.md §7 偏差 #4`（复审确认未推翻此条）——"沿用 T2.11 已提交的 `log_envelope`（在 `cli._stream` 消费点调用），未改为 bus 级订阅……HTTP sidecar 路径的带外投影暂未覆盖"。
- **对 P5 子进程/MCP 排障的实际影响**：inline 关联（loop `bind`）经 kernel 仍生效，故**桌面/sidecar 场景下带内行仍带 `run_id`**；缺的是**事件类带外行**（`tool_started`/`run_failed` 等）在 sidecar 路径不落日志文件。对 MCP 排障：① MCP server 自身崩溃/连不上→经 §2 T4 归一为 `WARNING`/`run_failed` 事件，CLI 下会投影到日志、sidecar 下**只在事件流、不进日志文件**；② 但 **MCP stderr 独立文件（D-16.4-A/B）不受此缺口影响**——它由 spawn 侧直接落盘、文件名带 `run_id`，是 sidecar 场景下最可靠的 MCP 排障面。
- **取舍**：**P5 不强行收口该缺口**（改 bus 级只读订阅会动投影消费者单一真源、有双重投影风险，且与 P5 DoD 无直接关系）。收口点记为：**bus 级只读订阅**（一处订阅、覆盖所有 surface），列 §2 尾注 + §6 活文档回填，挂到刀 3 / P7 桌面调试真需求触发。**P5 期间**：DoD⑤ 的跨进程关联判据用 **CLI 消费者路径**跑通（inline 行带 `run_id` + MCP 独立文件带 `run_id`），并**显式标注 sidecar 带外投影 = UNVERIFIED**。

### 0.5 stub 已钉约定的沿用（不得重造）

- **MCP**（`capabilities/mcp/README.md:1-6`）：远程工具**映射到同一 `ToolSpec`、走同一 permission/sandbox gate**（design/03 §6）；**命名规则 `mcp_<server>_<tool>`，权限规则按 suffix 匹配**。P5 沿用此命名/匹配，**不改双下划线**（与 DeepCode `mcp__…` 有意不同，以本仓 stub 为准）。
- **Skills**（`capabilities/skills/README.md:1-5`）：目录为空是 **S2 有意为之**；`ToolSpec`/registry 形状已容 skill 提供的工具——P5 填实体，不新造 registry。
- **subagent**（`capabilities/subagent/README.md`）：留 **P8**，P5 不触碰（`TaskKind.SUBAGENT` 占位保持在 `contracts/state_schema.py:134-138`）。

---

## 1. 目标与可验证判据（DoD）

**目标（ROADMAP §1 P5 行）**：技能加载（丢一个 `SKILL.md` 即生效）+ MCP 接入（挂一个 MCP server 出工具）。

### 1.1 进入条件（对齐 ROADMAP §1.5 P5 备注，按 ADR-0027 复审 + pitfalls 核对，不引 PLAN §7 自报）

- **依赖 P3**（MCP 调用需账本/持久化，`docs/ROADMAP.md:24`）：已满足（P3 ✅ ADR-0020-0022 已实现）。早期可**只做适配器 stub**（R小文本）。
- **日志骨架刀 2 已合入（ADR-0027），B①–B⑧ 为其进入条件**：
  - **判据以 [`ADR-0027「复审修正」节`](../adr/0027-observability-logging-foundation.md)（`:35-68`）+ [`docs/pitfalls.md`](../pitfalls.md) 为准**，**不得引用 `docs/log/PLAN.md §7` 的自报完成度**。原因（实测推翻，见 PLAN §7 复审轮 `:136-154`）：A① 曾靠第三方噪声凑数、B① 在生产 happy path 是空集（inline `questor.*` 行 0 条、80/85 来自 aiosqlite 工作者线程 `context={}`）、B② 只测 dataclass 未测端到端、B⑤/B⑥ aiosqlite SQL 参数把 prompt/checkpoint 原文写进主干（D4 被旁路）、B⑦ 的 **G-L11 守卫当时根本不存在**（加 `"arguments"` 后 527 用例全绿）。
  - **#140 合入后**修正口径已落：新增 **C20**、C6 折叠/合并同罪延伸、`scripts/check_projection_whitelist.py`（G-L11 现为**存在**的守卫带 `--self-test`）、来源门（非 `questor.*` 下界恒 INFO）、ERROR/CRITICAL 绕节流、stdout 洁净（litellm 自挂 handler 由 `providers/litellm_adapter.py` 治理）。新判据 `git stash` 突变验证：未修复源码 21 条全红、修复后 557 passed / 5 skipped（PLAN §7 `:153-154`）。
  - **因此**：P5 的进入条件成立——观测面已有 C20/G-L11 兜底，MCP 这个"第一个从进程外引入错误来源的 Phase"（ADR-0027 背景 `:4`）落在保护窗内。
- **P5 §0 扫描表必须含 D-16.4-A/B 两条决策**（ROADMAP §1.5 `:36`）：已在 §0.3 落成。

### 1.2 DoD（写成可复现行为，不是"完成感"）

> 每条都能在终端/测试里复现；靠 mock 得出的结论一律标 **UNVERIFIED**。

- **① SKILL.md 即被发现并生效**：往 skills 搜索目录丢一个合法 `SKILL.md`（YAML frontmatter：`name`/`description`），一次 freeze/run 后该 skill 被 `discover_skills` 命中并进工具面/指令；坏 `SKILL.md`（缺 `---`/非法 YAML/目录名≠声明名/超 `_MAX_BODY_CHARS`）→ 单文件降级 + 发结构化告警，**发现流程不中断**。
- **② 挂一个 MCP server 能列出并调用其工具，工具结果先进 `event_log` 账本再投影**：`mcp.json` 配一个 stdio MCP server → 其工具以 `mcp_<server>_<tool>` 出现在 `ToolRegistry.definitions()`；调用结果经**同一 Harness 路由**产 `tool_started`→`tool_completed`（`kernel/events.py:49-51`），`RecordToolResult` 先落 `event_log`（C13 唯一真相）→ 再投影外发；**绝不先写日志/直抄事件**。
- **③ 三类失败归一结构化错误、绝不静默绝不崩宿主**：MCP 连不上/握手超时、`SKILL.md` 解析失败、远程工具描述异常（超长/含注入字符/含凭据形状/与内置同名伪装）→ 归一 `ErrorEntry` 语义（`layer`/`kind`/`retryable` 各正确），走 `WARNING`（非终态）或经配对关卡后的 `run_failed`（终态）；`turn` 循环与宿主进程**不崩**（C6 + C10 + C19）。
- **④ 协议 schema 零 diff**：不新增/破坏事件 type 与关联键——**只用现有 21 个 `EventType`**（`contracts/events.py:251-273`）；`check_protocol_schema --check` 零 diff；`R2`（契约占位补实，见 §2 T12）。
- **⑤ 关联可验证（"注入 run_id"的真判据）**：给定 `run_id`，**分别**从（a）主干 `questor-<date>.jsonl` 的 inline 行（`context.run_id`）与（b）MCP stderr 独立文件（文件名/首行含同 `run_id`，D-16.4-B）**定位该 run 的全部相关记录**。**必须在 CLI 消费者路径实测**；sidecar 带外投影缺口按 §0.4 标 UNVERIFIED。

---


## 2. 子任务清单

> 每条：**目标 · 涉及层 · 依赖 · 验证方式 · commit 粒度**。commit/push 均需用户逐轮明确许可（AGENTS §6）。落点守分层（C1/C14）：MCP/Skills 属 L3 `capabilities/`，进程/artifact/env 经 L5 `providers/` 端口，**kernel 不 import L3 具体实现**（S3/注册表挂进，C1/C14）。

### 2.0 `parallel_safe` / `barrier` 归属裁决（显式决策，不留隐债）

**裁决：本 P5 不纳入「完整并行工具执行」，显式推迟到后续专门的并行化 Phase（目标读者：reader/writer gate 属 P8 编排 / 或独立的 parallelization Phase）。**

- **冲突点（原文引用）**：`docs/ROADMAP.md:35` §1.5「P2 v1 主干串行工具；`parallel_safe` 仅 schema 占位，**完整并行后置 P5**」、`:48` §2.5「完整并行→P5」；而 `contracts/tool.py:54,57` 注释写「`parallel_safe` NOT enforced until P5 / `barrier` NOT enforced until P5」；`HARD C19`（`:108`）「reader/writer gate 与真并发属 P5」、ADR-0028（`:72`）「完整并行 gate 仍归 P5」。
- **理由（为什么从"后置 P5"改为"移出 P5"）**：
  1. **P5 的 DoD 不需要并行**（§1.2 五条无一是并行执行）；引入并行 = 加投机面，违 AGENTS §2 Simplicity First。
  2. **并行与 P5 最脆弱的自伤面（C19 配对关卡 + 串行派发）正交但强耦合**：`kernel/loop.py:599-637` 的 `_execute_tool` 与 `:406-435` 的 `_ensure_paired_history` 建立在"严格串行、发出前成对"之上；在**同一 Phase** 既改派发并发又新引入程外错误源（MCP），会把两条高危改动叠在一个 blast radius（§5 风险"并行占位被误当已生效"）。
  3. **远程工具的并发安全是 per-server hint**（DeepCode `core/mcp/tools.py:77-78` `concurrency_safe = supports_parallel_tool_calls`），做正确的并行 gate 要先落"按工具能力档 + 远程 hint 的 capability floor"，这本身是独立子系统（§2.5 明列 MCP/子agent/并行全部后置）。
- **落成的动作（消解隐债，不许只写注释）**：见 §2 T13（改注释/占位口径）+ §6（记一条 ADR 作跨阶段移动的"先记 ADR 再改 ROADMAP"，ROADMAP §5）+ 更新 `contracts/tool.py:54,57`、`HARD C19`、`ROADMAP §1.5/§2.5` 措辞为"deferred beyond P5（target: dedicated parallelization phase / P8 gate）"。
- **"P5 不做"清单**（对齐 §1「P5 不做」）：① 完整并行工具执行（reader/writer gate、真并发派发）；② 子 agent/DAG（P8）；③ 多模态/语音（P6）；④ 凭据池/退避重试编排（P10，ADR-0028 `:73`）。

### 2.1 任务表（T1–T15）

- [ ] **T1 · MCP 配置载入与 server 发现**：目标=读 `mcp.json` 产出 server 定义（command/args/env 占位）→ 交 `McpConnection` 起 stdio。涉及层=L3 `capabilities/mcp/`（新）+ L6 组合根读取。依赖=P3 store（账本）。验证=给定 `mcp.json`，`ToolRegistry` 后能列出该 server 的工具；**配置落点与写保护对齐**：`mcp.json` 在 workspace root 且已列 `contracts/tool_args.py:57-65` `PROTECTED_IN_ROOTS`（agent 不得自改自身 MCP 面，`tests/unit/test_permission_policy.py:212-220` 已钉"protected-root 那一步真在跑、不可被 mode 放宽"）。commit=`feat(capabilities/mcp): load server definitions from protected mcp.json`。**安全门**：采 hermes `mcp_security.py:1-40` 的**载入 + spawn 前双门**（§0.2 第 4 行）。
- [ ] **T2 · MCP 客户端连接/握手/超时/重连**：目标=transport 生命周期 + 握手（`initialize`/`tools/list`）+ 超时 + 失败恢复。涉及层=L3 client → L5 `providers/process_runner.py`（起子进程，ADR-0018）。依赖=T1。验证=连不上的 server 不崩、出声；重连后状态自洽（见 T4 恢复语义）。改造自 DeepCode `core/mcp/connection.py:33-80`（transport 独占 task + 子 task 撤单）与 CowAgent `mcp_client.py:167-168,326`（handshake 失败清残留）。commit=`feat(capabilities/mcp): connection lifecycle with handshake timeout and safe teardown`。
- [ ] **T3 · 远程工具 → `ToolSpec` 归一与净化**：目标=remote tool→`ToolSpec`，命名 `mcp_<server>_<tool>`、suffix 权限匹配、`approval_mode` 只收紧不放宽 unknown→deny、`description_max_chars=2000` 有界、schema 归一。涉及层=L3。依赖=T1/T2。验证=注册后 spec 净化（去控制字符/截断/退化非空）；`params` 过 `contracts/tool.py:48` json-schema 校验。改造自 DeepCode `core/mcp/tools.py:42-56`+`schema.py:8-39`+`base.py:50-72`；**沿用本仓 `registry.py:21-37` 的 `_sanitize_description`，不重造**。命名**采本仓 `mcp_<server>_<tool>`（suffix 匹配）非 DeepCode `mcp__`**。commit=`feat(capabilities/mcp): normalize and sanitize remote tool descriptors`。
- [ ] **T4 · 重连/断开的恢复语义（在途 tool_call 如何闭合）**：目标=定义"transport 断开/重连时，OLD 连接上已发出的 `tool_use` 如何闭合"。**定案**：**不 auto-replay 副作用型远程调用**（避免 at-least-once 双执行远端不可逆动作），改为在结算点回填一条**error 形态的 `tool_result`**（`is_error=true`，内容点名"mcp server disconnected mid-call"）——这是**真实记录的结果**（调用确已尝试且失败），非 ADR-0028 被否的"合成 tool_result 骗协议"。涉及层=L2 `kernel/loop.py::_settle_open_calls`（`:697-725` 已有 OPEN→闭合机制，MCP 侧只需 execute 抛错/返回 error 让它自然闭合）。依赖=T2/T3。验证=见 §4「断连闭合专项」。commit=`fix(kernel): settle open MCP calls with error result on transport loss (no auto-replay of side-effecting remote tools)`。
- [ ] **T5 · C19 专项：断开/超时回填 `tool_result`（含审批等待变体）**（**P5 最可能自伤路径**）：目标=证明 MCP server 中途断开/超时时，已发出的 `tool_use` 必被回填 `tool_result`（error/timed_out），否则下一轮被配对关卡 fail-closed 成 `run_failed`。机理（代码真源）：`_execute_tool`（`kernel/loop.py:617-633`）把 `tool.execute()` 包在 `asyncio.wait_for(timeout=deadline)`，**捕 `Exception`（非 BaseException）→ 造 `ToolResult(status="error"/"timed_out")` → `RecordToolResult` 闭合配对**。因此要求：① MCP 适配器 `execute()` 在断连/握手失败时**必须 raise 或返回 error status**（不得吞异常返回成功、不得无限阻塞——超时由 `ToolSpec.timeout_s` 或 `Budget.tool_default_timeout_seconds`(120s，`contracts/state_schema.py:321`) 兜）；② **变体：断开发生在审批等待中**——`_handle_ask`（`:646-695`）里 call 处 `AWAITING_APPROVAL`：审批 Resolve 后 `MarkToolRunning→_execute_tool→execute` 抛（server 已没）→ error 闭合；审批超时→`ExpireApproval→denied`（`MarkToolDenied` 也写 tool_result）→ 闭合；两条路径都不留悬空。涉及层=L2。依赖=T2/T3/T4。验证=§4「断连闭合专项」+「审批中断开」判例。commit=`test(kernel): assert C19 pairing holds on MCP disconnect during execution and during approval wait`。
- [ ] **T6 · 命名空间冲突处置（重名/同名伪装内置工具）**：目标=远程工具与内置重名或伪装（如 server 报 `name="read"`）时的**拒绝 + 告警**。策略（对齐 C17 capability floor 不因远程放宽）：① 强制加 `mcp_<server>_` 前缀使全名不可能等于内置裸名；② 若 sanitize 后的全名仍与现有 spec 冲突→**拒绝注册该远程工具 + 发 `WARNING`（单行、含冲突名、不静默）**（呼应 DeepCode `naming.py:21-34` 冲突加 sha256 后缀，但本仓更保守：冲突即拒、不外露同名）。涉及层=L3 registry。依赖=T3。验证=§4「与内置同名」判例。commit=`fix(capabilities/mcp): reject and warn on remote/builtin tool-name collisions`。
- [ ] **T7 · MCP 调用经同一 Harness 工具路由写 `ToolLedger`**：目标=MCP 工具走 `_handle_tool_call`→`_execute_tool`→`RecordToolResult`（`kernel/loop.py:515-637`），**账本记录在 kernel、不在 MCP 层**。R04 明说 `log_mcp_call` 是**补充非替代**：DeepCode `core/mcp/tools.py:146-166` 的 `log_mcp_call` 只是遥测（"telemetry never changes tool outcome"），本项目**账本 = `event_log`（C13）**，MCP 结果**先进 `event_log` 再投影**，不在 MCP 层写第二套持久化。涉及层=L2/L3。依赖=T3/T4。验证=调用 MCP 工具后 `event_log` 有对应 `tool_started`/`tool_completed`（含 `tool_call_id`），且投影走白名单 `EXTERNAL_EVENT_FIELDS`（`kernel/events.py:49-51`，只有 `args_summary` 无全 args）。commit=`test(kernel): MCP tool calls route through harness and land in event_log before projection`。
- [ ] **T8 · Skills 加载：发现/解析/校验/坏文件降级**：目标=`SKILL.md` frontmatter 解析（safe_load）+ name/desc 校验 + 单坏文件不拖垮发现。涉及层=L3 `capabilities/skills/`（填实体）。依赖=无（可早于 MCP）。验证=DoD①；坏文件→结构化告警 + continue（改造 crewAI `skills/loader.py:44-117`+`parser.py:39-127`+`validation.py`）。**渐进披露**（METADATA→INSTRUCTIONS→RESOURCES）按 crewAI 形状，body 超 `_MAX_BODY_CHARS` 有界告警。commit=`feat(capabilities/skills): discover and parse SKILL.md with per-file failure isolation`。
- [ ] **T9 · `SKILL.md` 与远程描述的安全校验与有界（投毒/注入面）**：目标=skill 正文/描述、MCP 远程描述统一过：控制字符剥离 + 空白折叠 + 长度上界（`description_max_chars` / skill body `_MAX_BODY_CHARS`）+ 凭据形状不入工具面。涉及层=L3。依赖=T3/T8。验证=§4「远程描述超长/含敏感/含注入字符」。改造 hermes `mcp_security.py:1-40`（双门）+ DeepCode `tools.py:80-84`（raw args 只留受保护观测面）+ 复用本仓 `registry.py` sanitize + C20 白名单（`observability/projection.py` 载荷键不含 prompt/args/result 类）。**C20 关键**：skill 正文/远程描述进 prompt 是"载荷进模型"，但**绝不进观测面**（不得把远程描述/正文抄成日志里的第二份真相）。commit=`feat(capabilities): bound and sanitize skill bodies and remote descriptions`。
- [ ] **T10 · MCP/Skills 结果与输出复用 C18 既有 artifact 通道（禁旁路直抄）**：目标=远程输出/大结果走 `_output.py:41-69` `envelope_for_text`（超 `OutputBudget.model_result_bytes` → `FileSystemArtifactStore.put_text` + 有界 preview），`ToolContext.put_artifact`（`contracts/tool.py:105-111`）。涉及层=L3 用 L5 `providers/artifact_store.py`。依赖=T3/T8。验证=§4「大输出撑爆账本」反例：超阈结果只落 artifact ref + preview，**绝不把远程输出直抄进事件/日志**（C13/C18/C20）。改造自 DeepCode `tools.py:101-123`（result→ToolResult + metadata，不塞 raw）。commit=`feat(capabilities): route MCP/skill outputs through the bounded C18 artifact channel`。
- [ ] **T11 · 权限与沙箱对 MCP 工具的接入（capability floor 不因远程放宽，C17）**：目标=MCP 工具带 `capability`（`contracts/tool.py:24-31` 有 `NETWORK`）+ `risk`，走同一 `PermissionPolicy.evaluate` + `SandboxDescriptor` floor（`kernel/loop.py:547-563`）。**`read_only` 缺省 false=fail-closed**（DeepCode `tools.py:71-74` "hints not grants" 同向）；`approval_mode` unknown→deny。涉及层=L2/L3/L5 sandbox。依赖=T3。验证=§4「远程写/exec 不被 mode 放宽」；凭据/env 走 `providers/env_safety.py`（T15）。commit=`feat(kernel): enforce capability floor on MCP tools (remote hints never widen grants)`。
- [ ] **T12 · 把 P0–P2 预留的 draft/unimplemented 契约占位补实（R2，避免破坏性变更）**：目标=`contracts` 里 MCP/skill 相关占位落地为**只增不改**——`ToolSpec.approval_mode`（`:55`）、`Capability.NETWORK`（`:30`）、`ToolResult`/`ContentBlock`（`is_error`/`payload`）承载远程结果；**不新增 `EventType`**（用现有 21 个，`contracts/events.py:251-273`）。涉及层=L0 contracts（审慎，C6/C11）。依赖=T3/T7。验证=`check_protocol_schema --check` 零 diff；`contracts/state_schema.py:134-138` `TaskKind.SUBAGENT` 占位**保持不动**（属 P8）。commit=`feat(contracts): fill MCP/skill contract placeholders additively (protocol schema zero diff)`。
- [ ] **T13 · `parallel_safe`/`barrier` 注释与口径改判（消隐债）**：目标=依 §2.0 裁决，把 `contracts/tool.py:54,57`「NOT enforced until P5」改注为「deferred beyond P5 → dedicated parallelization phase / P8 gate」，同步 `HARD C19`（`:108`）、`ROADMAP §1.5`（`:35`）/`§2.5`（`:48`）、ADR-0028（`:72`）措辞；并**记一条 ADR**（跨阶段移动：先记 ADR 再改 ROADMAP，ROADMAP §5）。涉及层=L0 docs/contracts 注释。依赖=§2.0 定案。验证=全仓 grep "until P5" 无残留歧义（orchestrator 的 "until P8" 保留）。commit=`docs(contracts): re-scope parallel_safe/barrier from P5 to a dedicated parallelization phase (+ ADR)`。
- [ ] **T14 · 子进程观测接入（DESIGN §16.4，D-16.4-A/B）**：目标=MCP 子进程 stderr 重定向到独立文件（`mcp-stderr-<run_id>.log`）+ spawn 侧注 `run_id`（文件名主、首行标记辅）。涉及层=L5 `providers/process_runner.py`（Harness-owned，ADR-0018）+ 组合根 `QUESTOR_LOG_DIR`。依赖=T2。验证=DoD⑤/§4 跨进程关联判据。改造自 hermes `mcp_tool_config.py:22-63`（句柄治理）；**run_id 注入自写**（§0.3 D-16.4-B）。**C20 硬约束**：MCP stderr 文件是**独立通道、只放子进程自有输出**，绝不把 prompt/凭据/账本内容镜像进去；跨进程关联**只能显式注入**（文件名/首行），**绝不假设 ambient `bind()` 传播**（pitfalls 第 3 条）。commit=`feat(providers): redirect MCP subprocess stderr to per-run file with explicit run_id injection (C20/§16.4)`。
- [ ] **T15 · MCP/Skills 凭据与 env 接入（复用 `env_safety.py`，C17）**：目标=MCP server 子进程 env 经 `providers/env_safety.py` `scrub_environment`+`build_child_env`；provider 凭据即使被 `declare_env_passthrough` 也抛 `PermissionError`（`:68-70`）。涉及层=L5。依赖=T2/T14。验证=§4「env 值不入事件/日志 + 凭据不透传」；`env_scrubbed` 记名不记值（`contracts/state_schema.py:227`）。commit=`feat(providers): scrub MCP subprocess env via the shared env_safety guard`。

> **尾注（观测缺口收口，§0.4）**：bus 级只读订阅以覆盖 sidecar 带外投影 = **不在 P5 做**，列 §6 活文档回填 + 挂刀 3/P7。

---

## 3. 契约与红线自检

- **触及分层/契约？□ 是（先记 ADR 再动代码）** —— 新增 `capabilities/mcp`/`skills` 实体包、`mcp.json` 配置面、远程工具净化、`parallel_safe`/`barrier` 跨阶段改判，均触及 `contracts/`/分层/观测边界 → **前置 ADR**（T13 的并行改判 ADR；若改 `contracts` 形状再加一条）。**§6 硬门槛**：动代码前 ADR 到位。
- **逐条对照 C1–C20**（全量，非重点）：

| 红线 | P5 勾对结论 |
|---|---|
| **C1** 分层依赖方向 | MCP/Skills=L3；进程/env/artifact=L5 端口；kernel 不 import L3 实现（S3 注册表挂进）。✅ |
| **C2** 单写者+不可变视图 | MCP 结果只经 `Command→reduce`（`RecordToolResult`）；视图只读、COW（`contracts/state_schema.py:236-237` 深冻结 args）。✅ |
| **C3** 视图 vs 快照 | 正常 turn 只读视图；MCP 不改快照策略。✅ |
| **C4** Store 读写过接口 | MCP 不持裸 store/句柄；结果经 Harness→`event_log`。✅ |
| **C5** Command/Event 分离 | MCP 输入=Command（`ProposeAction`/`RecordToolResult`）；输出=Event；**事件不反哺状态**；**协议 schema 零 diff**（DoD④）。✅ |
| **C6** 事件内外分层+版本（含折叠/合并同罪延伸 `:42`） | 连接/解析失败**绝不静默**；错误类绕过节流、不折叠/合并（呼应 pitfalls 第 2 条）；未知 error 类事件必告警。✅ |
| **C7** 终止权在 Harness | MCP 挂起/取消走 `Cancel→reduce`（回填未闭合 tool_call），不 out-of-band 硬杀子进程（撤单由 T2 transport teardown + `process_runner` 负责）。✅ |
| **C8** 工具执行边界 | 远程 MCP 工具的**参数校验/权限/沙箱/超时全在 Harness**；敏感路径 denylist（`PROTECTED_IN_ROOTS` 含 `mcp.json`）不可被 mode 覆盖。✅ |
| **C9** 权限三态+沙箱可插拔 | MCP `approval_mode` 只收紧不放宽、unknown→deny（`contracts/tool.py:55`）；沙箱 floor（T11）。✅ |
| **C10** 插件生命周期+故障隔离 | MCP server=插件：连不上/崩→Harness 捕获、归一 error、发 `WARNING`/`run_failed`，**绝不带崩宿主**（DeepCode `tools.py:86-92` 只透传 KeyboardInterrupt/SystemExit，其余归一）。✅ |
| **C11** 状态模型谨慎演进 | MCP 不新定字段；复用 `ToolSpec`/`ToolCall`/`ContentBlock`；`ToolSpec.available` 动态性由 `Tool.available()` 真源。✅ |
| **C12** 远程策略预留非现在 | MCP 是"能力接入"非"策略远程化"；不把一切序列化；**无网络 exporter**（永久红线，日志不上网）。✅ |
| **C13** `event_log` 唯一真相+终态唯一 | **MCP 结果先进 `event_log` 再投影**（T7）；不在 MCP 层写第二套持久化；一 run 恰一终态。✅ |
| **C14** 结构边界机器守（S1–S7） | 新包 `capabilities/mcp`/`skills` 需 `.importlinter` 契约 + `check_layering_ast`；kernel 不 import 实现。✅ |
| **C15** 外部契约单一真源+守卫可信 | `protocol/*.schema.json` 零 diff；若 `.importlinter`/`check_layering_ast` 清单需扩，**必须同步扩且带 `--self-test` 判红 + fail-on-empty**（见 §4 守卫族）。✅ |
| **C16** Command Inbox 唯一外部写入口 | surfaces 只提交 Command；MCP 不直接 `reduce`/改 state。✅ |
| **C17** PermissionCtx/capability floor 优先于 mode | **远程不放宽 floor**（T11）；凭据/env 值不入事件/日志（`providers/env_safety.py`，T15）；`full_auto` 不把无围栏 exec/远程写降 allow。✅ |
| **C18** ToolCall 生命周期+输出载荷有界 | 远程描述与输出**有界 + 净化**，走 C18 artifact 通道（T10），禁旁路直抄。✅ |
| **C19** 回发前配对关卡+provider 故障不崩宿主 | **MCP 工具执行仍走串行/既有派发**；断开/超时**必回填 `tool_result`（error/timed_out）**，含审批等待变体（T4/T5）；不破 `_stream_turn` 唯一调用点关卡。✅ |
| **C20** 观测面不得成为载荷第二载体 | MCP 工具描述、远程结果、子进程 stderr 文件**都不得把 prompt/凭据/账本内容变成日志里的第二份真相**；MCP stderr=独立通道只放子进程自有输出（T14）；投影载荷白名单不含 args/result/prompt 键（复用 `scripts/check_projection_whitelist.py`）；**跨进程关联只能显式注入（文件名/首行），绝不假设 ambient 传播**（D-16.4-B）。✅ |

- **observability 关系明说**：`config ⟂ observability`（`configure_logging` 参数注入、env 读在组合根，ADR-0027）；`kernel → observability` 允许（S7 明文方向，`bind` 在 loop），**反向禁止**（observability 不得 import 上层）；**S7 内核零依赖不破**——MCP/Skills **不改 observability 九内核文件**，新增的 MCP stderr 落盘属 `providers/`（L5）非 observability，且不得把 `questor.*` 依赖塞进内核九文件（G-L1/G-L2 守）。

---

## 4. 测试与回归（**§2 每条子任务都有对应判红用例**）

> TDD：先写判红用例再实现（AGENTS §6 / PLAN 执行约定）。任何"已覆盖"若靠 mock 得出 → 标 **UNVERIFIED**。

- **单元**（镜像目录）：`capabilities/mcp` spec 净化/suffix 命名/冲突拒绝（T3/T6/T9）、`skills` frontmatter 解析与坏文件降级（T8）、env scrub（T15，复用 `providers/env_safety.py` 判例）、artifact 有界（T10，超阈→preview+ref）。
- **集成 · 真 stdio 假 MCP server（本地起真进程，不用 fake 对象冒充真进程）**：写一个最小 `mcp_stdio_server`（本地 py 脚本，JSON-RPC over stdio），roundtrip：`discover → tools/list → call → 结果进 event_log → 投影`（T7/DoD②）。断言：`event_log` 里该 `tool_call_id` 恰一 `tool_started`+一 `tool_completed`；投影 `EXTERNAL_EVENT_FIELDS` 只含白名单键（`args_summary`，无全 args）。**判红**：把结果改直抄事件 → G-L11/白名单守卫红。
- **连接失败/握手超时不崩且出声**：喂一个立刻退出/挂起的假 server → 归一结构化 error（`WARNING`/`run_failed`）、宿主进程 rc 正常、日志单行含 server 名。对应 T2。
- **`SKILL.md` 缺失/格式错不崩且出声**：缺 `---`/非法 YAML/目录名≠声明名/超 body 阈 → 结构化告警 + 其余 skill 继续被发现。对应 T8/T9。
- **远程描述异常**：超长 / 含凭据形状（`sk-`/`Authorization`）/ 含注入字符 / 与内置同名 → 净化有界 + 冲突拒注册 + 告警。对应 T3/T6/T9。
- **断连闭合专项（C19，T5）**：工具**在途时 kill 子进程** → `_execute_tool` 捕异常 → `RecordToolResult(status="error")` 闭合 → **下一轮 `_ensure_paired_history`（`loop.py:406-435`）不 fail-closed**（不产生 `pairing_violation`）。**变体**：断开发生在 `AWAITING_APPROVAL`（Resolve 后 server 已没 / 或 ExpireApproval）→ 均闭合。**判红**：让 MCP execute 吞异常返回成功 → 悬空 tool_use → 下一轮 `run_failed(pairing_violation)`，用例必须红。
- **跨进程关联判据（T14/DoD⑤）**：CLI 路径跑真 run（真子进程 + 真 IO），断言：按 `run_id` 能从主干 `questor-<date>.jsonl` inline 行 **和** `mcp-stderr-<run_id>.log`（文件名/首行）**分别**定位该 run 记录。**真子进程 grep canary**（不测 `LogEntry` 构造，pitfalls 第 1 条纪律③）。sidecar 带外投影 = **UNVERIFIED**（§0.4）。
- **守卫族全判红 + fail-on-empty**：冷导入 `import questor.capabilities.mcp/skills`；`lint-imports`（新包契约 + observability 五契约 kept）；`check_layering_ast`（kernel 未 import L3 实现）；**若清单需扩则同步扩 + `--self-test` 能判红**；`check_protocol_schema --check` **零 diff**；`scripts/check_projection_whitelist.py --self-test`（远程描述/结果键不入白名单）；`check_log_kernel_isolation.py`（observability 内核零依赖不破）。
- **流程与安全门**：细粒度英文 Conventional Commits；每次 commit/push 需用户逐轮明确许可（AGENTS §6）；**push/开 PR 前先走 L3 深度安全评审**——MCP 涉及**凭据与远程输入**（注入面、凭据透传、远程工具名伪装）是本轮审查重点。
- **自检矩阵**：T1→发现判例；T2→连不上/超时判例；T3→净化/命名判例；T4→重连状态自洽；T5→断连闭合专项；T6→同名冲突；T7→进账本再投影；T8→坏文件降级；T9→投毒/有界；T10→大输出走 artifact；T11→floor 不放宽；T12→schema 零 diff；T13→grep "until P5" 无残留；T14→跨进程关联 canary；T15→env 不入日志。**每条均有判红用例**。

---

## 5. 落地风险 & 备选

| 风险 | 触发条件 | 缓解 | 备选 |
|---|---|---|---|
| **远程工具面成为注入入口** | 恶意/被攻陷 MCP server 投毒描述或返回值 | T3 净化 + T6 冲突拒 + T9 有界 + C20 载荷不入观测面 + T1 载入/spawn 双门（hermes `mcp_security.py` 形状） | 默认拒所有远程工具 → 否（P5 DoD 要出工具）；靠人 review 每个 server → 否（不可扩展） |
| **MCP server 崩溃拖垮宿主** | 子进程 panic/挂起把 turn loop 带崩 | T2 transport 独占 task + 子 task 撤单（DeepCode）；T5 `_execute_tool` 捕 Exception + `asyncio.wait_for` deadline；BaseException 继续上抛（C10/ADR-0028 纪律） | 无超时裸执行 → 否（会卡死 loop） |
| **账本被大输出撑爆** | 远程结果巨大、直进 `event_log`/prompt | T10 复用 C18 `envelope_for_text`：超 `model_result_bytes`→artifact ref + 有界 preview | 截断原文塞满 fields → 否（C13/C18/C20） |
| **重连后状态不一致** | transport 重连、OLD 在途 tool_call 悬空 | T4 定案：不 auto-replay 副作用调用，回填 error `tool_result` 闭合；`_settle_open_calls` 已有 OPEN 闭合机制 | 合成 tool_result 骗协议 → 否（ADR-0028 被否方案，破账本/context 一致） |
| **并行占位被误当已生效** | 看到 `parallel_safe`/`barrier` 字段就以为可并行 | §2.0 显式移出 P5 + T13 改注释/口径 + ADR；执行严格串行（C19 `:108`） | 保持"NOT enforced until P5"歧义注释 → 否（隐债） |
| **真实远程 MCP server 不可复现** | 第三方 server 行为随版本/网络变，CI 不稳 | 用**本地真 stdio 假 server** 跑 roundtrip（§4）；真 key/真远程 server 端到端标 **UNVERIFIED** | 用 fake 对象冒充真进程 → 否（AGENTS §0，PLAN 刀 2 复审已证此坑） |
| **凭据/env 经远程侧外泄** | MCP server 继承父 env 拿到 provider key | T15 `env_safety.build_child_env`：provider 凭据即使 declare 也抛 `PermissionError`；`env_scrubbed` 记名不记值 | 全量透传 env → 否（C17 威胁模型） |
| **`mcp.json` 被 agent 自改扩大能力面** | run 内写 `mcp.json` 增/换 server | `PROTECTED_IN_ROOTS` 写保护（已含 `mcp.json`）+ mode 不可放宽（`test_permission_policy.py:212-220`） | 允许写自身配置 → 否（第二写者/能力自扩面） |
| **§0 行号 stale（P3 审计 F 类教训）** | 参考仓上游文件漂移 | 开工当天重验每条 `file:line`；stale 即改判"仅参照思路" | 信旧行号直接抄 → 否 |
| **许可/署名** | 搬 DeepCode/crewAI/hermes 片段 | 文件内标 provenance + CHANGELOG 注；EvoFlow evopanel 码零接触；autogen 仅搬 code(MIT) 文档需 CC-BY 署名 | 无署名照搬 → 否（AGENTS §5.6） |

---

## 6. 收尾（活文档，AGENTS §5.5）

- [ ] **偏差回填** `docs/adr/` 或 `docs/design/*`：实现与计划偏差 → reality-wins 写回本文 §7（执行期新增"实现偏差回填"节）+ 相应 design。
- [ ] **先记 ADR 再动代码**：① `parallel_safe`/`barrier` 跨阶段改判 ADR（§2.0/T13，ROADMAP §5）；② 若改 `contracts/`/分层/事件形状 → 对应 ADR（§3 前置门）。
- [ ] 更新 **`ROADMAP.md §1.5` P5 备注**（`:36`）：并行改判指向新 Phase；D-16.4 决策落地确认。
- [ ] **`CHANGELOG.md` `[Unreleased]` 追加**：Skills/MCP 能力（含 provenance/许可注：DeepCode/crewAI/hermes/CowAgent MIT；autogen code MIT；EvoFlow 仅形状）。
- [ ] **`docs/STRUCTURE.md` S2**（`:82`）：`capabilities/mcp`/`skills` 从"预留 stub"改为"实体"；`.importlinter` 契约 + `check_layering_ast` 清单同步扩（带 `--self-test` 判红 + fail-on-empty，C15）。
- [ ] **新增架构级易复发陷阱 → `docs/pitfalls.md` 对应分区**（跨子系统+高理解成本+会再踩才进；普通 bug 只走 Issue）。候选："子进程/线程侧 `run_id` 关联只在 spawn 边界可注入（文件名/首行），ambient 传播不可用"（若 P5 实测出新的架构级证据；否则沿用现有第 3 条）。
- [ ] **`docs/design/03-tool-interface.md` 等**：若已定稿因 MCP/Skills 有变（§6 远程工具映射、skill 工具）→ **就地修订** + 保持 locked/draft 标记诚实。
- [ ] **观测缺口收口挂账（§0.4）**：bus 级只读订阅覆盖 sidecar 带外投影 → 记入 CHANGELOG 诚实标注 + 挂刀 3/P7，不在 P5 做。
- [ ] **§0 表行号终检**（交付前防 stale）。

---

## 7. 文末诚实自检（逐问如实回答）

**Q1 · §0 表是否逐能力 ≥2 仓、每条带 `file:line`、"自写"都给了原因？是否排除本仓自身目录？**
- ✅ 逐能力均 ≥2 仓：生命周期（DeepCode+CowAgent+OpenManus+hermes）；描述归一（DeepCode×3 文件+OpenManus 对照）；Skills（crewAI×3+hermes×2）；凭据/投毒（hermes+DeepCode+本仓 env_safety）；stderr 重定向（hermes+GenericAgent 对照）。每条带 `repo:path:line` 且标"扫描快照 2026-10-17，开工当天重验"。
- "自写"原因给了：`run_id` 注入（§0.3 D-16.4-B）= 参考实现（hermes 单一共享 `mcp-stderr.log`）与本项目"按 run_id 定位"判据不兼容，拿过来不能直接用。
- ✅ 排除 `questor` 与 `questor-log-foundation`（§0.1）。

**Q2 · C1–C20 是否逐条勾对（非只列重点）？C20 与 §16.4 两条决策是否落成明确设计而非口号？**
- ✅ §3 表格 **C1–C20 全量逐条**，无遗漏。
- ✅ C20：落成"观测面不得成第二载体"的具体约束——MCP 描述/结果/stderr 文件不入载荷、投影白名单、跨进程关联只能显式注入（不假设 ambient）——并指向复用件（`check_projection_whitelist.py`/`projection.py` 白名单），非口号。
- ✅ §16.4 两条决策落成**明确设计**：D-16.4-A（stderr 独立文件 + 句柄治理形状）+ D-16.4-B（文件名主/首行辅注入 `run_id`，含"为什么文件名而非 bind"的语言事实依据 + DoD⑤ 判据），非"待议"。

**Q3 · `parallel_safe`/`barrier` 归属是否已裁决并写明理由？**
- ✅ §2.0 **裁决：移出 P5、显式推迟到专门并行化 Phase（目标 P8 gate）**，给三条理由（DoD 不需、与 C19 自伤面正交但叠 blast radius、并行 gate 是独立子系统）；配套 T13（改注释/口径 + 记 ADR）+ §5 风险行 + §6 ADR 项，**不留隐债**。

**Q4 · §2 每条子任务是否都有 §4 判红用例？有无用 mock 冒充真进程/真远程 server 而未标注？**
- ✅ §4 末尾**自检矩阵**逐一对应 T1–T15；断连闭合专项、跨进程关联 canary、真 stdio 假 server roundtrip 都要求**真进程/真 IO**。
- ✅ 无 mock 冒充：明确"不用 fake 对象冒充真进程"；真 key/真远程 server 端到端、sidecar 带外投影均标 **UNVERIFIED**（§0.4/§4/§5）。

**Q5 · 基线 commit 是否已记入 §0（决定 C20/pitfalls 是否存在的依据）？**
- ✅ §0.0 记入 **基线 = `main` @ `68a225b`**，并证 PR #140 已合入 → **C20（`HARD-CONSTRAINTS.md:110-116`）与 `docs/pitfalls.md` 存在**，P5 在其约束下规划。

> **诚实边界**：本文为 READ-ONLY 规划，只落此文档，未改代码/未建分支/未 commit/未 push。所有 `file:line`（本仓与参考仓）为 2026-10-17 扫描快照，开工当天必重验；真机凭据/真远程 MCP server 的端到端效果标 UNVERIFIED。
