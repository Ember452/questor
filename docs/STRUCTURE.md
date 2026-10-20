# Questor 项目结构（参考，非硬约束）

> ⚠️ **这是参考蓝图，不是死规矩。** 目录/命名可按实现需要调整、增删、合并——**不必一模一样**。
> 唯一真正要守的是**分层与依赖方向**（见 [`design/00-layering.md`](./design/00-layering.md) 与 `HARD-CONSTRAINTS`），
> 不是具体文件夹叫什么。结构服务分层；若两者冲突，**以分层纪律为准**。若你改了这里的示例结构，无需改设计文档。

一个**双栈 monorepo**：Python 后端（Agent Harness + 策略）是产品核心与真源；桌面是 Tauri 壳 + Web 瘦客户端，**只经事件协议连后端**。

---

## 1. 顶层

```
questor/
├── pyproject.toml · uv.lock · .python-version     # 依赖/工具链（uv, Python 3.13）
├── ruff.toml (或并入 pyproject) · .importlinter    # lint + 分层依赖守卫
├── AGENTS.md · CLAUDE.md · README.md · LICENSE · .gitignore
├── docs/            # 设计/决策/计划（见 docs/ 现状）
├── src/questor/     # ★ Python 后端：Harness 内核 + Agent 策略
├── tests/           # Python 测试（单元 + 任务级评测/回归网）
├── desktop/         # Tauri 桌面应用（Rust 壳 + Web 前端）
├── scripts/         # 开发/构建/一次性脚本
├── assets/          # 图标/静态资源（品牌）
└── .github/workflows/  # CI（可 P 后期再铺）
```

## 2. Python 后端 `src/questor/`（按层切包）

```
src/questor/
├── contracts/       # L0 共享词表：状态 schema · 事件类型 · ToolSpec · 各 Port 接口  ← 最稳定
├── state/           # L1 领域/核心状态模型（Domain_State、任务树、账本、不变式、reduce）
├── kernel/          # L2 Harness 运行时：turn 循环(阶段) · 调度 · 压缩 · checkpoint · 权限引擎 · 事件总线
├── capabilities/    # L3 能力：tools/ · skills/ · mcp/ · （后期）subagent 编排
├── policy/          # L4 Agent 策略（可插拔）：ReAct/规划/反思/记忆策略，实现 PolicyPort
├── providers/       # L5 端口 + 适配器：ProviderPort→LiteLLM · StorePort→SQLite/向量 · Clock · Id
├── surfaces/        # L6 传输/接入：HTTP+SSE 事件服务 · /run·/cancel·/resume · OpenAI兼容 · IM · CLI
├── config/          # 配置加载（含 secrets 边界）
├── observability/   # 日志 · 事件溯源查询 · trace（横切）
├── __main__.py · composition.py         # 组合根 + CLI/serve 入口（sidecar 启动点）
```
- **依赖方向**：外层 → 内层；`kernel` 只依赖 `contracts/state/providers 端口`，**不 import `policy`/`surfaces` 具体实现**（用端口注入）。策略/MCP 通过注册表挂进内核。
- **P2 新增接缝（ADR-0013-0019）**：`contracts/{inbox,process,sandbox,shell_analysis,artifacts}.py` 与扩展后的 `state_schema/events/tool.py` 只放数据/Port；`kernel/{run_control,permission_policy,capability_floor,shell_parse_posix,shell_parse_powershell}.py` 放机制；`providers/{process_runner,artifact_store,env_safety}.py` 放适配器；`capabilities/tools/{read,write,edit,apply_patch,ls,glob,grep,bash,powershell}.py` 只经 ToolContext 请求进程/artifact；surfaces 只提交 Command。
- `contracts` 是全系统"词汇"，改动最保守（C6/C11）。

## 3. 桌面 `desktop/`（Tauri v2）

```
desktop/
├── src-tauri/       # Rust 壳：窗口/生命周期/打包；把 Python 后端作为 sidecar 子进程拉起（P7 尚未建，UNVERIFIED）
│   ├── src/  tauri.conf.json  build.rs  capabilities/  icons/
├── sidecar-requirements.{in,lock}  # sidecar 冻结窄锁（比根 pyproject 更窄；uv pip compile 产出）
└── web/             # 前端（TS）：瘦客户端，仅消费事件协议（SSE）
    ├── package.json · tsconfig.json · scripts/generate-protocol.mjs   # 协议 codegen + --check 防漂移
    └── src/
        ├── generated/event.ts        # 由 protocol/event.schema.json codegen（DO NOT EDIT）
        └── api/{eventStream,commandClient}.ts   # 瘦客户端：仅投 Command + 消费事件（无业务下沉）
```
- **铁律**：`web/` 只做 UI 与"订阅外部事件"，**禁止把业务/状态/校验逻辑下沉到壳**（ROADMAP §1.5 / ADR-0007）。
- `src-tauri` 不碰内核逻辑，只负责启动 sidecar + 暴露窗口能力。
- **P7 现状（`feat/p7-desktop-shell`，含审计后加固）**：`web/src/{generated,api}` + Vite 薄客户端 app（`tsc`+`vite build` 产 dist）、
  `scripts/generate-protocol.mjs`（含 per-type `*Data` 字段级接口 + 漂移 `--check`）、`sidecar-requirements.{in,lock}`、
  **`desktop/sidecar` Rust crate**（generation 栅栏/两级优雅关闭/`fail_all`/loopback 就绪/Job Object 杀进程树/`resolve_sidecar`，
  `cargo test`）、**`desktop/src-tauri` Tauri v2 壳**（spawn 冻结产物、读 bootstrap、注入 token、退出走 `/shutdown`）均已本地
  **cargo `check`/`clippy`/`test` 编译验证**；sidecar serve 生产入口 `src/questor/surfaces/serve.py`（loopback `127.0.0.1:0` +
  generation bootstrap + 会话 token，ADR-0032）由组合根 `__main__.py --serve` 装配；PyInstaller onedir 已用 `build-sidecar.py`
  实产并经 `verify_release_bundle --verify-runtime` 启动验证；本轮另以 clean-PATH（无 `python`）直跑冻结 exe 证伪 `/health`=200 与 `/shutdown` 优雅自退（Exited）。
  **§6-5/6-6 生命周期**：`contracts/sidecar_status.py`（Starting/Ready/Stopping/Stopped/Crashed，独立进程级 status 面、不进 per-run 信封）+ `protocol/sidecar_status.schema.json` + codegen TS 判别类型 + `check_protocol_schema` 字段级漂移门；Rust 壳 `monitor_sidecar_loop` 崩溃→emit→respawn（bump generation）→重导航，UI 订阅渲染 Crashed 横幅（capability 限 `core:event:allow-listen` 到 `http://127.0.0.1:*`）。**仍 UNVERIFIED**：真开窗口/像素渲染、真机 kill→Crashed→重启端到端与 after_seq 重挂（§6-8）、全量 `tauri build` 安装介质（需显示 + WiX）、真远程 MCP/真 LLM。

## 4. 测试 `tests/`
- 单元测试随模块镜像目录；**任务级评测/回归网**单列（如 `tests/evals/`），改内核前必备（ROADMAP P10）。
- CI 门禁：冷导入 + `import-linter` 分层守卫 + 单测 + 回归；外部事件契约快照 diff。
- P2 起持续产 coverage baseline：branch coverage + `coverage.xml` artifact；此阶段不设全局 `fail-under`，先建立可比较基线，再按安全模块逐步抬门槛。

## 5. 命名/风格约定
- 小写包名、动词/名词清晰的模块；跨层只暴露 Port/契约，实现细节不外泄到上层 `__init__`（HARD-CONSTRAINTS C1）。
- 新能力优先落进"对应层的插件/注册项"，而非往 `kernel` 堆代码。

## 6. 与分层的对应（结构服务纪律）
| 层 | 目录 |
|---|---|
| L0 Contracts | `src/questor/contracts/` |
| L1 State | `state/` |
| L2 Kernel/Harness | `kernel/` |
| L3 Capabilities | `capabilities/` |
| L4 Policy | `policy/` |
| L5 Ports | `providers/` |
| L6 Surfaces | `surfaces/` |
| L7 Shell | `desktop/` |

## 7. 落地边界补充（评审采纳 S1–S7）
> 共同落点：**目录只是提示，真正防错靠 `.importlinter` 契约 + Port 抽象**——见 [HARD-CONSTRAINTS](./design/HARD-CONSTRAINTS.md) C14。
- **S1 providers 命名**：`providers/` 含 LLM+存储+时钟/ID 的**适配器**，易被误读为"模型提供商列表"。保留名 + 放目录 `README.md` 说明"所有底层基础设施 Port 的实现"即可（不改名）。
- **S2 capabilities 膨胀**：P2 只实现内置 tools；P5 起 `mcp/`（官方 SDK 连接、远程工具→`ToolSpec`、per-run stderr+run_id 关联）与 `skills/`（`SKILL.md` 发现/加载/目录注入）落**实体**（`docs/plan-archive/05`）；`subagent/` 仍为 stub 至 P8。
- **S3 注册/注入必须落地**：policy/MCP 经注册表+端口挂进 kernel；**禁止 kernel 直接 import policy 具体实现**，由 import-linter 强制（非口头约定）。
- **S4 抽象 vs 实现分家**：`contracts/` 只放**抽象 Port 协议 + 数据模型**；`providers/capabilities/policy` 放具体实现。实现写进 contracts 会让"最稳定层"持续膨胀、破 C11。
- **S5 进程边界（Tauri）**：Python Harness 是**独立 sidecar 进程**，Rust 壳与它**只经 HTTP+SSE 事件协议通信**，**严禁进程内直调 Python 函数**（否则破"Shell 只消费事件"铁律）。
- **S6 surfaces 零业务**：`surfaces/`（HTTP/CLI/OpenAI 兼容）只做 Command 接收 + 事件协议转发/翻译；**不实现业务、不改 state**，一切写操作造 Command 送入 kernel 总线。
- **S7 observability 依赖方向（双条，ADR-0027）**：① **调用方向**——可被各层调用（含 `kernel`→`observability`，AST 明文允许方向），只读/上报、**不改状态**；真正的红线只在**反向**（observability 不得 import 上层实现）。② **内核零依赖**——`observability/` 九个**内核文件**（`entry`/`scope`/`redact`/`exporter`/`sink_console`/`sink_file`/`bridge`/`pipeline`/`configure`）**零 `questor.*` 依赖、连 `contracts` 都不许**（保"将来抽包 = 纯机械搬目录"）；唯 `projection.py`（适配层）允许 import `questor.contracts`。故旧表述"只依赖 contracts"仅适用于适配层、不适用于内核（`grep 只依赖 contracts` 会误导抽包）。机械强制：`.importlinter` 第五契约（意图声明）+ `scripts/check_log_kernel_isolation.py` G-L1/G-L2（含 `--self-test`）。

## 8. 再次强调
> 以上目录/命名是**便于阅读、可维护的常见大型开源布局**，不是必须照抄的硬约束。实际实现时按需要长什么样就长什么样；
> **要守的只有那几条分层依赖与接缝契约**。改结构 → 不必改设计文档；改分层/契约 → 才需要走 ADR。

## 9. 工程拓扑与守卫增补（仍为参考、非硬约束）
- **分层强制三道防线**（非单一 import-linter）：声明式 `.importlinter` + ruff `flake8-tidy-imports.banned-api` 点名禁跨层 import（附"改走哪个 Port"）+ `ban-relative-imports=all` + 自研 AST 检查器；**以包边界为主、lint 为兜底**（HARD C15）。
- **跨语言 wire 契约单一真源**：顶层 `protocol/*.schema.json`（外部事件投影的唯一 JSON Schema）→ codegen 生 TS 类型 → CI `--check` 防漂移（呼应 02/C6）。
- **sidecar 构建三段式**（Python→桌面）：`desktop/sidecar-requirements.{in,lock}`（**比根依赖更窄**）→ PyInstaller **onedir** 冻结（非 onefile）→ tauri `bundle.resources` 打进包 → 发布前 `verify-release-bundle`（导入探针 + initialize/shutdown RPC smoke）。**dev 与打包依赖分两份锁**。
- **工具链钉死**：`.python-version` + `.node-version` + `rust-toolchain.toml` + 各语言 lockfile（`uv.lock`/pnpm|npm lock/`Cargo.lock`）。供应链 `[加固]`：核心 exact-pin、provider 走 extras、`exclude-newer` + `pip-audit`/osv 进 security lane。
- **CI 分道**：`python-ci` / `desktop-ci`(Rust+web) / `security-ci` + **改动分类器跳过无关 job**；契约快照挂 `contracts_changed`；**分层守卫/冷导入作为不依赖分类器的独立 blocking job**。
- **每条机械守卫带 `--self-test` + fail-on-empty**（扫不到文件≠通过）。
- **反面清单（别照抄）**：别扁平文件海（保持 src 包化）、别把核心代码不打包、别靠整目录 lint 豁免维持边界。长期记忆子系统落 `src/questor/memory/`（与 `state/` 分离，见 `design/06-memory.md`）；策略契约 `contracts/policy.py`、实现 `policy/`。

## 10. 开源仓库完整骨架（目标；此前只写了架构层，遗漏了 OSS 治理层）

> ⚑ 标记：**[N]**=现在就该有（不依赖代码）；**[P#]**=等对应里程碑有实物再铺（避免空 CI 假绿）。

```
questor/
├── README.md            [N]  门面：徽章/一句话/截图-gif/快速开始/功能表/架构指链/贡献链接/许可证
├── LICENSE              [N]  MIT（需版权人+年份）
├── CONTRIBUTING.md      [N]  开发环境(uv)、分支/提交规范、跑测试/lint、提 PR 流程、AI 辅助声明
├── SECURITY.md          [N]  漏洞报告渠道 + 支持版本表（桌面 agent 必配）
├── CODE_OF_CONDUCT.md   [N]  Contributor Covenant
├── CHANGELOG.md         [N]  Keep a Changelog 格式、按里程碑追记
├── .gitattributes        [N]  统一换行（Windows 开发必需）、二进制标记、export-ignore
├── .editorconfig         [N]  跨编辑器缩进/编码一致
├── .env.example          [N]  配置模板（无真凭据）
├── .pre-commit-config.yaml[P2]  ruff/格式/hook（有代码后）
├── .github/
│   ├── workflows/        [P0+]  ci-python / ci-desktop / security / release（需代码才能真跑）
│   ├── ISSUE_TEMPLATE/   [N]  bug.yml / feature.yml / config.yml（禁用空白 issue）
│   ├── PULL_REQUEST_TEMPLATE.md [N]
│   ├── dependabot.yml    [N]  升 pip/npm/cargo/github-actions
│   ├── CODEOWNERS        [N]  单人项目可省或指自己
│   ├── actions/          [P]  复用自定义 action（如 ci-scope）
│   └── FUNDING.yml       [N]  可选（GitHub Sponsors 等）
├── docs/
│   ├── VISION · ROADMAP · STRUCTURE · ARCHITECTURE   （现有些已在）
│   ├── getting-started/  installation / quickstart / configuration  [N]
│   ├── guide/            usage / models(LiteLLM) / tools / desktop   [P#]
│   ├── reference/        api / event-protocol / cli                [P#]
│   ├── adr/  design/  references/   （已有）
│   └── media/            图片/动图
├── src/questor/          （见 §2）
├── tests/
│   ├── unit/  integration/  evals/   [P1+]
│   └── conftest.py
├── examples/             [P#]  可跑示例/脚本
├── scripts/              dev/build/lint 辅助
├── assets/               logo/图标/截图
├── desktop/  (Tauri：src-tauri/ + web/，见 §3)
├── pyproject.toml · uv.lock · .python-version · .node-version · rust-toolchain.toml
└── .gitignore
```

**README 标配（开源项门面）**：顶部徽章(CI/license/release/ stars)、一句话定位、一张截图/gif、特性表、快速安装/运行、指向 `docs/` 的链接、贡献指引、许可证。
