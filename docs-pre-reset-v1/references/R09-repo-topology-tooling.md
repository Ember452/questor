# R09 · 工程拓扑与守卫外部参考扫描（→ docs/STRUCTURE.md）

> 只读扫描，不改代码，不改 STRUCTURE 原文（评审默认：只提增量/取优，不推翻）。目标维度=**工程拓扑与守卫**，不看业务实现（归 R01–R08）。
> 逐项目回答同一组问题：① 顶层目录怎么切；② 依赖分层是否被**工具**强制（import-linter / ruff / eslint / 架构测试 / CI 门禁，贴配置原文）；③ 多语言单体怎么组织与构建（Python→sidecar、Rust 壳、TS 前端、lockfile/workspace/Makefile）；④ 该维度的最佳实践与反面教训。最后横向综合，给 STRUCTURE 一套"取各家之长"的落点。
> 证据项目（全部实读、非抽样、带 `文件:行号`）：`hermes-agent-main`、`wuu-main`、`DeepCode-main`、`CowAgent-master`、`crewAI-main`、`autogen-main`、`MetaGPT-main`、`OpenManus-main`、`GenericAgent-main`、`cordis-main`、`EvoFlow-main`、`Agent-S-main`。
> 前置已读：`docs/STRUCTURE.md`、`docs/design/00-layering.md`、`docs/design/HARD-CONSTRAINTS.md` C14。
> 纪律：**STRUCTURE 是参考蓝图非硬约束**——落点是"目录拓扑 / 工具 / 守卫机制"，不是死磕命名（`项目结构文档参考性原则`）。
> 状态：待评审采纳；采纳项回写 STRUCTURE 时按其 §1/§4/§7 现有编号对齐。

---

## ① 结论（增量总览）

STRUCTURE 现状方向对（双栈 monorepo：Python 后端为真源 + Tauri 壳 + Web 瘦客户端 + 按层切包 + `.importlinter`/ruff 分层守卫 + 契约快照 diff）。但相对 12 家实装，**在五个维度上偏薄或缺失**：

1. **`.importlinter` 在本参考集里零采用**——12 个项目**没有一个**用 import-linter（`Grep import[-_]?linter|importlinter → 0 命中`）。真正在业界被用来"机械守分层"的是三条替代路线：① Go `internal/` **编译期可见性**天然封边界（wuu）；② ruff `flake8-tidy-imports.banned-api` **点名禁某些 import**（hermes/autogen/DeepCode）；③ **自研 AST/正则 CI 检查器**扫 `git ls-files` 追踪文件、命中即红、且"扫不到东西也算失败"（hermes `check_lazy_deps_imports.py`、wuu `check-test-policy.mjs`）。STRUCTURE S3/§4 把 import-linter 当唯一强制手段，**缺一条已被验证的兜底**。
2. **缺"跨语言契约单一真源"**——STRUCTURE 有 Python 内 `contracts/`，但**进程边界外**（S5：Python↔Rust↔TS）的事件协议没有一个**语言中立的 schema 文件 + 代码生成 + 漂移检查**承载。DeepCode 用顶层 `protocol/app-server.schema.json` → `generate-protocol.mjs` 生成 TS 类型 → `check:protocol` 进 CI 阻断，正是 questor C6"外部事件契约快照 diff"的可抄实现。
3. **sidecar 依赖与主依赖混一份**——STRUCTURE §1 只有一个 `pyproject.toml + uv.lock`。DeepCode 把**打包进桌面的 Python 运行时**单列 `desktop/sidecar-requirements.{in,lock}`（"narrower than CLI dev"），用 PyInstaller 冻结、经 tauri `bundle.resources` 落进安装包——questor 的"Python→sidecar"缺这套**独立锁 + 冻结 + 打进 bundle** 的构建链。
4. **CI 门禁口径粗**——STRUCTURE §4 只列"冷导入+import-linter+单测+回归+契约快照"。缺：① **按语言分道**（python/web/desktop/security 各自一条 lane）；② **改动分类器跳过无关 lane**（DeepCode `.github/actions/ci-scope` 的 `runtime_changed`/`desktop_changed`）；③ **重活错峰**（每 OS 的 bundle 只周跑/手动，PR 只跑质量门）；④ **守卫脚本自带 `--self-test`**（wuu/hermes：证明检查器本身能判红判绿）。
5. **缺"工具链/供应链"守门清单**——各家普遍用文件钉死工具链（`.python-version`/`.node-version`/`go-version-file`/`rust-toolchain.toml` + 各语言 lockfile），并有供应链红线（hermes 核心依赖**全 exact-pin**、crewAI/autogen `exclude-newer` + CVE `override-dependencies` + `pip-audit`）。STRUCTURE 只提了 uv/`.python-version`，没把"锁+钉+审计"列成守卫。

**取舍**：hermes 的体量（58 条 workflow、40+ 个根级 `hermes_state_*.py`、数百行 ruff 规则）来自极端健壮性，v1 **不必全抄**；本文件给每条标 `[P1]`（进 v1 骨架）/`[加固]`（里程碑后补），只强推 `[P1]`。

---

## ② 各项目做法（证据）

### DeepCode-main（★ Python→Tauri sidecar 的最佳蓝本；四道 CI lane + 跨语言契约）

**① 顶层切分**：Python 后端 `core/`（按层切子包：`domain`/`application`/`harness`/`loop`/`events`/`providers`/`persistence`/`observability`/`plugins`/`skills`/`mcp`/`sessions`/`team`/`network`/`config`）、`app_server/`（HTTP/JSON-RPC 传输面）、`cli/`、`desktop/`（壳）、顶层 `protocol/`+`schema/`（**跨语言契约 JSON**）、`tests/`、`docs/`、`scripts/`、`workflows/`。`desktop/` 内 `src/`(TS web) + `src-tauri/`(Rust) + `e2e/`(playwright) + `sidecar-requirements.{in,lock}` + `build:sidecar` 脚本。

**② 分层是否被工具强制**：**无 import-linter**。用 ruff `per-file-ignores` 给 vendored skills 让路（`pyproject.toml:32`：`"core/skills/builtin/**" = ["ALL"]`——"Lint the host around them without rewriting vendor workflows"）；`check-manifest` 把 sdist 只含 Python 运行时、`desktop/**`/`tests/**`/`docs/**` 不进 PyPI 包（`pyproject.toml:34-49`）。**真正的分层靠进程边界**：`protocol/app-server.schema.json` 是 Python app-server 与 TS/Rust 的唯一契约（跨语言即跨进程，结构上封死"壳碰内核"）。

**③ 多语言构建（sidecar 全套）**：
- `desktop/src-tauri/tauri.conf.json:9` `beforeBuildCommand: "npm run build && npm run build:sidecar"`；`:33-37` `bundle.resources` 把 `../build/sidecar/dist/deepcode-app-server/` 映射成包内 `app-server/`——**PyInstaller 冻结的 Python 后端作为 bundled resource 随 tauri 安装**（非 externalBin 单文件）。
- `desktop/sidecar-requirements.in:1-3`：sidecar 运行时依赖"keep this list **narrower** than the CLI development environment so packaging is reproducible"；`:21` 单列 `pyinstaller==6.21.0`。
- `desktop/package.json:11-13,16-17`：`setup:sidecar`（建锁死 venv）、`build:sidecar`（PyInstaller）、`generate:protocol`/`check:protocol`（从 JSON-schema 生 TS 类型 + 漂移检查）、`audit:licenses`（许可证溯源→随包分发 `THIRD_PARTY_NOTICES.md`）。`build` 脚本 `:8` 串了 `check:version && check:tauri && check:protocol && tsc --noEmit && vite build`。
- CI 四道分道 + 改动分类：`python-ci.yml` / `desktop-ci.yml` / `web-ci.yml` / `security-ci.yml`；每条首步 `uses: ./.github/actions/ci-scope`（`python-ci.yml:34-36`）产出 `runtime_changed`/`desktop_changed`，无关即跳过整条 job。`desktop-ci.yml`：push/PR 只跑 `quality`（`cargo clippy -- -D warnings` `:138`、`npm run typecheck/lint/test/build` `:117-127`），每 OS 的 `bundle`（90 分钟/OS）**仅 schedule+dispatch 跑**（`:141-150`）；bundle 后 `verify-release-bundle.py` `:262` 验证 sidecar 真在包内且能跑。Python 版本矩阵：`main` push 只跑主解释器、PR 跑全支持范围（`python-ci.yml:26`）。

**④ 最佳实践**：sidecar 独立锁+PyInstaller+bundle.resources+发布期校验，是 questor "Python→sidecar" 可直接照搬的骨架；`protocol/*.schema.json` 单一契约 + 生成 + `--check`；四道 lane + 改动分类 + 重活错峰。**反面教训**：sdist 用 `check-manifest` 手工列 ignore（新增非 Python 资源易漏进/漏出）；`per-file-ignores = ["ALL"]` 对 vendored 代码整体豁免=审计盲区。

### wuu-main（★ Go 编译期封边界 + 自研 policy-check 脚本群 + Makefile 跨语言分派器）

**① 顶层切分**（Go 单体多语言）：`internal/`（**~70 个纵向职责子包**：`appserver`/`agentcontrol`/`agent`/`loopdriver`/`providers`/`compact`/`storelock`/`toolledger`/`pluginhost`/`processsandbox` 等）、`cmd/`（**每二进制一目录**：`wuu`、`wuu-server`、`wuu-*-plugin` 十余个）、`packages/`（`protocol`/`plugin-sdk`/`plugin-go` 跨语言产物）、`clients/`（`core`/`mobile`/`mobile-app`/`mobile-web`/`native` 多 TS 端）、`desktop/`（Electron TS）、`docs-site/`、`plugins/`、`prompts/`、`evals/`。

**② 分层是否被工具强制**：**两道**——(a) **Go `internal/` 可见性**：编译器强制模块外不可 import，天然把内核实现封在边界内（无需 lint）；(b) **自研 policy-check 脚本**（TS 写、带 `--self-test`）：`Makefile:43-49` 定义 `test-policy-check`/`docs-policy-check`/`eval-check`/`theme-contract-check`，如 `scripts/check-test-policy.mjs:1-10` 是"merge-gate：产品测试不得读样式表源码钉死声明"，`:27-30` 维护 allowlist、`:31-32` 正则扫、`:35` `--self-test` 自证判红判绿。`Makefile:33-37` 把这些聚成 `check → repository-check → repository-metadata-check → …`。

**③ 多语言构建**：`Makefile` 是跨语言任务分派器——`check-go`/`check-desktop`/`check-clients` 各走各栈（`Makefile:63-79`），`build-go`(ldflags 注入 version/commit/date `:11-14`) / `build-desktop` / `build-clients`；工具链钉死：`go-version-file: go.mod`、`node-version-file: .node-version`（`ci.yml:31,56-62`）；`check-go:63-69` 跑 `go mod tidy -diff` + `gofmt -l` + `go vet` + **交叉编译 GOOS=windows/darwin**（防平台专属代码腐）。`ci.yml:23-34` `repository-check` job、`:36+` `go-validation`（起 postgres service）。

**④ 最佳实践**：`internal/` 把"边界"交给编译器而非约定；**policy-check 脚本群 + 每个 `--self-test`** 是把"我们独有的红线"落进 CI 的通用范式（questor 的 C1/C14 正是"独有红线"）。**反面教训**：`internal/` 下 70 个子包**扁平无二级分组**，靠命名前缀（`agent*`/`execution*`/`plugin*`）聚类——包多到一定程度"分层"就退化成"命名约定"，无二级目录树提示归属。

### hermes-agent-main（★ 体量最大的守卫家族：ruff 点名禁 import + AST 兜底 + lefthook 多栈路由 + 供应链钉死）

**① 顶层切分**：Python 多子树（`agent/`、`gateway/`、`hermes_cli/`、`tools/`、`providers/`、`plugins/`、`skills/`、`pm/`、`cron/`、`acp_adapter/`、`native/`(Rust fts5)），多前端（`apps/desktop`(Electron)、`apps/shared`、`web/`、`ui-tui/`、`tui_gateway/`），测试分 `tests/`(py)+`tests-js/`+`evals/`，另有 `plugin-catalog/`、`optional-mcps/`、`optional-skills/`、`locales/`(35 语言)。**反面信号**：根目录散落 **40+ 个 `hermes_state_*.py` 顶层模块** + 大量 `*.py` 单文件——顶层是"扁平文件海"而非二级包。

**② 分层是否被工具强制**（三种守卫并存，最丰富）：
- **ruff `flake8-tidy-imports.banned-api`**（`ruff.toml:460-466`）：点名禁 `pm.uv`/`pm.client.uv`/`pm._uv`/`pm.environment`/`pm.runtime_stage`，每条带 msg 指路"用 PM 语义操作而非裸执行器/私有引擎"；`:468-471` `per-file-ignores` 给 `pm/**`、`tests/**`、fixtures 放行。**这就是"内层实现不得被外层直接 import"的可抄 lint 写法**（对应 C1/C14）。
- **自研 AST 兜底检查器**（`scripts/ci/check_lazy_deps_imports.py`）：`_tracked_python_files` 走 `git ls-files`（`:51`）只扫被追踪文件、排除 `tests/`；**"never passes by scanning nothing"——空清单/读失败/解析失败一律 exit 2**（`:73-78,154-162`）；AST 匹配 `import`/`from`/相对导入的真实导入点（`:98-133`），命中 exit 1 打出 `path:line`。`lazy-deps-guard.yml:15-19` 注明"无条件跑、不因语言 lane 被门控"，契约测试 `tests/pm/test_no_lazy_deps.py` 用 fixture 仓证 red/green。
- **lefthook 多栈 pre-commit 路由**（`lefthook.yml:1-36`）：python 走 `ruff check --config ./ruff.pre-commit.toml`（**pre-commit 用单独一套收紧的 ruff 配置**），TS 按子项目 root 分别 `npx eslint`（`web/`、`apps/desktop/`、`apps/bootstrap-installer/`、`ui-tui/`、`apps/shared/`、`tests-js/`）。
- **供应链钉死**（`pyproject.toml:20-39`）：核心直接依赖**全 exact-pin `==X.Y.Z`**（附 Mini Shai-Hulud 蠕虫投毒的 rationale），"只有每次会话都用得到的包进 core deps，provider-specific 进 extras 走 PM 懒装——小 dependencies=小爆炸半径"。

**③ 多语言构建**：根同时挂 `pyproject.toml`+`package.json`+`justfile`+`lefthook.yml`+`ruff.toml`；`native/` Rust、`apps/desktop` Electron、`web/`/`ui-tui/` TS。CI **58 条 workflow**，含 `rust-tests.yml`/`js-tests.yml`/`desktop-bundle-smoke.yml`/`windows-bundle-sdk.yml`（Python 打桌面）/`uv-lockfile-check.yml`/`lockfile-diff.yml`/`case-collision-check.yml`（跨大小写不敏感 FS 的 `README.md` vs `readme.md` 冲突，CI-only 强制点）/`prompt-surface-diff.yml`（提示词面快照 diff）。

**④ 最佳实践**：`banned-api` 点名禁 import + `AST 兜底 + fail-on-empty + self-test` + `lefthook 分栈路由` + `核心 exact-pin/extras 隔离`。**反面教训**：顶层扁平文件海（40+ `hermes_state_*`）+ `ruff.toml` 数百行逐条 enable/注释掉的规则=**积累式债**；58 条 workflow 需要外部 orchestrator+change classifier 才不至于淹没维护者——守卫数量本身会成为负债。

### crewAI-main（★ uv workspace 多包单体 + import 边界 + 供应链/CVE 红线 + 提交规范门）

**① 顶层切分**：`lib/` 六个 workspace 成员（`crewai`/`crewai-core`/`crewai-tools`/`crewai-files`/`cli`/`devtools`），每成员自带 `src/<pkg>/`+`tests/`+`pyproject.toml`；根 `pyproject.toml` 是 workspace hub。

**② 分层是否被工具强制**：ruff **`ban-relative-imports = "all"`**（`pyproject.toml:90-91`）——禁相对导入，强制绝对包路径，结构上把"包边界"变显式；`[tool.ruff.lint.isort]` 定制 `section-order`（`:96-104`）；`mypy strict`（`:120-131`，`disallow_untyped_defs`/`disallow_any_unimported`+pydantic 插件）；`bandit`+`pip-audit` 进 dev deps（`:14,34`）。**仍无 import-linter**，但 `ban-relative-imports=all` 是一个"零成本、覆盖面广"的边界机械强制。

**③ 多语言/构建**：`[tool.uv.workspace] members=["lib/*"]`（`:335-343`）+ `[tool.uv.sources] {workspace=true}` 让成员互相以本地路径解析。供应链：`exclude-newer="3 days"` + 逐包 `exclude-newer-package` + **超长 `override-dependencies` CVE 抬版清单**（`:172-333`，每条注明 GHSA 编号与理由）。提交规范：commitizen `schema_pattern` Conventional Commits（`:156-169`）。

**④ 最佳实践**：uv workspace 拆包 + `ban-relative-imports=all` + `exclude-newer`/CVE override 的供应链红门 + mypy strict。**反面教训**：workspace 根 `override-dependencies` 膨胀到 **150+ 行手工 CVE 注释**——把"上游未修的安全债"全压进一个文件，可读性/维护性极差；`testpaths` 需逐包列举（`:142-148`），新包易漏配。

### autogen-main（★ Python+dotnet+JS 三语言 xlang 单体 + poe 任务分派 + workspace）

**① 顶层切分**：`python/packages/*`（`autogen-core`/`autogen-agentchat`/`autogen-ext`/`autogen-studio`(+`frontend/` TS)/`agbench`/`component-schema-gen` 等 9 个）、`dotnet/`（独立 .NET 栈）、`protos/`（跨语言 protobuf 单一真源）、`samples/`、`docs/`。

**② 分层是否被工具强制**：ruff `banned-api "unittest"→"Use pytest"`（`python/pyproject.toml:77-79`）；**双类型器并跑** `mypy strict` + `pyright typeCheckingMode="strict"`（`:81-103`）；`component-schema-gen` 从代码生成组件 schema（契约产物化）。无 import-linter。

**③ 多语言构建**：`[tool.uv.workspace] members=["packages/*"] exclude=["packages/autogen-magentic-one"]`（`:47-49`）；**poe-the-poet 任务分派器** `run_task_in_pkgs_if_exist.py`（`:110-120`）——一条 `poe check` 遍历所有子包、只跑各包已定义的 fmt/lint/pyright/mypy/test；`gen-proto`（`:130-136`）用 grpc_tools 从 `../protos/` 同时生成 Python+Mypy 桩，供 Python↔.NET 跨语言；CI 按语言/包切分（`checks.yml`/`dotnet-build.yml`/`integration.yml`/`single-python-package.yml`/`lfs-check.yml`）。

**④ 最佳实践**：poe "遍历子包按需分派"的单体任务入口 + protos 单一真源跨语言 codegen + workspace `exclude` 处理遗留包。**反面教训**：0.2 遗留 `pyautogen` 包与新 `autogen-*` 并存 + workspace `exclude` 一个成员=**迁移期双轨**，拓扑长期处于"半搬迁"态。

### CowAgent-master（★ Python+Electron；ruff 只 F 门 + 有意豁免的味道）

**①** 顶层 `agent/`+`bridge/`+`channel/`+`models/`+`common/`+`plugins/`+`voice/`+`desktop/`(Electron)+`docker/`。**②** ruff `select=["E","F","W","B"]` 但**只对 F 判红**（`pyproject.toml:31-44` 注释详述"E/W/B 供编辑器反馈但故意不致命"）；`ignore=["F403","F405"]` 放行**有意的 star-import 跨 channel 再导出**；`per-file-ignores` 给 try/except ImportError 探针让路（`:46-51`）。`extend-exclude=["desktop","docs"]`（`:24-29`）——TS 桌面不在 python lint 面。**③** `pyproject` 只 `include=["cli*"]` 打包，桌面另有 `desktop/package.json`。**④ 最佳实践**：CI 门"只卡真缺陷(F)、把风格(E/W/B)降级为建议"是务实的 lint 分级。**反面教训**：`bridge/` 把契约 DTO 与装配混一层（`00-layering.md:15` 已点名"我们引以为戒"）；靠 `ignore F403/F405` 迁就散落的 star-import 再导出=**边界靠豁免维持而非靠设计**。

### MetaGPT-main / OpenManus-main / Agent-S-main（★ 只有风格守卫、零架构守卫）

- **MetaGPT**：单包 `metagpt/`；`ruff.toml:1` 仅 `select=["E","F"]`；`.pre-commit-config.yaml` 只有 isort/black/ruff——**无任何分层/边界守卫**。反面教训：`metagpt/environment/minecraft/...` 里塞了 node.js `package.json`/`tsconfig.json`（跨语言代码嵌进 Python 包树深处，污染包结构）。
- **OpenManus**：`app/` 扁平单包 + 根 `run_*.py`；`.pre-commit` 只有 black/autoflake/isort（`check-added-large-files` 是唯一"守卫"），`requirements.txt` 无锁——零分层强制。
- **Agent-S**：`gui_agents/` 一个包；`lint.yml` 仅 `black --check gui_agents`、`on push/PR` 用 `paths:` 限定到 `gui_agents/**`+`tests/**`（这是**唯一可取之处**：按路径触发）——守卫=格式化检查。

### cordis-main / EvoFlow-main / GenericAgent-main（★ TS 单体 / Makefile 编排 / 应用式扁平）

- **cordis**：纯 TS monorepo `packages/*`（`core`/`hmr`/`loader`/`include`/`service`…），`package.json`+每包 `tsconfig.json`，yarn berry + vitest + nyc；`.eslintrc.yml` **仅 `extends: '@cordisjs/eslint-config'`**（共享风格配置，**无 eslint boundary/import 分区插件**）。取：TS 多包用"每包独立 tsconfig + 顶层 extends 共享 eslint"；反：**TS 侧没有任何跨包 import 边界强制**。
- **EvoFlow**：`backend/`（uv，`packages/harness/evoflow/**`，`ruff.toml known-first-party=["evoflow","app"]` `:22`）+ `evopanel/`（tauri：`src-tauri`+`src`+`pnpm-workspace.yaml`+flat `eslint.config.mjs`）。根 `Makefile:60-64` = 跨语言总入口（`cd backend && uv sync` + `cd evopanel && pnpm install`），`:44-47` `ci-local`/`setup-git-hooks`（"同 GitHub Actions 的本地一键 + pre-commit quick"）。取：**Makefile 当跨语言开发/CI 统一 façade**（`make ci-local` 本地=CI）；反：`evopanel/eslint.config.mjs` 有 react-hooks 但**无 boundaries 插件**、`ruff.toml:9-19` 一堆 `E501` 逐文件豁免（长行治理靠豁免）。
- **GenericAgent**：`pyproject.toml:46-48` 只 `packages=["ga_cli"]`，**核心 agent 代码是根级散装 `.py`（agentmain.py/llmcore.py…）不打包**；多前端 `frontends/desktop`(tauri)+`ga_cli`+bot extras（`:22-40` 按需选 extras）。取：extras 按 UI/bot 切分、"do NOT install all"（`:1-2` AI 安装提示）；反：**应用核心不可 pip 安装、不可作为包树被 import-lint**——"没有包边界可谈"的极端。

---

## ③ 对 STRUCTURE 的具体改法（取优表，仅增量/更优，标 `[P1]`/`[加固]`）

> 原则不变：STRUCTURE 是参考，落点是**目录拓扑/工具/守卫**，不新增硬命名。以下每条给"改哪节 + 抄谁家 + 证据"。

**G-1 §1/§4 把"分层强制"从单一 import-linter 升级为三道防线 `[P1]`**
- STRUCTURE §1 已列 `.importlinter`、S3 说"由 import-linter 强制"。本扫描证据：**12 家零采用 import-linter**，且 C1 局限已承认静态 lint 拦不住动态 import。建议 §4 CI 门禁把分层强制写成**三道**：① **声明式** `.importlinter` 契约（保留，作为"分层意图"的人读规格）；② **ruff `flake8-tidy-imports.banned-api`** 点名禁"kernel 直接 import policy/surfaces/providers 具体实现"、禁"上层 import 某底层实现类"（照 hermes `ruff.toml:460-466` 的 msg 指路写法，每条禁import附一句"改走哪个 Port"）；③ **自研 AST 兜底检查器** 扫 `git ls-files` 追踪的生产 `.py`、命中打 `path:line`、**空清单/解析失败一律 exit≠0**、且脚本自带 `--self-test`（照 hermes `check_lazy_deps_imports.py` + wuu `check-test-policy.mjs`）。**关键增量**：`fail-on-empty` 与 `self-test` 是"守卫可信"的根，STRUCTURE 现无此口径。
- 附带零成本项：`ban-relative-imports="all"`（照 crewAI `:90-91`）强制绝对包路径，让"跨层 import"在 diff 里一眼可见。

**G-2 §3 桌面新增"sidecar 独立锁 + 冻结 + 打进 bundle"三段式 `[P1]`**
STRUCTURE §3 现在只说"把 Python 后端作为 sidecar 子进程拉起"。补具体构建链（照 DeepCode）：`desktop/sidecar-requirements.in/.lock`（**比根 pyproject 更窄**的打包运行时，注释写明"narrower than dev"）→ PyInstaller 冻结 → `tauri.conf.json` `bundle.resources` 把冻结产物映射进包（`tauri.conf.json:33-37`）→ 发布前 `verify-release-bundle.py` 校验 sidecar 真在包内且起得来。§5 命名约定可加一句"打包面 vs 开发面依赖分两份锁"。

**G-3 §3/§2 之间新增"跨语言契约单一真源" `[P1]`（呼应 C6 快照 diff）**
STRUCTURE 有 Python 内 `contracts/`（L0），但 **S5 进程边界外**（Python↔Rust↔TS）的事件协议缺一个语言中立承载。补：顶层 `protocol/*.schema.json`（或 `contracts/` 旁一个 `wire/` 子目录）= 外部事件投影的**唯一 JSON Schema**；构建期 `generate-protocol` 从它生成 TS 类型、`check:protocol --check` 进 CI 阻断漂移（照 DeepCode `protocol/app-server.schema.json` + `desktop/package.json:16-17`）。这把 C6"外部事件契约快照测试/CI diff"从抽象落到具体工件。

**G-4 §4 CI 门禁细化为"分道 + 改动分类 + 错峰" `[P1 分道/分类]` `[加固 错峰]`**
- **按语言分道**：`python-ci.yml` / `desktop-ci.yml`(Rust+web) / `security-ci.yml`——各自独立，改 python 不触发桌面全量（照 DeepCode 四道）。
- **改动分类器**：抽 `.github/actions/ci-scope` 产出 `runtime_changed`/`desktop_changed`/`contracts_changed`，无关 job 整条 skip（`python-ci.yml:34-36`）。questor 的"契约快照 diff"正可挂 `contracts_changed`。
- **解释器矩阵降配**：`main` push 只跑主 Python、PR 跑全矩阵（`python-ci.yml:26`）；重型 per-OS bundle 仅 schedule/dispatch（`desktop-ci.yml:141-150`）。
- **冷导入 + 分层守卫 无条件跑**：照 hermes"不 fold 进语言 lane、因语言 lane 会被 change classifier 门控掉"（`lazy-deps-guard.yml:11-13`），把 C1/分层守卫放成**不依赖分类器的独立 blocking job**。

**G-5 §5 工具链钉死 + 供应链红线 `[P1 钉工具链]` `[加固 供应链]`**
- §1 依赖清单补**钉死工具链的文件**：`.python-version`(已列) + `.node-version` + `rust-toolchain.toml`（照 wuu/DeepCode）；各语言各留 lockfile（`uv.lock`/`pnpm`或`npm` lock/`Cargo.lock`）。
- `[加固]` 供应链：核心直接依赖 **exact-pin**、可插拔/provider-specific 走 extras 懒装（hermes `pyproject:20-39` 的小爆炸半径理由）；`[tool.uv] exclude-newer` + `pip-audit`/osv-scanner（crewAI `:172-333`、hermes `osv-scanner.yml`）进 security lane。

**G-6 §5 提交/PR 规范门（低成本高价值）`[加固]`**
crewAI 用 commitizen `schema_pattern` Conventional Commits（`:156-169`）+ CI `pr-title.yml`/`pr-size.yml`。questor 若要"变更走 ADR/评审"有抓手，可加一条 **PR-title 规范 + commit-message 规范** 的轻量门（`[加固]`，v1 可先只做本地 lefthook/commit hook）。

**G-7 §7 S3/S4 落地补注：守卫脚本自身要红绿自证 `[P1]`**
S3 现说"由 import-linter 强制（非口头约定）"。补一句 S8：**每条机械守卫（分层/契约快照/import 禁令）必须附带一个 `--self-test`（或 fixture 测试）证明它在'有违规时确实判红、无违规时确实判绿、扫不到文件时确实报错'**——否则守卫会"静默通过"（passive rule that cannot enforce a policy，hermes `case-collision-check.yml:14-17` 的教训）。

**G-8 反面清单（STRUCTURE 应显式避开的形态）**
- 别学 hermes 把状态模块散在根目录成"扁平文件海"——questor 已定 `src/questor/state/` 按层切包，**保持 src-layout，勿回退 flat**。
- 别学 GenericAgent"核心不打包"——`src/questor/` 必须是可安装、可被 import-linter/lint 遍历的包树。
- 别靠"整目录 `= ["ALL"]` / `ignore F403/F405`"维持边界（DeepCode vendored、CowAgent star-import）——questor 的再导出应经 `contracts/` 显式 Port，不用 star-import 蒙混。

---

## ④ 失败模式（参考实现踩过的坑，STRUCTURE/守卫应显式防）

- **F1 守卫"静默通过"**：检查器扫不到文件就当通过（扫空=绿）、或被语言 lane 的 change classifier 意外门控掉 → 红线形同虚设。hermes 用 **fail-on-empty + 无条件独立 job** 防（`check_lazy_deps_imports.py:73-78`、`lazy-deps-guard.yml:11-19`）。
- **F2 静态 lint 拦不住动态 import**：ruff/import-linter 只看字面 import；`importlib`/`__import__`/字符串装配绕过。C1 局限已述——故要"包/模块边界为主、lint 兜底"，光加 import-linter 不够。
- **F3 sidecar 依赖与 dev 混一份**：把 CLI/dev 工具链一起打进桌面 → 包体积膨胀 + 不可复现 + 继承本地依赖（DeepCode 专门开 `sidecar-requirements.in` 且注释"narrower"来防，`:1-3`）。
- **F4 跨语言契约漂移**：事件协议在 Python/Rust/TS 三处各写各的 → 字段悄悄不一致。解法=单一 schema + codegen + `--check`（DeepCode `check:protocol`），否则"改了不牵全身"名存实亡。
- **F5 大小写不敏感 FS 炸克隆**：`Foo.py` vs `foo.py` 在 Linux CI 没事、Windows/macOS 克隆互相覆盖（questor 桌面=Windows，风险更高）。解法=CI `case-collision-check`（hermes）。
- **F6 跨平台工具链漂移**：不钉 `.node-version`/`rust-toolchain.toml`/`go-version-file` → 本地与 CI 版本分叉。各家普遍用文件钉死。
- **F7 vendored/整目录豁免变审计盲区**：`= ["ALL"]` 关掉一片（DeepCode vendored skills）、workspace `exclude` 掉一个成员（autogen）→ 那片彻底无人看。questor `capabilities/` 若塞第三方 SDK 需警惕。
- **F8 供应链经范围版本被投毒**：`pkg>=x` 允许 PyPI 随时投新版本（hermes 记 Mini Shai-Hulud 事件，`pyproject:22-28`）→ 桌面端把恶意版本打进每个用户机。解法=核心 exact-pin + `exclude-newer` + audit。
- **F9 守卫数量本身成负债**：58 条 workflow（hermes）需外部 orchestrator+分类器才不淹没；questor P1 阶段**别一次性铺开全 CI 矩阵**，先铺"分层守卫+冷导入+单测"三条 blocking，其余按里程碑加。

---

## ⑤ 文档缺口（STRUCTURE 及关联文档需补/需对齐处）

- **D1 §4 分层强制口径单薄**：只写"import-linter 分层守卫"，缺 G-1 的"三道防线 + fail-on-empty + self-test + ban-relative-imports"。STRUCTURE 现把 import-linter 当唯一硬手段，而本参考集零采用——需重定为"意图规格"，把实际硬门交给 ruff banned-api + AST 检查器。
- **D2 无"跨语言 wire 契约"落点**：`contracts/` 只覆盖 Python 进程内 L0；S5 进程边界（Python↔Rust↔TS）的事件协议缺一个 `protocol/*.schema.json` 单一真源 + codegen + drift-check（G-3）。与 C6、`02-event-protocol.md` 交叉引用缺失。
- **D3 §3 sidecar 构建链留白**：只说"作为子进程拉起"，未写"独立锁→PyInstaller/冻结→bundle.resources 打进安装包→发布校验"（G-2）。ROADMAP 桌面里程碑需据此排活。
- **D4 §4 无 CI 分道/改动分类/错峰模型**：现把门禁写成一条流水，缺"按语言分道 + ci-scope 跳过无关 + 重 bundle 错峰 + 分层守卫无条件独立 job"（G-4）。
- **D5 工具链钉死不全**：§1 有 uv/`.python-version`，缺 `.node-version`/`rust-toolchain.toml`/各语言 lockfile 齐备（G-5）。
- **D6 无供应链/依赖分层守卫**：exact-pin vs extras、`exclude-newer`、pip-audit/osv 均未提（G-5 `[加固]`）；对 BYOM/桌面分发是实打实风险。
- **D7 §7 S 系列缺"守卫自证"条**：S1–S7 讲了各接缝约束，但没讲"每条机械守卫须附 `--self-test`/fixture 证其能判红"（G-7）——这是 F1 的根防线，建议新增 S8。
- **D8 提交/PR 规范门未定归属**：若采纳 G-6，需在 ROADMAP 指定里程碑（建议 P1 先本地 commit-hook、`pr-title`/`pr-size` 后铺），避免与"变更走 ADR"口径悬空。
- **D9 命名↔打包张力未点破**：`GenericAgent` 核心不打包、`MetaGPT` 把 node 代码埋进 Python 包树、`wuu` 70 子包扁平无二级——是"结构服务分层"的三条反例，STRUCTURE §8 可引为"别照抄这些"的注脚（G-8），但现文档未列。

---

### 采纳优先级建议
- **进 v1（STRUCTURE 收口前就改）**：G-1（三道分层防线 + fail-on-empty + self-test）、G-2（sidecar 三段式）、G-3（wire 契约单一真源）、G-4（分道+改动分类，分层守卫独立 job）、G-5 工具链钉死部分、G-7/新增 S8。对应缺口 D1–D5、D7。
- **加固期（里程碑后补）**：G-4 重 bundle 错峰、G-5 供应链（exact-pin/extras/audit）、G-6 提交规范门、`case-collision-check`。对应缺口 D6、D8。
- 触及 wire 契约（G-3/D2）与分层强制（G-1/D1）两条建议同步在 `HARD-CONSTRAINTS.md` C1/C6/C14 各加一行"实际强制工件"引用；触及 sidecar 构建链（G-2/D3）建议在 ROADMAP 桌面里程碑补一句落点。
- 本文件仅提增量与更优，未改 STRUCTURE 原文，也未推翻其结论；是否回写待评审采纳。
