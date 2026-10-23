# 计划 01：结构加固（面向千文件规模）

- 状态：Active
- 日期：2026-10-23
- 基线：`b8632fd`（分支 `refactor/phase1-move-only`）上的快照；**2026-10-23 该分支已作为 PR #217 合入 `main`（merge `8d9f9ae`）**，执行窗口一律从 `main` 开分支，基线以 W0 复测值为准
- 来源：仓外 `optimize-scan/QUESTOR-STRUCTURE-OPTIMIZATION-PLAN.md`（取证与同规模对照）+ `optimize-scan/DOCS-MANIFEST.md`（pin 与口径纪律）。本文件是**执行版**：只写"按什么顺序动、每刀怎么算完成、哪些症状出现就停"。
- **本文是唯一执行计划**。仓外 `optimize-scan/QUESTOR-STRUCTURE-OPTIMIZATION-PLAN.md` 是取证与论证（母文档），不作为执行依据；`DOCS-MANIFEST.md` 是交付清单；窗口提示词只是启动指令。四者冲突时以本文为准。
- 口径：行数一律 python `splitlines()`；目录扇出一律"非 `__init__` 源文件数"。任何"实测"必须注明 commit。
- **排版约定**：反引号包住的路径 = **现已存在**（由 `check_doc_cross_refs` 校验）；**加粗路径** = 本计划待创建，当前不存在。前者写错即 CI 红，后者不得回写成反引号。

---

## 0. 怎么用这份文档

1. 开工前重跑 §1 的基线采集脚本，与表中数字比对；**任一不符先停**，说明 HEAD 已漂移。
2. 按 §2 的顺序逐刀推进，一刀一分支一 PR；**上一刀的 D 类验收（验红）没过，不许开下一刀**。
3. 每刀结束把"实测值"回填到 §5 总验收表，并注明 commit。
4. 出现 §6 任一症状，视为**门本身有缺陷**，先修门再继续，禁止"先加豁免绕过"。

---

## 1. 基线（`b8632fd` 快照；`main` 已前进到 `8d9f9ae`，开工以复测为准）

| # | 指标 | 值 | 采集方式 |
|---|---|---|---|
| B1 | src `.py` / 非 `__init__` 模块 | 319 / 256 | `git ls-files src | grep '\.py$'`（`git ls-files 'src/**/*.py'` 只得 318，漏顶层 `src/__init__.py`） |
| B2 | tests `.py` | 139（unit 94 / integration 31 / e2e 11） | `git ls-files 'tests/**/*.py'` |
| B3 | 含 `def`/`class` 的 `__init__.py` | 14 | 正则扫 `^\s*(def\|class) ` |
| B4 | 导出 >10 的包 | 8（最大 `runtime/swarm` 23） | 解析 `__all__` |
| B5 | **顶层包无 `__all__`** | **8**：`contracts`/`capabilities`/`runtime`/`providers`/`bootstrap`/`surfaces`/`execution`/`platform` | `grep __all__` |
| B6 | 禁用名文件（`base/manager/service/types/constants/helpers`） | 22 | 文件名匹配 |
| B7 | 1001–1500 行 / >1500 行 | **4** / 0（max `cli.py` 1187）；801–1000 行另有 4 个，属健康带（阈值已从 801–1200/1200 放宽到 1001–1500/1500） | 行数统计 |
| B8 | 包级依赖环 | 2（`engine↔runtime` 已登记 1 条反向边；`capabilities↔plugins` 无契约覆盖） | `lint-imports` + 人工 |
| B9 | 新增工具共享文件半径 | 5（`registry.py` ×2 处 / `compact/constants.py` / `capabilities/context/coordinator.py` / `permission_sync.py` / `engine/tool_metadata.py` 的 `elif` 链） | 见 W5 |
| B10 | `mypy src` | 1453 errors / 251 files，21.1s，**未进任何门禁** | `uv run mypy src` |
| B11 | pytest 收集 | 1177 用例 / 3.83s | `uv run pytest --collect-only -q` |
| B12 | 同名测试镜像率 | 33.6%（86/256） | 路径比对 |
| B13 | 守卫脚本 / CI 实际执行 | 5 个脚本；CI 只跑 3 个（`thread_leak`/`secret_projection`/`doc_cross_refs`）的 `--self-test` + `--fail-on-empty`；**`check_layout`/`gen_tree` 在 `.github/workflows/` 零命中** | `grep -r` |
| B14 | `docs-pre-reset-v1` tracked | 110 | `git ls-files` |
| B15 | 根 `AGENTS.md` | 118 行 / 8646 字节，**全是行为守则，零结构表** | wc |
| B16 | 包级 `AGENTS.md` | 9 份，3–10 物理行 / 893–1496 字节 | wc |
| B17 | `capabilities` 体量 | 103 文件（占 32.3%）；内部 6 个一级子域 / **16 个二级目录**（≥2 个非 `__init__` 源文件）；`tools` 53 文件 / 8 族 | 目录统计 |

**基线落盘**：把 B1–B17 写进 **tests/fixtures/structure_baseline.json**（机器可读），后续每刀只读不写；刷新需显式 `--refresh-baseline` 并在 PR 描述说明原因。

---

## 2. 波次与依赖（不可颠倒）

```text
W0 基线落盘 ──► W1 守卫进 CI ──► W2 尺寸/命名/地图门 ──► W3 快照门
                                      │                    │
                                      ▼                    ▼
                                  W4 类型门 ──────────► W5 共享点收口
                                                           │
                              W6 依赖收紧 ◄────────────────┘
                                      │
                                      ▼
                                  W7 文档三层 ──► W8 门面与尺寸 ──► W9 命名销账 ──► W10 归位清理
                                                                                    │
                                                                                    ▼
                                                                              W11 规模补丁（可选，600 文件前）
```

硬顺序理由（违反会返工）：

1. **W1 必须先于 W2–W10**：门不进 CI，后面所有"销账"都会反弹。
2. **W2 必须先于 W5/W8/W9**：没有尺寸门，拆完立刻长出新的巨石。
3. **W6 必须先于 W8**：拆门面时若还留着 `capabilities↔plugins` 环，环会被拆进新文件。
4. **W4 在 W5 之前**：共享点收口要动 4 个消费方的类型，先有 mypy 才能证明"行为没变"。
5. **W7 在 W8 之前**：包级文档的"公开入口"是 W8 收口 `__all__` 的判据来源。

---

## 3. 每刀的验收模板（DoD 五问 + 四类判据）

任何一刀，PR 描述里必须逐条回答这五问；答不上来即未完成：

1. **能判红吗？** 我构造的违规，守卫真的红了吗（附命令与输出）。
2. **空扫描会通过吗？** `--fail-on-empty` 打开时，扫到 0 个文件必须失败。
3. **规则比规格宽吗？** 实现逐条对照规格（如 R4 必须同时查"行数"和"含 def/class"）。
4. **存量豁免有出口吗？** 每条豁免带规则号 + 删除条件，且条件非空。
5. **本地绿 = 远端绿吗？** CI 与本地同一 `uv` 锁、同一命令、同一工作目录假设。

四类判据（缺一不可）：

- **A 机器判据**：命令 + 期望输出（必须全绿）。
- **B 验红判据**：故意构造违规 → 必须红；恢复 → 必须绿。
- **C 症状判据**：§6 的失败模式逐条核对，出现即停。
- **D 回滚判据**：一行命令回到上一状态，且回滚后基线五项不变。

---

## 4. 执行波次

### 4.0 开工前口径裁定（2026-10-23，四处计划与代码不符，按此执行，不再讨论）

| # | 计划原文 | 实测 | 裁定 | 台账必记 |
|---|---|---|---|---|
| D1 | W6「去掉 `capabilities-are-leaf` 的 `allow_indirect_imports`」 | `capabilities → execution.shell → providers.sandbox` **真实存在**：`capabilities/schedule/cron_scheduler.py`、`capabilities/tools/remote_trigger_tool.py` → `execution/shell.py:14` → `providers.sandbox`。去掉间接豁免必然红，修它要动 execution 链 | **保留 `allow_indirect_imports=True`**；把 `plugins`/`engine`/`commands`/`surfaces` 加进 forbidden（直接边即红）；**新增冻结**：`capabilities → execution` 的边集合必须逐字等于登记集（**5 条**，见 §4.1 R1），`execution → providers` 的**模块集合**等于 {`sandbox`, `sandbox.session`}；新增即红 | 「间接路径经 execution→providers 仍在；入口已冻结为 5 条边 + 2 个模块；Phase 3 把 sandbox 抽成 Port 后关闭」 |
| D2 | W6 验收「`lint-imports` ≥12 契约全 KEPT」 | 现状 9 条，本刀只授权新增 1 条 → **10** | 判据改为「现有 9 条全 KEPT + 新增 1 条 KEPT = **10**」；**不为凑数加契约**——`engine→bootstrap` / `runtime→bootstrap` 已被 `layers` 覆盖（bootstrap 是顶层，向上 import 本就违约），加它们是 S-10 的恒真契约 | 「计划 ≥12 / 实测 10 / 缺口 2 条属计划口径错误，非实现缺口」 |
| D3 | W1 直接把 `baseline_check --check` 加进 CI | **该检查在 main 上已红**：`dryrun.txt` 的 `system prompt chars: 19008 → 18987`；根因 `system_prompt.py` 内嵌 cwd / date / python 路径 | **W1 先加归一化再进 CI**：`_normalize` 将 `- system prompt chars: \d+` 替换为占位；受控 `--record`；审计 `git diff tests/fixtures/baseline/` **只允许 `dryrun.txt` 变化**，`summary.json` / `main_node_ids.txt` 变则回滚 | 「该数字不再作为门；prompt 体积信号移交 W3 的 prompt-surface 快照（固定渲染输入）」 |
| D4 | W5「`permission_tier` 复用 `contracts/policy.py` 既有枚举」；R9「模型可见面可枚举」无规则正文 | `policy.py` 只有 `PermissionMode`（DEFAULT/PLAN/FULL_AUTO，会话模式），无 tier；ADR-0003 §8 无 R9（R8/R9 本就由本计划新增） | (a) **不新增枚举**：`BaseTool` 加**唯一必填声明** `capabilities: ClassVar[ToolCapabilities]`（frozen dataclass：`read_only_by_default` / `keep_in_compaction` / `artifact_keys` / `remember_as`），`permission_sync` 改读 `capability_index().read_only_tools`；(b) **R9 定义为**「每个 `input_model.model_json_schema()` 的属性必须带 `type`/`$ref`/`anyOf`/`enum`/`const`，裸 `{}` 即红；扫到 0 个工具即红」，实现载体是 **tests/ci/test_tool_schemas.py**，**不进 `check_layout`**；「每个工具都能被渲染」归 W3 | 「未能复用 PermissionMode，改用类级布尔声明；R9 规格由本计划定义，落地后补进 ADR-0003 §8」 |

**执行纪律**：以上四条写入同一份偏差台账（`## 10. 偏差台账`），一行一条；**不得自行扩大改动面**（例如为此把 sandbox 抽 Port、或新增两条凑数契约）。

### 4.1 回测修订（2026-10-23 第二轮，10 项，全部已核实）

| # | 回测发现 | 实测 | 处置（已写入正文） |
|---|---|---|---|
| R1 | D1 冻结集「2 条」错 | `capabilities→execution` 实为 **5 条**（另有 `tools/shell/bash_tool.py`、`tools/web/web_fetch_tool.py`、`tools/web/web_search_tool.py`）；`execution→providers` 是 **3 处语句 / 2 个模块**（`sandbox`、`sandbox.session`） | 登记 5 条 file→module 边；execution→providers 按**模块集合**冻结，不按语句数 |
| R2 | `--record --fast` 不存在 | `baseline_check.py:360` 明写 `--fast cannot be combined with --record` | 只用 `--record`；审计三件：`dryrun.txt` **必须变**，`summary.json`/`main_node_ids.txt` **必须逐字不变** |
| R3 | 默认值与「不留兜底」互斥 | 有默认值就无法区分「声明为 False」与「未声明」 | 改为**单一必填声明** `capabilities: ToolCapabilities`（字段带默认值）；AST 断言每个子类**类体里必须出现该赋值**；运行期缺失直接抛 |
| R4 | 消费方路径错 | `capabilities/context/compact/coordinator.py` 不存在；真实文件是 `capabilities/context/coordinator.py` | 全文改正 |
| R5 | 319 口径不自洽 | `git ls-files 'src/**/*.py'` = **318**；`git ls-files src` 过滤 `.py` = **319** | B1 改用后者；`src/__init__.py` 记为顶层标记，不计入 256 |
| R6 | W1 探针 1201 在 W2 后失效 | W2 把 fail 抬到 1500 后，1201 只告警 | 探针改 **1501 行**（两刀都红） |
| R7 | W6 C 表仍写「逐条关闭间接豁免」 | 与 D1 冲突 | 改为「冻结入口集，多一条即红；Phase 3 抽 Port 后关闭」 |
| R8 | W3 缺固定渲染输入 | `_child_env` 只 unset 凭据；`is_coordinator_mode()` 读 `CLAUDE_CODE_COORDINATOR_MODE`（`capabilities/context/coordinator.py:34`）会切换 prompt 分支 | W3 增：构造注入固定 `EnvironmentInfo`（全字段定值）+ `get_platform` 打桩 + unset `CLAUDE_CODE_COORDINATOR_MODE` |
| R9 | 契约名与 body 不符 | 名称声称「只有装配可 import」，实际 engine/runtime/commands/plugins/cli/api 都 import | 改名 `lower-layers-do-not-import-capabilities`，body 禁 6 个下层包（实测均 0 边） |
| R10 | 暂缓池无粒度 | 模块级 293 条 vs 包级 15 条 | 用**包级计数**：每包记录当前 non-init 模块数，上涨即红 |

**核对通过、不再改动**：白名单 22 模块 / 26 文件；`py.typed` 可消 18 个 `import-untyped`；R9 起点 42 工具 0 裸属性；`plugins` 新增 4 条 forbidden 不误红；R10 量级（事件 7 + 通道 2 + 工具 43 + config key 33）可控。

### W0 基线落盘（0.5 天 · 不碰业务代码）

**目标**：把 §1 的 17 个数字变成机器可读、可 diff 的文件，后续所有判定以它为准。

**改动**
- 新增 **tests/fixtures/baseline/structure.json**（与既有 `baseline_check.py` 的快照同目录，不另建目录）
- 新增 **scripts/guards/gen_structure_baseline.py**（`--write` / `--check` / `--refresh-baseline`；名字带 `structure_` 是为了不跟 `scripts/baseline_check.py` 撞车）
- `.gitignore` 增 `.tmp-baseline/`（`scratch/` 已在第 149 行，勿重复）

**验收**
- A：`uv run python scripts/guards/gen_structure_baseline.py --check` exit 0；`structure.json` 的 17 个键与 §1 表逐项相等。
- B：手工把 json 里 `src_files` 改成 320 → `--check` 必须 exit 1 并打印 `expected 319, got 320`。
- C：见下表。
- D：回滚 = 删三个文件 + `git checkout .gitignore`。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| 数字口径与文档不一致 | 文档 1187 行 / 实测 1183 | json 里带 `caliber` 字段并注明命令 | 统一 python `splitlines()`，把采集命令写进 json 注释字段 |
| 基线被悄悄刷新 | 每次 CI 都"绿"，但指标在退化 | `--refresh-baseline` 不出现在任何 CI/pre-commit 配置里 | 该 flag 只允许手动，且 PR 必须带说明 |
| 采集扫到工作区临时文件 | 数字随执行环境漂移 | 采集一律走 `git ls-files`，不 walk 目录 | `--fail-on-empty` 同款：清单为空即失败 |

---

### W1 守卫进 CI（R0）（1 天 · 风险为零，先做）

**目标**：让"已写下的规则"真的在流水线上跑，而不是只在本机 pre-commit。

**改动**
- **先修 `baseline_check` 的跨机器不稳定（D3）**：`_normalize` 把 `- system prompt chars: \d+` 归一化为占位；**只能 `--record`（`--fast` 与之互斥，见 R2）**；审计三件：`dryrun.txt` **必须变**，`summary.json` / `main_node_ids.txt` **必须逐字不变**（变则回滚并排查）
- `.github/workflows/ci.yml` 的 `guards` job 增：`check_layout.py --fail-on-empty`、`gen_tree.py --check`、`gen_structure_baseline.py --check`、`baseline_check.py --check --fast`（最后这条目前只在 pre-push）
- 新增 **scripts/check.py**：一个入口跑完全部 blocking（按固定顺序，带耗时汇总）
- `.pre-commit-config.yaml` 的 `layout` / `tree-map` 改为调用 `scripts/check.py --fast`（避免两处分叉）

**验收**
- A：CI 上 `guards` job 的 step 列表包含上述四条实体命令（不是 `--self-test`）；**scripts/check.py** 本地 exit 0。
- A2：`baseline_check --check --fast` **改动前先贴一次红**（证明问题真实），归一化 + `--record` 后 exit 0；`git diff --stat tests/fixtures/baseline/` 只有 `dryrun.txt`，另两件必须逐字不变。
- B：在临时分支制造 **src/questorharness/engine/_w1_probe.py**（**1501 行**；W2 把 fail 抬到 1500 后仍红，见 R6）→ **远端 CI 必须红**，且红在 `guards` job 而非 `tests` job；删文件后恢复绿。
- B2：把 `check_layout` 的扫描范围临时改成空 → `--fail-on-empty` 必须红。
- C：见下表。
- D：回滚 = revert workflow 与 **scripts/check.py**；基线五项不变。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| **只把 `--self-test` 当成"进了 CI"** | CI 绿，但违规代码照样合入 | grep CI 配置里是否有 `check_layout.py --fail-on-empty` 实体调用 | 本刀 B 判据就是专门抓这个 |
| 两处配置分叉 | pre-commit 绿、CI 红（或反之） | 两者必须调用同一个 **scripts/check.py** | 单一入口，禁止各写各的命令 |
| guards job 超时 | PR 卡 10 分钟 | 整个 job ≤90s（B11 基线 3.8s，余量足够） | 超时即拆分或加缓存，不许挪回 pre-commit |
| Windows/Ubuntu 行为差异 | 本地绿远端红 | 路径一律 `pathlib` + 正斜杠比较；不用 `os.sep` 拼路径 | 加 `check_case_collision` 兜底（W2） |

---

### W2 尺寸/命名/命名空间/门面/导出/地图门（R1–R10）（3–4 天）

**目标**：把 ADR-0003 §8 的规格从"2 条"补到"9 条"，并新增第 10 条（命名空间唯一性）；存量靠就地注释，新增一律红。

**改动**
- `scripts/guards/check_layout.py`：实现 **R1–R8**（R1 目录扇出三级、R2 行数、R3 禁用名、R4 门面、R5 导出、R6 地图、R7 测试镜像、R8 函数级棘轮）——**纯静态扫描**
- **R9（schema 有效性）走契约测试**：新增 **tests/ci/test_tool_schemas.py**——每个 `BaseTool.input_model.model_json_schema()` 的属性必须带 `type`/`$ref`/`anyOf`/`enum`/`const`，裸 `{}` 即红；扫到 0 个工具即红（D4；规格由本计划定义，落地后补进 ADR-0003 §8）
- **新增 scripts/guards/check_name_registries.py（R10）**：读 docs/architecture/NAMESPACES.md，三条断言——
  1. 同一命名空间内名字唯一（tool / command / event / config key / env / entry point / skill id 七类，大小写不敏感）；
  2. 每行登记的"生产者"与"消费者"路径必须真实存在（防登记表说谎）；
  3. 代码里出现的每个事件类型（AST 扫 `@dataclass`）与每个 `BaseTool.name` **必须被登记**（漏登记即红）。
- **新增 scripts/guards/gen_namespaces.py + docs/architecture/NAMESPACES.md**：生成器出骨架（AST 扫事件、`Settings.model_fields` 反射 config key、`pyproject` entry point、工具注册表），人只补两列。首版**全量登记，不设豁免**（登记是文档行，不是代码债）。
- 豁免语法：`# questor: allow <RULE> -- <删除条件>`，由守卫解析；**无 `--` 后条件的注释不构成豁免**；`# noqa` 与裸 `# type: ignore` 不构成豁免
- 存量就地注释：R2 **4** 处（1001–1500 行）、R3 22 处、R4 14 处、R5 16 处（8 个无 `__all__` 的顶层包 + 8 个导出 >10 的包）、R7 170 个缺口
- 新增 **tests/ci/test_guards_contract.py**：每条规则构造一个违规仓库，断言判红；再构造一个合规仓库，断言判绿

**验收**
- A：`uv run python scripts/guards/check_layout.py --fail-on-empty` 在真仓 exit 0；`check_layout --self-test` **8 条**全过；`check_name_registries --self-test` 3 条全过且登记缺口 = 0；`pytest tests/ci/test_tool_schemas.py tests/ci/test_guards_contract.py` 全绿且**每条规则至少 2 个用例（红/绿）**。
- B（逐条验红，必须贴输出）：
  - R1：临时造 31 个 `.py` 的目录 → 红；17–30 → 只告警不红。
  - R4：在 `__init__.py` 里加 `def _x():` → 红（证明不只看行数）。
  - R5：删掉某包 `__all__` 且该包不在清单 → 红；`contracts` 允许 15。
  - R7：新增 **src/<包>/foo.py** 但无 `tests/**/test_foo.py` → 红。
  - R8：新增一个 CC 21 的函数 → 红；把已超函数拆小 → 绿且违例数下降。
  - **R9**：把某个工具的 `input_model` 字段改成裸 `{}`（或 `Field()` 无类型）→ `test_tool_schemas` 红；扫到 0 个工具 → 红。
  - R10：① 复制一个已有事件类型成同名 → 红；② 把某行的消费者改成不存在的路径 → 红；③ 新增一个 `BaseTool` 子类但不登记 → 红；④ 同一个 config key 出现两次 → 红。
- C：见下表。
- D：回滚 = revert `check_layout.py` / `check_name_registries.py` / `NAMESPACES.md` 并移除新增注释；`lint-imports` 仍 KEPT。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| **豁免爆炸**：一次加 200 条注释让门变绿 | 存量清零但债务翻倍 | 守卫断言"每包豁免数 ≤ 该包当前存量"，且总数只能减 | 豁免必须带波次号（如 `Phase 2 W7`） |
| 豁免无删除条件 | 注释永久生效 | 解析 `--` 之后必须非空且含 `when/until/W\d` | 无条件的注释直接判红 |
| R4 只查行数 | 门面里塞 300 行 `def` 但文件 40 行内 | 判据必须同时检查 `^\s*(async )?(def\|class) ` | W2 B 判据专抓 |
| 扫描用 walk 而非 `git ls-files` | `__pycache__`/`.tmp-baseline` 造成误报 | 守卫入口统一走 `_guard_kit.py` 的 `tracked_files()` | 复用既有 kit，不新写 |
| 空匹配通过 | 守卫扫到 0 个文件 exit 0 | `--fail-on-empty` 必须默认真 | CI 配置里显式带该 flag |
| 行数口径受 CRLF 影响 | Windows 与 Linux 差 1 行 | 统一 `splitlines()`；不按 `\n` 切 | 采集与守卫共用同一工具函数 |
| 告警被当失败 | 开发者嫌烦关掉整条门 | 17–30 段只打印不退出 | 分级：fail / warn 明确写进帮助文本 |
| **登记表变成第二真源** | 手抄清单与代码脱节 | 三条断言互锁：路径必存 + 代码里的名字必登 | 生成器出骨架，人只补两列 |
| 事件类型扫漏（继承/子类/Union） | 漏登记而门是绿的 | 用 AST 遍历 `ClassDef` + `@dataclass`，不用正则；扫到 0 个即红 | 与 `--fail-on-empty` 同款 |
| config key 手抄 | 与 pydantic 模型不一致 | 从 `Settings.model_fields` 反射生成 | 不手写 key 清单 |
| env 前缀泛滥 | 任意变量进登记表 | 只允许 `QUESTORHARNESS_` 前缀 | 前缀外即红 |
| 改名后忘改登记表 | 路径存在但名字对不上 | 反向断言：代码里的名字集合 ⊆ 登记集合 | 改名必须同 PR 改登记表 |

---

### W3 快照门：把既有 `baseline_check` 提进 CI + 补 prompt surface（1 天）

**事实纠正**：仓内**已有** CLI 快照机制——`scripts/baseline_check.py` 维护 `tests/fixtures/baseline/` 下的三份 `--help`、`dryrun.txt`、`doctor.txt`、`summary.json`、`node-id` 清单，自带归一化与 diff，`--record` / `--check` 双档。**但它只在 pre-push，不在 CI。** 所以这一刀不是"从零建 golden"，而是"把已有的门放进流水线"，外加一个真正缺失的 prompt surface。

**目标**：给"唯一改行为的波次"（W5）和未来的模型可见面变更装一个可 diff 的判据。

**改动**
- `.github/workflows/ci.yml`：`baseline_check.py --check --fast` 进 `guards` job（W1 已列，这里补齐验红）
- 新增 **tests/fixtures/baseline/prompt_surface/** + **scripts/ci/prompt_surface.py**（按宿主渲染 system prompt + `tools[]`；宿主至少：CLI、桌面 host、一个 channel、cron）
- 归一化**复用** `baseline_check._normalize` 与 `_child_env`（临时目录 → `<TMP>`、凭据 unset、数据目录指临时），不新写一套
- **固定渲染输入（R8）**：`prompt_surface.py` 构造注入定值 `EnvironmentInfo`（`os_name`/`os_version`/`platform_machine`/`shell`/`cwd`/`home_dir`/`date`/`python_version`/`python_executable`/`virtual_env`/`is_git_repo`/`git_branch`/`hostname` 全定值）、对 `get_platform` 打桩、并 unset `CLAUDE_CODE_COORDINATOR_MODE`（`capabilities/context/coordinator.py:34`，会切换整套 prompt 分支）；**不得仅靠 `_child_env` 兜底**

**验收**
- A：`uv run python scripts/baseline_check.py --check --fast` exit 0；新建的 prompt surface 测试绿。
- B：改 `cli.py` 里一句 `--help` 文案 → `baseline_check --check` 必须红并打印 diff；改回 → 绿。
- B2：改任意一个 `BaseTool.description` → prompt surface 快照必须红。
- C：见下表。
- D：回滚 = revert；不影响运行时代码。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| **重建一套并行机制** | 两套快照各说各话 | 复用 `baseline_check` 与 `_normalize`，**不新建第二套 golden 目录** | 本刀只加 prompt_surface |
| 快照含环境值 | CI 上永远红 | 新快照必须走同一 `_child_env`（凭据 unset、数据目录→临时） | 生成与校验同一环境 |
| `--record` 变成橡皮图章 | 每次 PR 都重录 | CI 只调 `--check`，`--record` 不进任何 CI 配置 | grep 证明 |
| 只记 hash 无法审 | 红了不知道改了什么 | 必须是可 diff 的文本快照 | 快照用文本 |
| 宿主覆盖不全 | 改了桌面协议但快照绿 | 宿主清单写死常量并断言覆盖数 | — |

---

### W4 类型门（mypy strict 白名单）（2 天）

**目标**：让"改名/移动"重新有安全网，且**新代码不能默认掉队**。

**改动**
- 两个分发各放 `py.typed`
- `pyproject.toml`：`[tool.mypy] strict = true` + `files = [...]` 白名单起步 **22 个非 `__init__` 模块**（`contracts/` 13 + `platform/` 5 + `config/` 4，三包共 26 个 `.py`）；开 `pydantic.mypy` 插件
- 新增 **scripts/guards/check_mypy_scope.py**：
  - 白名单条目数只增不减（删除即红）
  - **新增模块必须同 PR 入白名单，或进 `mypy_deferred.json` 暂缓池；暂缓池按包级计数**（每包记当前 non-init 模块数，上涨即红，R10）——不用模块级清单（293 条不可维护）
- CI：`uv run mypy` 走同一锁文件与缓存 key

**三包的已知存量（开工前实测，共 28 错）**：**20 个 `import-untyped`**（包缺 `py.typed` 被当成未类型化：`config` 6 / `contracts` 4 / `platform` 6 / 跨包 import 4）→ 加 `py.typed` 即消；剩下 **8 个真错**：`platform/locking.py` 的 4 个 `fcntl` `attr-defined`（Unix-only，Windows 上 mypy 仍分析）、`platform/frontmatter.py` 缺 `types-PyYAML`、`config/settings_models.py:688` 一个 `assignment`、`platform/session_storage.py:60` 与 `contracts/domain/message.py:77` 两个 `no-any-return`、`message.py:160` 一个 `arg-type`（`list` 不协变）。**W4 的“0 error”不是免费的：20 个靠 `py.typed`，8 个靠 `types-PyYAML` + 4 行平台守卫 + 2 处类型标注**。

**验收**
- A：`uv run mypy` 对白名单内模块 0 error；三包实测 22 个模块 / 26 个文件，可一次做完。
- B：删掉白名单里一个条目 → `check_mypy_scope` 红；新增 **src/questorharness/engine/probe.py** 不入名单也不入暂缓池 → 红；入暂缓池后绿，且池内条目数被记录。
- C：见下表。
- D：回滚 = 移除 mypy step 与 `py.typed`；基线 B10 不变（1453 是"未进门的存量"，不作为门禁）。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| **白名单只增不减但不强制新增** | 覆盖率永远停在 24 | 必须同时有"新模块必须登记"规则 | 本刀 B 判据专抓；两个机制成对存在 |
| mypy 版本漂移 | 同一份代码昨天绿今天红 | 只经 `uv run`，锁文件钉版 | CI 与本地同锁 |
| 增量缓存不一致 | 本地绿、CI 红 | cache key 含 mypy 版本 + 配置 hash | 先关缓存跑通，再开 |
| `pydantic.mypy` 一开错误暴涨 | 一次性 300+ 新错 | 分两步：先开插件到"仅新模块"，再 strict | 不承诺清零，只承诺"白名单内零错" |
| 为过门加 `# type: ignore` | 白名单内"零错"但全是 ignore | 裸 `# type: ignore` 新增即红；只允许 `# type: ignore[code]` 且带 `-- 原因` | 与 W2 豁免语法统一 |

---

### W5 共享点收口（radius 5 → 1）（3–4 天 · 唯一改行为的波次）

**目标**：新增一个工具从"改 5 处"降到"改 1 个文件 + 1 行"。

**改动**
- `capabilities/tools/base.py`：新增 `@dataclass(frozen=True) ToolCapabilities`（字段：`read_only_by_default: bool = False` / `keep_in_compaction: bool = False` / `artifact_keys: frozenset[str] = frozenset()` / `remember_as: str | None = None`），并在 `BaseTool` 上要求**唯一必填声明** `capabilities: ClassVar[ToolCapabilities]`（D4/R3：不新增枚举；`PermissionMode` 仍只表示会话模式）
- `capabilities/tools/registry.py`：增 `capability_index()`（含 `read_only_tools`）派生不可变映射；手工 import 列表 → `discover_builtin_tools()`
- 4 处消费方改为只读派生结果，删除本地名单：`compact/constants.py`、`capabilities/context/coordinator.py`、`swarm/permission_sync.py`（改读 `capability_index().read_only_tools`）、`engine/tool_metadata.py` 的 `elif` 链
- 新增 **scripts/guards/check_tool_radius.py**

**验收**
- A：`check_tool_radius` 绿；新增一个真实工具（如 `web_search` 的变体）后 `git diff --stat` 只涉及 2 个文件（工具自身 + registry 一行）。
- A2：`git grep` 工具名字符串字面量只出现在该工具自身文件与 `registry.py` 列表项；4 处消费方 0 命中。
- B：把某个工具的 `read_only_by_default` 改错 → `check_tool_radius`/权限测试必须红；把工具名写进 `tool_metadata.py` → 红。
- B2（金标）：对同一批工具调用前后各跑一次 metadata 快照，**逐字比对必须相等**；**只读工具集合前后完全相同**（这是"属性来源变更"的唯一安全网）。
- C：见下表。
- D：回滚 = `git revert` 本刀；CLI golden 快照是回滚后的判据。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| **声明默认值取错 / 漏声明** | 工具被误判为只读/可压缩，行为静默变化 | ① AST 断言每个 `BaseTool` 子类**类体里出现 `capabilities` 赋值**（缺即红）；② 运行期 `capability_index()` 遇到无声明者**直接抛**，不兜底；③ 金标：before/after metadata 逐字相等 | 默认值只给字段，不给「整份声明」兜底 |
| discovery 吞掉 import 失败 | 工具静默消失，模型看不到 | `registry` 数量断言（工具数 == 目录内注册数）；冷导入守卫 | 注册失败必须抛，不许 `try/except: pass` |
| 派生索引成为新共享点 | 从"4 份清单"变成"1 个上帝索引" | `capability_index()` 只读、不可变（`MappingProxyType`） | 只暴露查询，不允许注册时回写 |
| 启动变慢 | import 时扫描全目录 | 冷导入耗时进 §5.5 预算 | 目录扫描加缓存或显式清单 + 校验 |
| 测试 patch 失效 | 单测仍绿，但测的是旧路径 | patch 目标计数 before/after 相等 | 见 W8 同款判据 |

---

### W6 依赖收紧（1–2 天 · 纯配置 + 一处 Port）

**目标**：包级环 = 0；豁免是"登记的例外"而不是"层序的漏洞"。

**改动**
- `capabilities/skills/loader.py` 的插件发现 → `capabilities/ports.py` 的 `PluginSource` Protocol，由 `bootstrap` 注入
- `.importlinter`：**保留** `capabilities-are-leaf` 的 `allow_indirect_imports=True`（D1），forbidden 增 `plugins`/`engine`/`commands`/`surfaces`；`plugins-stay-an-extension-layer` 增 `runtime`/`execution`/`providers`/`config`；新增 `lower-layers-do-not-import-capabilities`（body：禁 `providers`/`config`/`platform`/`contracts`/`execution`/`surfaces` 六个包 import `capabilities`；实测均 0 边，KEPT 且非恒真）
- **冻结间接入口（D1/R1）**：`gen_graph --check` 断言 `capabilities → execution` 的边集合 == 登记集 **5 条**（`schedule/cron_scheduler.py`、`tools/remote_trigger_tool.py`、`tools/shell/bash_tool.py`、`tools/web/web_fetch_tool.py`、`tools/web/web_search_tool.py`），且 `execution → providers` 的**模块集合** == {`sandbox`, `sandbox.session`}（实为 3 处语句）；多一条、多一个模块即红
- 反向边登记集：只允许 `runtime.swarm.in_process → engine.query` 一条
- `gen_graph.py --check` 输出 `vacuous-contracts`（目标模块不存在而恒判 KEPT 的契约）
- **新增 docs/architecture/GRAPH.md（生成物，禁手改）**：首行 `<!-- generated by scripts/guards/gen_graph.py; do not edit -->`，内容六项——包级邻接表 / 环清单 / **被 import Top10 + 每个文件的类型标注**（契约·原语·门面 vs `base`/`manager`/`types`/`constants`/`helpers`）/ 超阈值清单 / `vacuous-contracts` / 新增能力半径实测。**Top10 栏是“共享点又开始膨胀”的仪表盘**：一旦 `constants`/`manager`/`base` 类文件挤回 Top10，说明 W5 的收口正在被侵蚀。

**验收**
- A：`uv run lint-imports` **现有 9 条 + 新增 1 条 = 10 条全 KEPT**（D2；不为凑数加契约）；`python scripts/guards/gen_graph.py --check` 报告环数 0。
- A2：`GRAPH.md` 与 `--check` 输出逐字一致；**手改其中一行 → `--check` 红**。
- B：临时加一条 `plugins → capabilities` 的 import → 红；**临时给 capabilities 再加第 3 条 `execution` 边 → 红（冻结生效）**；临时加第二条反向边（如 `runtime.x → engine.y`）→ 红；删除一个契约目标模块 → `vacuous-contracts` 数量增加 → 红。
- C：见下表。
- D：回滚 = revert `.importlinter` 与 Port 注入；`lint-imports` 回到 9 KEPT。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| **`allow_indirect_imports` 放行新环** | 直接边干净，间接路径成环 | **冻结入口集**：5 条 file→module 边 + 2 个模块；多一条即红 | Phase 3 抽 `ExecutionPort` 后关闭；关一条删一条登记 |
| 契约引用不存在的模块 | 恒 KEPT，看起来有约束 | `vacuous-contracts` 清单必须打印，且数量不得增长 | 保留条目但标注"未生效" |
| Port 注入把接线错误变成运行时错 | 启动才炸 | `bootstrap` 装配处必须有"未注入即 fail-fast"的断言 | 不引入惰性默认实现 |
| 契约名与 AGENTS 脱节 | 文档写"能力是叶子"，配置里没这条 | W7 的 C3 校验 | 契约名 → 文档双向 |

---

### W7 文档三层（2–3 天）

**目标**：根 AGENTS 只做"路标"，包级只做"边界"，图由脚本产出。

**改动**
- **先搬家**：根 `AGENTS.md` 的 §0–§6 **原文整段迁**到 **docs/CONVENTIONS.md**（不改一字）
- 重写根 `AGENTS.md`：五节（顶层结构 ≤18 行 / 依赖铁律带契约名 / 路由表 15–20 条 / 全局禁令+命令 / 首个 PR 路径 3 条）+ 一行指针；≤170 行且 ≤16KB
- 包级模板补两字段（**不负责**、禁止），回改 9 份；补 `execution`/`platform`/`plugins`/`src/questor` 四份；新建 **docs/architecture/APPEARANCE.md** 覆盖外观五包
- `STRUCTURE.md`：§0/§2.1 手写依赖图改为"文字意图声明 + 指向生成的 `GRAPH.md`"
- 新增 **scripts/guards/check_agents_docs.py**（C1–C6）、`check_agents_md_size.py`
- **C6（手写事实即红）**：`GRAPH.md` / `TREE.md` 首行生成标记缺失、或内容与 `--check` 输出不一致 → 红；`STRUCTURE.md` 里再出现手画依赖图（含 mermaid 边）→ 红

**验收**
- A：C1–C6 全绿；`AGENTS.md` 份数 = 14（根 1 + 包 13）。
- B：删掉任一包 AGENTS → C1 红；把某包"公开入口"写错一个名字 → C2 红（集合比对）；把路由表某行起点改成不存在的路径 → C5 红；把 `AGENTS.md` 加到 171 行 → 尺寸门红。
- B2（迁移完整性）：**docs/CONVENTIONS.md** 的 §0–§6 与迁移前 `AGENTS.md` 对应段落**逐字 sha256 相等**（迁移脚本生成对比）。
- C：见下表。
- D：回滚 = 恢复根 AGENTS（`git checkout`）+ 删 `CONVENTIONS.md`；`check_doc_cross_refs` 必须仍绿。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| **迁移丢内容** | 行为守则少了一节 | 迁移前后段落 sha256 对比 | 用脚本搬，不用手抄 |
| 根 AGENTS 长成论文 | 170 行塞进 118 行旧内容 | 尺寸门（行 + 字节双口径） | 旧内容只留指针 |
| 包级文档复制空话 | 14 份长得一样，零信息 | "不负责"必须点名 ≥1 个**真实存在**的归属路径 | C1 校验该路径存在 |
| `CLAUDE.md` 双份内容 | 两份必然分叉 | `CLAUDE.md` 只允许一行指针 | C1 加字数上限 |
| 路由表路径基准错 | 守卫永远红 | 相对仓库根解析，不用相对当前文件 | 统一 `Path(repo_root)` |
| 图又回到文档里 | 三个月后与代码不符 | `GRAPH.md` 首行 `<!-- generated by gen_graph.py, do not edit -->` | 手写即红 |

---

### W8 门面与尺寸（5–7 天 · 一文件一 PR）

**目标**：14 个含逻辑 `__init__` 清零；8 个导出 >10 收到 ≤10；**4** 个 1001–1500 行文件降到 1000 行以下或登记波次（801–1000 行的 4 个已在健康带，不强制拆）。

**改动**（按风险从低到高）
1. 低风险 5 个：`plugins`(53) / `runtime/hooks`(49) / `skills`(44) / `tools`(37) / `capabilities/policy`(26)
2. 中风险 5 个：`platform`(86) / `providers/mcp`(79) / `engine`(80) / `skills/bundled`(75) / `runtime/swarm`(70)
3. 高风险 4 个：`context/compact`(1166) / `memory/extract`(261) / `providers/lsp`(216) / `memory/session`(139)

形态：Facade + siblings（`compact/` → `compact_policy.py` + `compact_summarize.py` + `compact_placeholders.py`），**行为绝不进门面**；siblings 在函数内延迟 import 门面。

**验收（每个文件单独一轮）**
- A：R4 该文件清零；`pytest` 全绿；冷导入 `python -c "import <mod>"` 通过。
- A2：公开面不变——改造前后该包 `__all__`（或 `dir()` 公开名）集合**相等**。
- A3：**patch 目标计数不变**——改造前后 `grep -r "patch(\"<mod>" tests/` 命中数相等；且这些测试**实际生效**（故意改坏实现，测试必须红一次）。
- B：把一段行为留在门面 → R4 红（因门面必然 >40 行或有 def）。
- C：见下表。
- D：一文件一 PR，回滚 = revert 单个 commit；CLI golden 不变。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| **patch 静默失效**（最隐蔽） | 测试全绿，但改实现不再被测 | 改坏实现必须红一次；patch 目标计数 equal | 门面保留 re-export，siblings 函数内 import 门面 |
| siblings 循环 import | 冷导入炸 | `python -c "import <mod>"` 必跑 | 禁止模块级回边，只在函数内 import |
| 门面变成"只有一行 import 的壳" | 公开面漂移 | `__all__` 集合前后相等 | 集合比对而不是肉眼 |
| 拆完文件数暴增 | 319 → 400 | 文件数增幅 ≤10% 且总量进 baseline | 拆之前先合并重复 |
| 一次 PR 拆多个文件 | 无法定位回归 | 一文件一 PR | 违反即打回 |

---

### W9 命名销账（3–4 天 · 一包一 PR）

**目标**：22 个禁用名清零（含边界裁决）。

**改动**：`git mv` + 同 PR 改写测试 patch 目标 + 改 import。边界情形先裁决：`channels/impl/manager.py`（目录唯一入口且 ≤600 行）按 ADR-0003 §3 的"限定名 + 生命周期所有者"处理。

**验收**
- A：R3 清零；`lint-imports` KEPT；`pytest` 全绿。
- B：新增一个 `helpers.py` → R3 红。
- C：见下表。
- D：一包一 PR；回滚 = revert；基线五项不变。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| Windows 大小写不敏感 | mv 后旧名仍可 import | `check_case_collision` 必跑；`git ls-files` 唯一性 | 先测大小写冲突对 |
| patch 目标漏改 | 测试绿但测不到 | >20 个 patch 目标的包单独排期，逐条核对 | MIGRATION §3.3 既有方法 |
| 改名顺带改语义 | 行为漂移 | 纯 rename：diff 只有符号名 | 发现逻辑改动即拆 PR |
| 公开面被改名 | 下游 import 断 | `__all__` 集合不变 | W7 的 C2 会红 |

---

### W10 归位与清理（1–2 天）

**目标**：顶层平铺收口；僵尸资产出仓；所有权落地；死代码可测。

**改动**
- `cli.py` + **7** 个 `cli_*.py` → `bootstrap/cli/`（move-only；`api.py`/`__init__.py`/`__main__.py` 留根，`api.py` 是公开门面）
- `docs-pre-reset-v1/` 110 文件移到仓外 `Project-main/questor-archive/`，仓内留一行 README 指针
- 新增 `CODEOWNERS`（按一级域 + `src/questor` 单独一条）
- 新增 **scripts/guards/check_orphan_modules.py**（零 import + 非 entry point + 非 `__main__` + 不在测试豁免 → 报告；占比 >5% blocking）

**验收**
- A：顶层平铺 ≤3 文件；`git ls-files docs-pre-reset-v1 | wc -l` = 1（只剩 README）；每个含 `.py` 的一级目录在 CODEOWNERS 有 owner；无引用占比 <5%。
- B：新增一个无人 import 的模块 → 孤儿守卫报告项 +1；把某归档文件引回仓内 → `git ls-files` 命中即红。
- C：见下表。
- D：回滚 = revert；`check_doc_cross_refs` 必须仍绿（归档移出会断链接）。

| 可能的问题 | 症状 | 判据 | 处置 |
|---|---|---|---|
| 归档移出后文档链接断 | `check_doc_cross_refs` 红 | 移出前先全仓 grep 引用并改指向 | 保留一行指针 README |
| CODEOWNERS 写错 owner | GitHub 静默不生效 | owner 必须是真实存在的 user/team | 合并后看 PR 自动 request 是否发生 |
| 移动 `cli_*.py` 打断入口 | 安装后的 console_script 找不到 | `pyproject.toml` 的 entry point 同步改 | 装一次 wheel 实测 `--help` |
| 孤儿守卫误杀 | 把 entry point 判成孤儿 | 白名单：`__main__`、`pyproject` 声明的 entry、测试 fixture | 先报告后 blocking，两阶段 |

---

### W11 规模补丁（可选 · 600 文件前完成）

W1–W10 把形态和门禁做对了，但**五条增长规则**还缺。它们不属于"修现状"，属于"防止 2000 文件后失效"。

| 补丁 | 问题 | 动作 | 验收（含验红） |
|---|---|---|---|
| P1 地图下移一层 | 地图按一级域（固定 17）定份数，而增长在二级域（现 16，1000 文件约 45） | src >600 时，每个二级域（≥5 文件）必有地图或并入父文档并注明 | 新建 `capabilities/tools/fs/` 第 6 个文件 → 地图门红 |
| P2 横切点位封顶 | 新增一个横切维度（权限/日志/审计/取消）要改 N 处；`config/settings.py` 已被 import 41 次 | 拦截点位总数 ≤17；新维度必须走同一点位的 matcher 链；"新增维度改动 ≤1 个共享文件"进不变式；**提前条件：`config/settings.py` 的 import 数 >45，或同一波次新增第 2 个横切维度 → 立即从 W11 提到当前波次，不等 600 文件** | 造第 18 个拦截点 → 红；新增维度改动 >1 文件 → 红 |
| P3 白名单/暂缓池成对 | 只增不减 ≠ 新模块必须进 | 见 W4，此处只做季度盘点：池内条目只减 | 暂缓池条目数增加 → 红 |
| P4 测试按影响选跑 | 90s 预算靠 timeout，不靠选择；3000 文件时会被"少跑"而不是"跑快"解决 | 引入按改动路径的测试选择（先手工映射表，再自动） | 只改 `providers/llm/x.py` 时，跑测数 ≤总测数 30% 且关键测试全含 |
| P5 准入阶梯记账 | 唯一影响增长斜率的机制靠自觉 | `capabilities/tools/` 每新增一个 core tool 必须对应一份 ADR（或 entry 说明走的是哪一级） | 新增 core tool 无 ADR → 红 |

---

## 5. 总验收表（每刀结束回填，注明 commit）

| 指标 | 起始（`b8632fd`） | W1 后 | W4 后 | W7 后 | W10 后 | 目标 |
|---|---|---|---|---|---|---|
| I0 CI 中执行的 blocking 守卫 | 4（3 guard + lint-imports） | 全部 | 全部 | 全部 | 全部 | 全部本体 |
| I1 新增工具半径 | 5 | 5 | 5 | 5 | **1** | ≤1 |
| I2 包级依赖环 | 2 | 2 | 2 | **0** | 0 | 0 |
| I3 命名空间登记缺口 | 未测 | 未测 | 未测 | 未测 | 首版 | 0 |
| I4 尺寸/命名违规 | 0/0/14/8/22 | 就地注释 | 同左 | 同左 | **全 0** | 全 0 |
| I5 文档-代码校验项 | 0 类 | 0 | 0 | **6 类** | 6 类 | 6 类全绿 |
| I6 mypy 白名单模块 | 0 | 0 | **≥22** | ≥22 | ≥22 | 只增不减 |
| I6b 同名测试镜像率 | 33.6% | 33.6% | 33.6% | 33.6% | ≥40% | ≥70% |
| 1001–1500 行文件 | 4 | 4 | 4 | 4 | **0** | 0 |
| `AGENTS.md` 份数 | 10 | 10 | 10 | **14** | 14 | 14 |
| 全量反馈时长 | ~30s | ≤90s | ≤120s | ≤120s | ≤2min | ≤2min |
| **PR 触及 src 文件数中位数**（近 20 个非 merge commit） | 未测 | 首版 | **≤10**；单 PR >40 需在描述里写波次与回滚点 |
| 无引用模块占比 | 未测 | 未测 | 未测 | 未测 | **<5%** | <5% |

**终验（四条，缺一不可）**
1. 给一个行为描述，靠根 AGENTS 路由表 3 次点击内定位（可机器验部分由 C5 管）。
2. 新增一个工具/命令/事件/配置项：共享文件改动 = 1，且由 CI 证明。
3. 字段变更爆炸半径 ≤3 文件 + 1 fixture。
4. 旧快照仍能加载、CLI golden 逐字不变。

---

## 6. 通用失败模式（每刀都要核对）

这十条是"跑完测试也没发现"的典型，任何一条出现，**先修门，不许加豁免**。

| # | 形态 | 识别方法 | 为什么危险 |
|---|---|---|---|
| 1 | 假绿：契约指向不存在的模块 | `gen_graph` 的 `vacuous-contracts` | 读起来有约束，实际无约束对象 |
| 2 | 空扫描通过 | `--fail-on-empty` 关着 | 扫到 0 个文件也 exit 0 |
| 3 | 只验门不跑门 | CI 里只有 `--self-test` | 门被证明能判红，但从未在流水线判红 |
| 4 | 规则比规格宽 | 逐条对照 ADR-0003 §8 | 门写着实现了，实际只查一半 |
| 5 | 豁免泄漏 | 注释无删除条件 / 数量增长 | 债务永久化，且 PR diff 里不可见 |
| 6 | 门太吵被关 | 告警被当失败 / 误报多 | 开发者一次 `--no-verify` 就绕过 |
| 7 | 口径漂移 | 行数 ±1~4、扇出含不含 `__init__` | 文档与实测永远对不上，信任崩塌 |
| 8 | 平台差异 | Windows 绿 / Ubuntu 红 | 大小写、路径分隔符、编码、换行 |
| 9 | 缓存不一致 | 本地增量绿、CI 全量红 | mypy/pytest/ruff 三套缓存都要管 |
| 10 | 文档回到手写事实 | `GRAPH.md`/`TREE.md` 出现手改 | 三个月后没人信任何一份地图 |

---

## 7. 明确不做

1. 不重排一级目录、不改包名、不建空目录（`kernel`/`profiles`/`apps/` 等有真实文件才建）。
2. 不在 W0–W6 期间改任何函数签名（W5 的属性声明除外）。
3. 不承诺 mypy 清零，只承诺"白名单内零错 + 新模块必须登记"。
4. 不为覆盖率造测试，只钉基线不倒退。
5. 不做 mtime 同步门禁。
6. 不引入第二层任务运行器（`justfile`/`Makefile`）；入口统一 **scripts/check.py**。
7. 不在平台测试里 fake `sys.platform`。
8. 不把表格式 baseline 重新引入（豁免一律就地注释）。

---

## 8. 节奏与预算

| 波次 | 预算 | 改行为 | 可并行 |
|---|---|---|---|
| W0 + W1 | 1.5 天 | 否 | 否 |
| W2 + W3 | 3–4 天 | 否 | 是（不同文件） |
| W4 | 2 天 | 否 | 与 W3 并行 |
| W5 | 3–4 天 | **是（轻）** | 否 |
| W6 | 1–2 天 | 否 | 否 |
| W7 | 2–3 天 | 否 | 与 W8 前半并行 |
| W8 | 5–7 天 | 否 | 一文件一 PR，可排队 |
| W9 | 3–4 天 | 否 | 一包一 PR，可排队 |
| W10 | 1–2 天 | 否 | 否 |
| W11 | 按需 | 否 | — |

**W0–W6 合计约 11–16 天**，是"防止后续爆雷"的全部杠杆；W7–W10 是销账，可与既有 Phase 2 剩余波次交织。W0–W6 期间零功能风险（W5 除外，且 W5 有 CLI golden 兜底）。

---

## 9. 一句话

**这份计划交付的不是"结构"，是 25 条可判红规则（I0–I8 / R1–R10 / C1–C6）+ 14 份只写边界不写事实的地图 + 一份生成的 `GRAPH.md` + 一条"新增能力只改一个文件"的路径。** 判断它是真做完还是假做完，只看一件事：**你构造的违规，CI 红了没有。**

---

## 10. 偏差台账

只追加，不改正文。一行一条：现象 / 计划原文 / 实测 / 处置 / commit。

| # | 现象 | 计划原文 | 实测 | 处置 | commit |
|---|---|---|---|---|---|
| 1 | 基线文件路径两说 | §1 写 **tests/fixtures/structure_baseline.json** | §4 W0 写 `tests/fixtures/baseline/structure.json` | 采用后者：与既有 `baseline_check.py` 快照同目录，不另建目录 | W0 |
| 2 | `.gitignore` 要加两行 | §4 W0「增 `.tmp-baseline/`、`scratch/`」 | `scratch/` 已在册 | 只增 `.tmp-baseline/`，不重复加 | W0 |
| 3 | B1 采集命令与数字不自洽 | §1「`git ls-files 'src/**/*.py'`」= 319 | 该命令实得 **318**（`**/` 不匹配 `src/__init__.py`）；319 需 `git ls-files src` 过滤 `.py` | `caliber` 记后者；`src_files` = 319 / `modules` = 256 | W0 |
| 4 | B11 节点数漂移 | 1177 用例 | **1178**（`summary.json` 已在 e779133 更新） | 按实测记录，`gate=false`（节点集合由 `baseline_check.py` 拥有） | W0 |
| 5 | B15 行数漂移 | 118 行 / 8646 字节 | **119 行** / 8646 字节 | 按实测记录 | W0 |
| 6 | B17 二级目录数（**本行先记错，已改正**） | §1 B17「≥2 个非 `__init__` 源文件」的二级目录 = 16 | 计划值 16 正确；W0 的实现只数了 depth-2 目录（`capabilities/<X>/<Y>`）得 12，漏掉 `capabilities/tools/*.py` 这类平铺族 | W0 记 12 是实现错，不是口径差异。已将 `collect()` 改为「任意深度目录、≥2 个非 init」→ 实测 16；`subdirs_ge2` 刷新为 16；详见 #48 | W0 / 复核修正 |
| 7 | B9 工具半径的"registry ×2 处" | 半径 5，含 `registry.py` ×2 处 | `registry.py` 里没有工具名字面量（只有类实例化），字面量命中的是 4 个消费方 | 半径 = 注册点（恒计） + 字面量消费方 = **5**，另记 `literal_hits` = 4 | W0 |
| 8 | B13 "CI 只跑 3 个"会成为易变项 | 守卫 5 / CI 3 | 计数会随 W1 把守卫搬进 CI 而变 | `ci_guard_scripts.value` 固定为基线守卫数 5；`in_ci` 只记录不设门（真正的门是 **scripts/check.py** + `ci.yml`） | W0 |
| 9 | `--check` 的 expected/got 语义 | 「expected 319, got 320」 | 常规写法是 expected=基线、got=实测，与该证据串相反 | 按证据串实现：`expected` = 现场实测，`got` = 基线文件记录值；输出追加 `(recorded baseline is stale)` 消歧 | W0 |
| 10 | `--record --fast` 不存在 | §4 W1「`--record --fast` 受控重录」 | `scripts/baseline_check.py` 明写 `--fast cannot be combined with --record` | 改用 `--record` 全量重录（本机 ~100s），再做三件审计 | W1 |
| 11 | 该标量不只跨机不稳，还随分支变 | 「`dryrun.txt` 的 `system prompt chars` 19008 → 18987」 | 切到 `ci/structure-hardening` 后同一台机器变为 **19005**（prompt 内嵌 git 分支名）；每次改分支就漂 20 上下 | 归一化为 `- system prompt chars: <VOLATILE>`；体积信号移交 W3 固定输入快照 | W1 |
| 12 | pre-commit 五个守卫 hook 都指向单个脚本 | §4 W1「`layout` / `tree-map` 改为调用 **scripts/check.py**」 | 若只改两个 hook，`import-contracts`/`secret-projection`/`doc-cross-refs` 仍会与 `check.py` 分叉 | 五个 hook 合成一个 `repo-guards`（`--fast`），pre-push 改为全量 `scripts/check.py`；同时更新守卫 README 的入口说明 | W1 |
| 13 | CI 里看不到四条实体命令的字面串 | §4 W1「`guards` job 的 step 列表包含上述四条实体命令」 | 单一入口后，命令只存在于 **scripts/check.py** 的 `STEPS` 表 | `guards` job 先跑 `scripts/check.py --list` 把完整 argv 表打进 CI 日志，再跑 `scripts/check.py`；断言依据从 `ci.yml` 文本改为「日志 + `STEPS` 表」 | W1 |
| 14 | R5 存量 17，不是 16 | §4 W2「R5 16 处（8 个无 `__all__` 的顶层包 + 8 个导出 >10 的包）」 | 还有第 9 个无 `__all__` 的顶层包：`src/questor/gateway/__init__.py`（产品分发） | 预算改为 17；补 `__all__` 属公开面变更，本波次不做 | W2 |
| 15 | R8 存量未给数，且启发式会高估 | §4 W2「R8 新增一个 CC 21 的函数 → 红」 | 简单 AST 启发式（含嵌套定义）估 50；改为排除嵌套 `def`/`class`/`lambda` 后是 **40 个函数 / 31 个文件** | `R8_EXEMPT_FUNCTIONS = 40`、`EXEMPTION_BUDGET["R8"] = 31`；两道上限都只能降 | W2 |
| 16 | R6 的「关键文件」行混了非路径 token | ADR-0003 §8「AGENTS.md 的关键文件少于 2 个或路径不存在 → fail」 | `commands/AGENTS.md` 里写了类名 `CommandRegistry`，不是路径 | 只把含 `/` 或以 `.py` 结尾的 token 当路径；不存在的路径仍红 | W2 |
| 17 | 豁免总量 | 计划只给了每规则条数 | 实际写入 **258 条注释 / 222 个文件**（R2 4 / R3 22 / R4 14 / R5 17 / R7 170 / R8 31） | 插入脚本 `scratch/annotate_layout_backlog.py` 不入库；commit body 记录了匹配正则与文件数 | W2 |
| 18 | `--self-test` 条数 | §4 W2「`check_layout --self-test` 8 条全过」 | 实际是 **8 条规则 / 16 个用例**（每条规则红+绿） | 超过计划要求，保留；汇报里按「8 条规则、16 用例」记 | W2 |
| 19 | R1 无存量且无 catalog | ADR-0003 §8「排除 migrations/schemas/generated」 | 仓内无此类目录 | `CATALOG_DIRS` 常量首版为空，扫描命中 0 → R1 只挡新增 | W2 |
| 20 | 新增测试改变了 node-id 基线 | 计划 W2 未提 node ids | `tests/ci` 新增 22 个用例 → 1178 → **1200**；`test_files` 139 → **141** | 在 W2 末做一次 `--record`；审计确认 `dryrun.txt`/`help-*.txt`/`doctor.txt` **未变**，只有 `main_node_ids.txt` + `summary.json` 变；结构基线 `test_files` 经 `--refresh-baseline --reason` 更新 | W2 |
| 21 | TREE.md 行数漂移 | `gen_tree` 用 `walk_py`（工作区） | 行内注释每文件 +2 行 → TREE.md 陈旧 | `gen_tree.py --write` 重生成；结构基线只比 `value`，`long_files.max` 1187 → 1190 经 `--refresh-baseline --reason` 刷新 | W2 |
| 22 | ADR-0003 §2 阈值表已过时 | 计划 §1 B7 已改 1001–1500 / 1500 | ADR 表仍写 801–1200 / 1200 | 在 ADR §2 加一行「2026-10-23 修订」，指向 **scripts/guards/_layout_rules.py**；不改历史表格 | W2 |
| 23 | `ci_guard_scripts.in_ci` 变空 | 计划未提 | 单一入口后 CI 不再直接调任何守卫脚本 | 该项只是记录字段（不设门）；`value` 仍为 5，门在 **scripts/check.py** | W2 |
| 24 | `gen_namespaces --check` 未列入守卫 | §4 W2 只列了 R10 守卫 | 登记表是生成物，不加新鲜度检查就会再次变成手写事实 | `scripts/check.py` 增加 `namespace-doc` 步，与 `name-registries` 成对 | W2 |
| 25 | prompt surface 需要 5 个打桩，不是 1 个 | §4 W3「固定渲染输入」只点名 `EnvironmentInfo` + `get_platform` | 还必须打桩 `load_local_rules`（读用户配置）、`get_user_skill_dirs`（读 `~/.questorharness/skills`、`~/.claude/skills`）、`questorharness.plugins.loader.load_plugins`（读用户插件目录） | 五个 patch 写在 `scripts/ci/prompt_surface.py` 顶部常量区；少一个就会漂 | W3 |
| 26 | 4 个宿主的输入并非全不同 | §4 W3「宿主至少：CLI、桌面 host、一个 channel、cron」 | 四个宿主共用 `bootstrap/runtime.py:367` 的同一装配；`cli`/`desktop`/`cron` 只在 `latest_user_prompt` 上不同（而它只影响（空的）项目记忆）→ 三份快照逐字相同；真正不同的是 `channel`（`include_project_memory=False` + 一个 gateway 工具，1701 vs 1739 行） | 保留四份（路径覆盖 + 漂移定位），并断言 `len(HOSTS) == 4`；台账记明“三份相同是真的，不是漏渲” | W3 |
| 27 | 没有复用 `_child_env` | §4 W3「复用 `baseline_check._normalize` 与 `_child_env`」 | `_child_env` 只为子进程准备环境；本实现改为**进程内渲染 + patch**，不启动子进程 | 复用 `_normalize`（同一归一化），不用 `_child_env`；理由写入脚本 docstring | W3 |
| 28 | 白名单会引出重复模块错误 | §4 W4「`files = [...]` 白名单」 | `src/__init__.py` 让 `src` 成为包，mypy 同时按 `src.questorharness...` 与 `questorharness...` 命名同一文件 → `Source file found twice` | 加 `mypy_path = "src"` + `explicit_package_bases = true` | W4 |
| 29 | 错误集与 E1 预估不完全一致 | 计划 E1：4 attr-defined + 1 assignment + 2 no-any + 1 arg-type | 加 `py.typed` 与 pydantic 插件后实为：4 `attr-defined`（fcntl）+ 1 `assignment` + 2 `assignment`/`attr-defined`（`platform/session_storage.py`，之前被 `import-untyped` 掩盖）+ 1 `no-any-return`；`message.py:160` 的 `arg-type` 因插件已消失 | 总数仍为 8，全部真修：2 行带原因 ignore、`cast`、局部注解、`isinstance` 窄化；**没有新增 type: ignore** | W4 |
| 30 | `# type: ignore[code] -- 原因` 语法无效 | §4 W4「只允许 `# type: ignore[code]` 且带 `-- 原因`」 | mypy 报 `Invalid "type: ignore" comment [syntax]` | 改用 mypy 认可的 `# type: ignore[code]  # 原因`；`check_mypy_scope` 的忽略卫生检查两种都收 | W4 |
| 31 | `types-PyYAML` 未加依赖 | §4 W4「靠 + `types-PyYAML`」 | 加 dev 依赖会改 `uv.lock` 且可能顺带升级 | 改用 `[[tool.mypy.overrides]] module=["yaml"] ignore_missing_imports`，并写明删除条件；不动锁文件 | W4 |
| 32 | 暂缓池用包级计数 | §4 W4「暂缓池条目数被记录」 | 模块级是 234 条，不可审 | `mypy_deferred.json` 记 16 个包 / 234 个模块；任一包计数上涨即红；抬高计数是显式、可审的改动 | W4 |
| 33 | 声明合并成单一 `ToolCapabilities` | §4 D4「`read_only_by_default: ClassVar[bool] = False`」 | 四个字段各自默认值无法区分「声明为 False」与「漏声明」 | 改为**一个必填声明** `capabilities: ClassVar[ToolCapabilities]`（字段带默认值），AST 断言每个子类类体里必须有这个赋值；`capability_index()` 遇无声明者抛 `UndeclaredToolError` | W5 |
| 34 | coordinator 不在“0 命中”范围内 | §4 W5「4 处消费方 0 命中」 | `capabilities/context/coordinator.py` 剩的两张表（`_WORKER_TOOLS`/`_SIMPLE_WORKER_TOOLS`）是**工作器能力策略**，不是每工具事实；新工具不应自动加入 | `get_coordinator_tools()` 改由 `by_remember_key` 派生；两张策略表在 `check_tool_radius.POLICY_LISTS` 具名豁免；半径指标同步剔除该文件（否则 2 而不是 1） | W5 |
| 35 | 分类名与工具名撞车 | §4 W5「工具名字面量 0 命中」 | `category == "skill"`/`"grep"` 等分类串本身就是工具名，字符串扫描会误报 | 守卫只判「列表/集合字面量里 ≥2 个工具名」与「`tool_name == "<工具名>"`」；分类比较不算 | W5 |
| 36 | private helper 加了参数 | §7.2「不改函数签名」 | `_remember_async_agent_activity/task` 原来按 `tool_name` 分支，现在需要 `category` | 两个模块内部 helper 各加一个关键字参数（无外部调用方）；golden 15 用例逐字相等 | W5 |
| 37 | 公开面新增一个名字 | 计划未提 | 产品工具必须从 `questorharness.api` 取类型（`product-uses-public-face` 禁止直连 capabilities） | `api.py` 重导出 `ToolCapabilities`；属纯加法 | W5 |
| 38 | 门面测试的旧前提失效 | — | `tests/unit/test_tools/test_tools_facade.py` 断言“取到工厂就导入 30+ 模块”；discovery 后改为“调用工厂才导入” | 测试改为三段：取工厂前 <10 / 取后仍 <10 / 调用后 ≥30 且工具数 ≥30 | W5 |
| 39 | 工具半径实测 | §4 W5「radius 5 → 1」 | 注册点 1 + 消费方 3（均 0 命中）= **1**；`structure.json` 的 `tool_radius` 经 `--refresh-baseline --reason` 从 5 刷到 1 | 金标 15 个调用前后逐字相等；`read_only_tools` 9 / `compactable_tools` 8 与旧名单完全一致 | W5 |
| 40 | 契约 10 条全 KEPT | §4 D2「9 + 1 = 10」 | 实测：`Contracts: 10 kept, 0 broken`（`capabilities-are-leaf` 加 plugins/engine/commands/surfaces，`plugins-stay-an-extension-layer` 加 4 条，新增 `lower-layers-do-not-import-capabilities`） | 不为凑数加第 11 条 | W6 |
| 41 | “环数 0”的准确口径 | §4 W6「报告环数 0」 | 包级环 **1**：`engine↔runtime` 就是计划自己保留的那一条反向边（`.importlinter` 的 `ignore_imports`） | `gen_graph` 分开报「已登记 / 未登记」：实为 1 / **0**；未登记 0 才是门禁对象 | W6 |
| 42 | vacuous-contracts 实测 11，不是 2 | §4 W6「目标模块不存在」 | 6 个不存在的目标 × 多条契约 = **11 条记录**：`kernel`/`personalization`/`profiles`/`prompts`/`skills`/`ui`（后三个是 Phase 1 已搬到 `capabilities/` 的旧顶层包） | 按实测写入 `GRAPH.md`；`--check` 逐字比对，多一条即红 | W6 |
| 43 | 冻结靠“内容相等”实现 | §4 W6「多一条即红」 | 若另立 pin 文件，就多一份可手改的真源 | 冻结集写在 **docs/architecture/GRAPH.md** 里（5 条边 + 2 个模块 + 1 条反向边），`gen_graph --check` 逐字比对：多一条边/多一个环/多一条恒真契约/手改一行 → 红 | W6 |
| 44 | Port 注入的接线点不止 bootstrap | §4 W6「由 bootstrap 注入」 | `--dry-run` 预览也构建真 prompt（`cli_preview.py`），不接线就会抛；测试也需要 | 三个接线点：`bootstrap/runtime.py:build_runtime`、`cli_preview` 预览构建、`tests/conftest.py` autouse；`load_skill_registry` 签名不变，fail-fast 在 loader 里 | W6 |
| 45 | prompt_surface 的插件隔离方式变了 | §4 E3「注入 NullPluginSource」 | 原先 patch `plugins.loader.load_plugins`，Port 之后不再经过它 | 改为 `configure_plugin_source(NullPluginSource())`；四份快照逐字未变（证明隔离等价） | W6 |
| 46 | 契约数变了会打红旧 summary | `.importlinter` 从 9 → 10 | `baseline_check` 的 `summary.json` 记的 `lint.kept` 是 9 | W6 末做一次 `--record`；`dryrun.txt`/`help-*.txt`/`doctor.txt` 均未变 | W6 |
| 47 | `src_files` 变 320 | W0 基线 319 | `plugins/source.py` 是新增源文件 | `--refresh-baseline --reason`；`test_files` 142、`tool_radius` 1 同步 | W6 |
| 48 | 复核发现「二级目录」口径实现错 | §1 B17 = 16 | 旧实现按 `capabilities/<X>/<Y>` 深度过滤得 12；B17 的定义是**任意目录** ≥2 个非 `__init__` 源文件 = **16**（`capabilities/tools` 下 13 个平铺工具文件被整段漏掉） | 修 `gen_structure_baseline.collect()`：统计 `capabilities/` 下任意深度目录；`subdirs_ge2` 重新刷新为 16；#6 已同步改正 | 复核修正 |
| 49 | registry 的「手工列表归零」只是换形态 | §4 W5-A「新增工具只动 2 文件」 | 实现是 `pkgutil` 发现 + 39 条显式类名顺序 + 双向校验（未发现/未登记/重名）；`registry.py` 198 行，随工具数线性增长，约 500 工具时会撞 250 行 `FILE_BUDGETS` | 半径契约（I1 = 1）成立，不算违约；已在 `registry.py` 写明「>100 工具时改为族内按名排序 + 例外表」，作为 W11/P5 的输入 | 复核补充 |
| 50 | vacuous 11 会被误读成「11 条约束在生效」 | §4 W6「目标模块不存在而恒判 KEPT」 | 11 条全部来自 **5 条老契约**的空目标：`kernel`(×5)/`profiles`/`ui`(×2)/`prompts`/`skills`/`personalization`；共声明 86 个目标，**实际生效 75 个**；新契约没有产生空条款 | `gen_graph` 在 vacuous 段输出「共声明/实际生效」与契约/模块出处，数字由生成器计算，不手写；逐字比对仍锁住增量 | 复核补充 |
| 51 | 单次耗时不能当基线 | 报告写「25.2s」 | 同机复跑 29.4s（缓存/负载浮动） | 判据只写「21 步、预算 90s」；耗时按区间（25–30s）记，不把单次值当基线 | 复核修正 |
| 52 | 窗口 2 提示词的 commit 数过期 | 自检表写「9 个 commit」 | 实测 **10**（多了 `9244ebf` 复核修正刀） | 以实测为准；提示词不改成能过的数字 | W2 自检 |
| 53 | 窗口 2 提示词的台账行数过期 | 「§10 台账（47 行）」 | **51 行**（#48–#51 是复核修正） | 以实测为准，并继续在本节追加 | W2 自检 |
| 54 | 「一文件一 PR」与「不 push」互斥 | 提示词两处要求 | 本轮 push ✗，无法开 PR | 一个分支 + 每单元一个 commit + 结束一个 PR；单元边界由 commit 保证 | W2 自检 |
| 55 | `EXEMPTION_BUDGET` 只判上界 | 提示词核心规则「每销一笔账必须同 PR 下调预算」 | 旧实现只判 `count > budget`：清完账不下调预算**不会红**，纪律靠人记 | 改为**等值棘轮**：新增纯函数 `_layout_rules.budget_problems()`，`>` 报「debt was added」、`<` 报「budget was not lowered in the same change」；`R8_EXEMPT_FUNCTIONS` 同步改为等值比较 | W2-§1 |
| 56 | 基线多一份「可见副本」 | 提示词只要求预算在守卫里 | `structure.json` 新增 `layout_exemptions`（`gate=false`），预算变化在此可见可 diff | 真源仍是 `EXEMPTION_BUDGET`；此字段只记录不设门 | W2-§1 |
| 57 | 合成仓库无豁免会撞等值棘轮 | — | `tests/ci/test_guards_contract.py` 的临时仓库豁免数为 0，真实预算会报「偏高」 | `collect_with_budgets(root, *, budget=None, pinned_functions=None)`：测试传空预算，CLI 用默认（新增 2 个用例专测两个方向） | W2-§1 |
