# R04 · 工具/权限/沙箱 参考扫描报告

> 只读扫描三份参考实现，为打磨 [`docs/design/03-tool-interface.md`](../design/03-tool-interface.md) 提供增量与缺口。所有引用附**文件:行号**。
> 范围（用户指定）：
> - **DeepCode-main**：`core/harness/permissions.py · policy.py · approval.py · sandbox.py · windows_sandbox.py · command_guard.py · env_sanitize.py · __init__.py` + `core/mcp/connection.py · tools.py`
> - **wuu-main**：`internal/agent/tool_runtime.go · tool_gate.go · tool_nested.go` + `internal/approvefor/review.go`
> - **CowAgent-master**：`agent/tools/base_tool.py` + `agent/permission/policy.py · __init__.py`
>
> 原则：读全不抽样、只提增量与缺口、不改 03 本体（03 的改动由后续"落地补丁轮"执行）。

---

## 0. 一句话结论

03 已把"策略只提议 / 校验·权限·沙箱·超时·记账全在 Harness"这条主轴立住了。三份实扒暴露的是**下一级具体化**：评估次序、参数字典、shell 解析、MCP 权限"只收紧不放宽"的组合律、账本落账必须脱离取消链、并行 gate 的 writer 优先级——这些没写进 03，实现期一定返工。

---

## 1. ToolSpec（03 §1）——契约字段的实扒校准

### 1.1 增量：`read_only` / `parallel_safe` 是**权威布尔**，不是 capability 派生

03 §1 只有 `capability: readonly|write|exec|network|memory`。三份实现都把"是否只读/是否可并行"作为工具**自报的一等字段**，capability 只是分类：

- wuu `ToolMetadataProvider.ToolMetadata(call)` 直接返 `(ReadOnly, ConcurrencySafe, Orchestrator)` 三 bool；`toolCanRunConcurrently` 走 `meta.ConcurrencySafe`；`toolCanStartDuringStreaming` 走 `meta.ReadOnly && meta.ConcurrencySafe`（`wuu-main/internal/agent/tool_runtime.go:872-894`）。**元数据缺失 → 视作 false → 串行/非只读，fail-closed**（同文件 878、890 行）。
- DeepCode `McpToolAdapter.read_only` 注释明确："MCP annotations are hints, not grants. Unknown is deliberately mutating so default/writes policies fail toward confirmation."（`DeepCode-main/core/mcp/tools.py:70-74`）
- CowAgent `BaseTool.parallel_safe: bool = False`（`CowAgent-master/agent/tools/base_tool.py:103-108`）—— 默认关，"only for work that is independent by construction"。

→ **03 §1 ToolSpec 建议补**：`read_only: bool`（权威，不是 capability 派生）、`parallel_safe: bool`（保留，但强调缺省= False、缺失元数据=fail-closed）、`orchestrator: bool`（子代理/嵌套编排角色，v1 预留）。

### 1.2 增量：`approval_mode` 是 per-tool **附加收紧位**，不是权限引擎的第二个头

DeepCode `McpToolAdapter.approval_mode = server.definition.policy_for(raw_name)`（`DeepCode-main/core/mcp/tools.py:56`）：值域 `{auto, approve, prompt, writes}`。

`PermissionEngine.evaluate_tool` 的组合律（`DeepCode-main/core/harness/permissions.py:269-309`）：
- `if decision is not ALLOW: return`（引擎已经 ask/deny，per-tool **不能翻案**）；
- `prompt` → 把 allow 降 ask；
- `writes` → 仅当 `read_only is True` 才继续 allow；
- **unknown approval_mode → `DENY, "unknown MCP approval policy (fail-closed)"`**（同文件 309 行）。

→ **03 §6 建议补一句**："MCP 工具自带 approval_mode 只能把全局 allow 收紧为 ask/deny，**不得放宽** ask/deny；unknown 值按 fail-closed deny 处理。"

### 1.3 增量：描述与 schema 归一（untrusted remote）

DeepCode `sanitize_description(remote, name=..., max_chars=8_000)` 与 `normalize_schema_for_openai(raw_schema)` 是 MCP 工具进 ToolSpec 的两道**归一预处理**（`DeepCode-main/core/mcp/tools.py:13、46-52`）。`presentation_detail()` 对任意 remote 工具**返回空串**："Arbitrary remote tools may accept credentials or signed URLs under innocent-looking argument names. Inventory identifies the tool; raw arguments remain in protected observability only."（`DeepCode-main/core/mcp/tools.py:80-84`）

→ **03 §1 建议补**：`description` 长度上限 + 空/退化回退；MCP 类工具的 `display_hint`（卡片摘要）默认**不暴露 raw 参数**。

### 1.4 增量：CowAgent 的 `renders_own_cards` / `stage` / `close`

`base_tool.py:70-79`（`renders_own_cards`，err-toward-generic）、`6`（`ToolStage.PRE_PROCESS|POST_PROCESS`：主动选择 vs. final_answer 后自动执行）、`243-251`（`close()`：释放浏览器/文件句柄）。

→ **03 §1/§2 可选加**：`renders_own_cards?`（默认 False，防"通用卡片 + 工具自发卡片"重复）、`lifecycle.close()`（插件生命周期挂 C10）。`stage` 属策略调度语义，不放 ToolSpec，避免与 01 §3 任务树混淆——**建议不采纳**。

---

## 2. 两层校验（03 §3）——参数字典 + 求值次序才是可开发级

03 §3 写了"① schema ② 权限"，但**没写 Harness 怎么从 params 里认出"路径/命令/动作"**——三份都维护一份**arg-key 词典**，不然 denylist 与沙箱都无从下嘴。

### 2.1 增量：arg-key 词典（路径 / shell 命令 / 动作 / patch 路径前缀）

- DeepCode `_PATH_ARG_KEYS = (file_path, path, root, workspace_path, target, filename)`（`DeepCode-main/core/harness/permissions.py:92`）；`_SHELL_TOOL_NAMES = (bash, exec, execute_bash, execute_commands)`（同 151 行）；`_PATCH_PATH_PREFIXES = (*** Add File:, *** Update File:, *** Delete File:, *** Move to:)`——apply_patch 的路径藏在结构化 patch envelope 里，需专门抽取"声明性路径指令"再走同一套中央保护，不为它开工具特例（`DeepCode-main/core/harness/permissions.py:93-98、219-229`）。
- CowAgent `_FILE_WRITE_TOOLS = {write, edit}` + `_ACTION_TOOLS = {browser:(action,{click,fill,select,press,evaluate}), scheduler:(action,{create,delete,enable,disable}), env_config:(action,{set,delete})}`（`CowAgent-master/agent/permission/policy.py:109、115-121`）——"只有部分子动作会写"的工具靠 arg 名+集合精确判。
- CowAgent `_MUTATING_NAME_RE`：未在白名单里的陌生工具名（多数是 MCP 动态注册），按名字里的动词（create|add|update|delete|...）判"看起来会改状态"（`CowAgent-master/agent/permission/policy.py:134-140`）——**只用于 read-only mode 的兜底**，其他 mode 不做名 heuristic。

→ **03 §3 建议补一段"参数字典"**：ToolSpec 或 Harness 层维护 `path_arg_keys / shell_arg_keys / action_arg_keys`；对 apply_patch 类结构化路径要单独抽取，**不为每个工具写特例**。

### 2.2 增量：JSON-parse 先于 schema

wuu `executeToolResult`：`if arguments != "" && !json.Valid(arguments): return InvalidArguments`（`wuu-main/internal/agent/tool_runtime.go:824-830`）——先判"是不是合法 JSON"，再进工具；非法 JSON 不进工具，不进账本之外。

CowAgent 用 `_coerce_integer_args` 做**一层通用 coercion**：模型常写 `"offset":"2"`，Harness 按 schema `type=integer` 转成 int，转不动就报错——工具自身只需校 range（`CowAgent-master/agent/tools/base_tool.py:193-207`）。

→ **03 §3 建议**：把"校验"拆成 ①JSON 合法性 → ②schema 校验 → ③类型 coerce（可选）→ ④权限判定 → ⑤业务校验（在工具 execute 内）。当前 03 只写了①②⑤。

### 2.3 增量：**评估次序**（03 现在缺这一段）

DeepCode 顶层注释给出铁次序（`DeepCode-main/core/harness/permissions.py:26-30`）：

```
1. sensitive-path protection          → DENY   (when enabled)
2. canonical Read only upper bound    → DENY   (mutating tools)
3. explicit rule match (last-wins)    → its action
4. mode default for read-only vs mutating tools
```

其中 rules 采用**二维通配 + last-match-wins**：`PermissionRule(permission, pattern, action)`，`fnmatch` 双维度匹配，后规则覆盖前规则（`DeepCode-main/core/harness/permissions.py:123-138、354-356`）。

→ **03 §3 建议加"求值次序"子节**，写清"denylist 优先于 rules、rules last-wins、mode 兜底"。

### 2.4 增量：`approval_policy=never` 时 ask **降为 deny**（headless fail-closed）

DeepCode `_apply_approval_policy`（`DeepCode-main/core/harness/permissions.py:384-404`）：`ASK + ApprovalPolicy.NEVER → DENY`。理由原文："a headless or otherwise non-interactive profile must not turn that into permission."

→ **03 §7 表格建议加一行**：`无审批人(headless / IM 通道无桌面端) → ask 视作 deny`；对齐 ADR-0006。

---

## 3. 三态权限 + denylist（03 §4/§7）

### 3.1 增量：三家的 mode 语义**不统一**，03 需要显式拆开

- DeepCode mode = `{default, plan, full_auto}`（`DeepCode-main/core/harness/permissions.py:55-59`）：**决定"没有 rule 命中时隐式默认"**（default：mutating→ask；plan：mutating→deny；full_auto：一律 allow）。
- CowAgent mode = `{read-only, workspace-write, full-access}`（`CowAgent-master/agent/permission/policy.py:39-43`）：**决定"能改什么"**（文件写围栏 + shell 白名单）。
- wuu 权限模式另有一套，`approvefor.EnabledForMode` 只对 `PermissionModeStandard` 开 review 流（`wuu-main/internal/approvefor/review.go:103-105`）。

→ **03 §7 建议改写**：明确 mode 是**"隐式默认决策"轴**（DeepCode 语义），capability+risk 是**"最小门"轴**，write_roots/protected_paths 是**"围栏"轴**（CowAgent 语义），**三轴正交**。v1 只做前两轴（DeepCode 型 mode + capability 表），第三轴走 ADR-0006 的沙箱后端。

### 3.2 增量：**denylist 不可覆盖**的具体形态

- DeepCode `SENSITIVE_PATH_PATTERNS`：`.ssh/.aws/credentials/.env*/.git-credentials/*.pem/*.key/id_rsa*/id_ed25519*/...`（`DeepCode-main/core/harness/permissions.py:66-89`）。命中即 return，**先于 rules 与 mode**（同文件 326-339 行）。
- DeepCode Full Access 预设**同时关掉 sensitive-path 与 sandbox**，"honest unrestricted-filesystem promise"（`DeepCode-main/core/harness/permissions.py:13-17、policy.py:204-210`）——**诚实边界**：真全访问要一起关，别一边写"沙箱保护"一边又绕过 denylist。
- CowAgent `protected_paths`（`policy.py:516-527`）：**即使位于 workspace roots 内也拒**（mcp.json / config.json / .env / credentials）；`_deny_protected` 明确："Nothing was written."（同 553-559）
- wuu `HardDenyReason`（`wuu-main/internal/approvefor/review.go:88-101`）：三类**任何 reviewer 都不能覆盖**的拒：
  1. `wuu credential files are never accessible to the agent in any permission mode`；
  2. `approve for me cannot raise the session permission mode`（**审批回复里不得携带 mode 提权**）；
  3. `write_file`/`edit_file` 命中 sensitive path（`.env*`、`id_rsa/id_ed25519/id_ecdsa`、含 `private`+`key`）。

→ **03 §4/§7 建议**：把"denylist 不可覆盖"具体化为**三层**：路径 denylist（sensitive files）+ **提权 denylist**（mode 字段本身不能被审批携带）+ **roots 内二次保护**（mcp.json 等"能开权限"的文件）。

### 3.3 增量：路径匹配前的规范化

三份都不做"raw 字符串匹配"：
- DeepCode `_normalize_path`：`expanduser + 相对 cwd + os.path.normpath`；匹配时 `os.sep → /` 再 fnmatch，`*` 跨分隔符（`DeepCode-main/core/harness/permissions.py:141-148、232-242`）。
- wuu `isWuuCredentialCall`：先按 cwd 补 abs，再 `filepath.EvalSymlinks(value)` **二次判定**（`wuu-main/internal/approvefor/review.go:121-141`）——**软链穿透**是必须的。
- CowAgent `_real`：`expanduser + expandvars + join(cwd) + realpath`；roots 匹配 `os.path.commonpath` 兜 Windows 跨盘符 ValueError（`CowAgent-master/agent/permission/policy.py:482-513、516-527`）。

→ **03 §4 建议加**：路径 denylist 匹配前**必须** realpath/expanduser/evalsymlink；软链与 Windows 大小写差异是"绕过 denylist"的主要路径。

### 3.4 缺口：**shell 命令解析**——03 §4 完全没写，是最大实现风险

三份实现都把 bash/exec 类视为**最难的一块**，共同做法：

1. **先按 shell 分隔符切段**（`;` `&&` `||` `|` `&` 换行、括号），**再对每段 shlex.split**。
   - DeepCode `command_guard._OPERATOR_SPLIT = r"(?:\|\||\||&&|&|;|\n)"` + `shlex.split(posix=True)`（`DeepCode-main/core/harness/command_guard.py:58、147-160`）。
   - CowAgent `_SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", "{", "}", "\n"}` + `shlex.shlex(punctuation_chars=True, whitespace_split=True)`（`CowAgent-master/agent/permission/policy.py:292、380-397`）。

2. **CowAgent 额外**：反引号 backtick 先转 `$(...)`（shlex 不视作引号，`echo \`cmd\`` 会漏），`<(cmd)/>(cmd)` process substitution 递归抽出 body 单独段（`policy.py:296-362`）。

3. **unwrap wrapper**：`env/nohup/time/timeout/nice/xargs/setsid/...` 与前置 `VAR=val` 都要跳过后再看真命令（`policy.py:279-283、413-436`）。否则 `env FOO=1 nohup rm -rf /` 会被认成 `env`。

4. **flag 簇展开匹配**：`rm -rf` / `rm -r -f` / `rm -R -f` / `rm --recursive --force` 都要命中；`_has_flag(letters)` 把短 flag 拼起来再看包含（`DeepCode-main/core/harness/command_guard.py:61-88、_is_recursive_force_rm`）。

5. **redirect 目标单抽**：`>` `>>` 目标另算，`2>&1`/`>&-` 这类 fd dup 排除（`CowAgent-master/agent/permission/policy.py:439-454`；`_NULL_SINKS` 里 `/dev/null /dev/stdout /dev/stderr /dev/tty NUL` 等不算写文件，见 285-288）。

6. **allowlist 命令的"写形态"flag**：`find -delete / -exec`、`sed -i / 'w out.txt'`、`sort -o / --output`、`xxd -r`、`awk system()`——`_READ_ONLY_WRITE_FORMS` 精确列出（`policy.py:174-194、706-726`）。

7. **git 单独一层**：sub-command 白名单 + write-flag 黑名单 + `git branch v1` vs `git branch -l`、`git config` 无 `--get/--list` 一律视为写（`policy.py:787-832`）。

8. **unparsable fail-closed**：CowAgent `_check_bash_read_only` 明确"this command could not be parsed, and an unparsable command cannot be confirmed read-only"（`policy.py:736-741`）；DeepCode `screen_command` 遇 ValueError 不猜、跳过、交给沙箱（`command_guard.py:151-155`）——**read-only 判定 unparsable = deny**；**screen 层 unparsable = 交给沙箱**（沙箱是边界）。

→ **03 §3/§4 建议加一段"shell 命令解析（Harness 侧）"**，明确："denylist 是 argv 匹配不是子串；沙箱是边界，screen 是 best-effort defense-in-depth；unparsable 在 read-only 判定=fail-closed deny、在 destructive screen=交给沙箱"。

### 3.5 增量：`reason` 是给模型的（errors-as-data）

DeepCode `_evaluate` docstring："when a call is denied the kernel surfaces it back to the model as the tool result (errors-as-data), so it must explain *why* and hint a legal path"（`DeepCode-main/core/harness/permissions.py:318-323`）。
CowAgent `_switch_hint`：`"Do not retry the same call: use a route the current mode allows, or tell the user which mode is needed."`（`CowAgent-master/agent/permission/policy.py:570-584`）。

→ **03 §5 建议**：ToolCall 的 `permission_decision` 结构里加 `reason`，明确"面向模型可读、给出合法替代路径"。

### 3.6 增量：`describe_mode` 注入到 prompt

CowAgent `describe_mode(mode, language, cwd)`：返回一段"当前会话能改什么/不能改什么/该怎么提示用户"的 markdown，塞进 system prompt（`policy.py:929-982`）；full-access 返 `[]`，"the historical prompt stays byte-identical"。

→ **03 §7 建议**：mode 变更要产 `mode_changed` 事件，并让策略层在下一 turn 拼 prompt 时能取到**该 mode 的模型可读描述**（Harness 侧提供 `describe_mode(mode, locale)` 只读方法）。

### 3.7 参考：CowAgent 的 mode aliases

`_ALIASES`：`ro/readonly/workspace/full/danger-full-access/all` 等映射到规范 id（`policy.py:51-64`），`normalize_mode` 兜底 DEFAULT_MODE。**.quest 也需 aliases**，用户写 `danger-full-access` 或 `ro` 都能识别——工程细节。

---

## 4. 沙箱：可插拔 + 降级（03 §4/§10 T4）

### 4.1 增量：后端能力矩阵——不是"有沙箱=全围栏"

DeepCode 三后端的**能力差异**（`DeepCode-main/core/harness/sandbox.py:1-38、416-426`）：

| 后端 | 写围栏 | 网络门 | 进程树隔离 |
|---|---|---|---|
| macOS seatbelt (`/usr/bin/sandbox-exec`) | ✅ (deny-default + 白名单) | ✅ (仅 allow_network=True 才放开) | — |
| Linux bwrap | ✅ (`--ro-bind / /` + `--bind root root`) | ✅ (`--unshare-net`) | ✅ (`--die-with-parent`) |
| Windows Job Object | **❌**（不 fake 写围栏） | ❌ | ✅ (`KILL_ON_JOB_CLOSE`) |
| none | ❌ | ❌ | ❌ |

关键："The Job Object backend **intentionally does not** fake it — it provides process-tree isolation and leaves write restriction to explicit approval."（`sandbox.py:21-28`）；`fences_writes()` 显式返 bool（同 423-425）。

→ **03 §4 建议**：`SandboxPort` 增加能力探针 `fences_writes() / fences_network() / isolates_process_tree() -> bool`；上层**依能力组合**决定"是否需要额外审批"（如 Windows 无 write fence → write 类工具走 ask）。

### 4.2 增量：**PATH 注入防御**——绝对路径调用后端二进制

`_MACOS_SANDBOX_EXEC = "/usr/bin/sandbox-exec"` 而非走 PATH 解析（`DeepCode-main/core/harness/sandbox.py:48-49`）——原文注释："referenced by its absolute path to defend against PATH injection"。

→ **03 §4 建议加**："沙箱后端二进制必须走绝对路径 or verified lookup，禁止 `shutil.which` 后直接使用"（`bwrap` 是唯一例外，见下）。

### 4.3 增量：seatbelt 是 **deny-default** 不是 allow-default

`_SEATBELT_BASE_POLICY` 起手 `(deny default)`，Chrome-inspired，再白名单 regrant：`process-exec/process-fork/signal same-sandbox/pty/cfprefs/…`；文件"broad read + 特定 subpath write + optional network"（`DeepCode-main/core/harness/sandbox.py:90-213、234-259`）。

→ **03 §4 建议加一句**："沙箱策略基线：**deny-default + 显式 regrant**；不允许 allow-default + 剔除。"

### 4.4 增量：**降级语义**三家分别

- DeepCode `wrap_shell_command` 无后端时：**原样返回 argv**，`backend="none"`，由 caller 决定"approval-first"（`sandbox.py:30-34、336、435`；`describe_backend()` 直白写"no sandbox (degraded: approval-first)"）。
- DeepCode Full Access 预设：**同时关掉 sensitive-path 与 sandbox**（`policy.py:204-210`）。
- 03 §10 T4 现写"无可用后端时 exec/high 风险工具**直接 deny**"——**比 DeepCode 更严**。这不是错，但要显式说明："**questor 走的是 T4 严于 DeepCode approval-first** 的策略；原因是桌面 agent 一旦 exec 无围栏=RCE 面"。

→ **03 §4/§10 建议**：把"无后端"拆两档：
  - `backend=none`：exec/high → **deny**（T4）；write/medium → ask + warning；readonly → allow（受 workspace 边界约束）。
  - `backend=job`（Windows）：写工具**额外走 ask**（因 job 无 write fence）；readonly/网络按能力矩阵放行。

### 4.5 增量：**shell-string 与 argv-list 分别 wrap**

DeepCode 提供 `wrap_shell_command(command, policy)` 与 `wrap_argv_command(inner_argv, policy)`（`sandbox.py:291-352`）；`build_exec_command(command=|argv=)` 二选一，`raise ValueError` if both/neither（同 399-400）。

→ **03 §4 建议**：`SandboxPort.wrap` 签名拆两个（`wrap_shell / wrap_argv`）；上层不允许"传 shell 字符串伪装成 argv"（防注入）。

### 4.6 缺口：**子进程 env 的 credential scrub**——03 完全未提

DeepCode `env_sanitize.py` 专门处理：**父进程环境有 live provider credentials**（.env 被 MCP 服务器加载并 `os.environ[k]=v` 回写）→ 子进程默认继承 → 子 stdout 里 `env` 一句就泄漏进下一轮 prompt → 第三方 relay 明文可读。

**规则**（`DeepCode-main/core/harness/env_sanitize.py:14-33、50-58`）：
- 只擦 `KEY|PASSWORD|SECRET|TOKEN` 形状名（`PATH/HOME/locale/proxy` 保留，不影响子进程运行）；
- 对**外部 agent CLI**：默认擦；
- 对**agent 自己的 shell / hooks / code-mode**：**默认不擦**（`gh/aws/huggingface-cli` 从 env 读 token，硬擦会让日常协作崩），除非 `DEEPCODE_BASH_SCRUB_ENV=1`；
- `DEEPCODE_BASH_FULL_ENV=1` 显式覆盖；
- 真正需要传的凭据**显式**通过 `extra_env` forward，"forwarding a secret becomes a deliberate act"。

→ **03 应新开一节 §11 "子进程 env"**（当前 03 §2/§8 都没写）：
  - 默认：对 exec 类工具**擦 credential-shaped env**；
  - 显式：`ctx.declare_env_passthrough(name)` 让工具**主动申报**要 forward 的 env（对齐 DeepCode 的 `extra_env`）；
  - 记审计：`env_scrubbed` 写进 ToolCall（对齐 01 §4 账本）；
  - 提示：provider credential **永不**给 exec 子进程默认继承。

---

## 5. MCP：进程模型 + 复用同一权限/账本（03 §6）

### 5.1 增量：MCP 服务器进程模型的**具体形状**

03 §6 只写"DeepCode 式工具=独立 server 进程"，缺实现级要点。DeepCode `McpConnection`：

- **一 server = 一个专属 task 拥有 transport**：`_serve()` 里 AsyncExitStack 进入 stdio_client/http client/ClientSession，`self._session` 就绪后 `_ready.set_result`；`close()` 通过 `self._close_event.set()` 让 `_serve` 走 exit-stack 有序退出（`DeepCode-main/core/mcp/connection.py:33-42、116-205`）。
- **tool 调用走 child task**，独立 timeout 与取消：`call_tool` 里 `asyncio.create_task(session.call_tool(...))` + `asyncio.wait_for(call, timeout=definition.tool_timeout_seconds)`；`_active_calls` 集合便于 close 时逐个 cancel 再 gather（`connection.py:92-114、120-125`）。
- **transport 三绑**：`stdio_client` / `sse_client` / `streamable_http_client`；plugin 源不跟 redirect（防跨 origin 头外泄），user/project 源保留（`connection.py:206-271`）。
- **env 装配三类**：`env` 字面 / `env_vars` 从父 env 转发 / `required_env_vars` 缺失即 `McpConfigurationError` / `credential_env` 走 `credential_resolver`（`connection.py:273-296`）。**MCP server 的 env 是"选择性白名单"而非继承**——与 §4.6 的 scrub 是两个方向。
- **占位符**：`${workspace}` `${configDir}`；plugin 额外 `${PLUGIN_ROOT}` `${PLUGIN_DATA}`；未识别占位符非 plugin 场景**抛错**（`connection.py:460-484`）。
- **plugin 沙箱化**：`_require_contained`：`command` 与 `cwd` 必须**位于 plugin_root/plugin_data 之内**，逃逸即拒（`connection.py:395-408、435-457`）。
- **stderr 落盘**：`_open_stderr_log` 写 `~/.deepcode/logs/mcp/<server_id>.log`（`connection.py:493-506`）。
- **上限**：`MAX_DISCOVERED_TOOLS/Resources/Prompts = 256`，超限 raise 拒爆上下文（`connection.py:27-29、360-392`）。
- **instructions 截断**：4000 chars（`connection.py:487-490`）。

→ **03 §6 建议**：把上述七条列入"MCP 适配（P5）验收清单"；尤其"**一 server 一 task 拥有 transport / tool 调用独立 child task / env 是白名单不是继承 / 上限 256 / plugin 目录 containment**"——这五条不做，P5 上线一定翻车。

### 5.2 增量：**MCP 工具映射到同一 ToolSpec 的字段**

`McpToolAdapter`（`DeepCode-main/core/mcp/tools.py:23-123`）：
- `name = visible_name`（`mcp_<server>_<tool>` 命名，见下 5.3）；
- `description = sanitize_description(remote, max_chars=8000)`（同 §1.3）；
- `parameters = normalize_schema_for_openai(inputSchema)`；
- `read_only = annotations.read_only`（**hints not grants**，缺省视作 mutating）；
- `concurrency_safe = server.supports_parallel_tool_calls`（**per-server 声明**）；
- `approval_mode = server.policy_for(raw_name)`（**per-tool**，见 §1.2）；
- 返回 `ToolResult(text, is_error, metadata={origin:"mcp", serverId, serverName, toolName, source, readOnly, approvalMode})`——**走同一 ToolResult 契约**。

→ **03 §6 建议**：MCP 工具映射表逐字段贴出来；强调"`isError=true` 视作 error ToolResult、`metadata.origin` 供后续审计"，对齐 01 §4 ToolCall 账本字段。

### 5.3 增量：命名与 bare-name 匹配

DeepCode `permissions.is_read_only` 对 `mcp_` 前缀特殊处理："MCP names embed both a server and a tool name, each may contain underscores/dashes, so a single 'bare name' split is ambiguous. **Match by suffix**"（`DeepCode-main/core/harness/permissions.py:201-208`）——即"结尾是已知只读名"就视作只读。

→ **03 §6 建议**：MCP 命名规范（`mcp_<server>_<tool>` 或等价）；rules/denylist 匹配 MCP 时**按 suffix**，不做 split。

### 5.4 增量：**账本复用**：MCP 走同一 ledger 是硬约束

DeepCode McpToolAdapter 只返回 `ToolResult`；ledger 记录在 agent loop（`kernel`）层，**不是 MCP 层**——这保证 MCP 与内置工具账本同源。此外有**辅助** MCP 专属 observability：`log_mcp_call(server, tool, duration_ms, status, arguments, result, error)`；"telemetry never changes tool outcome"（`DeepCode-main/core/mcp/tools.py:146-166`）。

→ **03 §6 建议**：明确"MCP 调用**必须**经同一 Harness 工具路由写入 01 §4 `ToolLedger`；`observability.log_mcp_call` 是**补充**不是替代"——否则审计会漏 MCP。

---

## 6. 并行与取消（03 §8/§10 T2）——工程细节最硬的一段

### 6.1 增量：**并发 gate**（不是"能并行就并行"这么简单）

wuu `ToolExecutionGate`（`wuu-main/internal/agent/tool_gate.go`）是**读写锁风格**的自定义 gate：

- `capacity`：并行读的最大槽数；
- `shared=ConcurrencySafe`：可共享，走读侧；
- `shared=false`（unsafe write）：**独占**（`g.active==0` 才能进）；
- **`waitingWriters`**：writer 排队时新的 reader **不再插队**，防 writer 饿死（`tool_gate.go:11-13、40`）；
- **orchestrator 不 acquire gate**：原文："Orchestrators do not acquire it: holding a leaf slot while awaiting children **deadlocks at capacity**"（`tool_gate.go:9-12`；`tool_runtime.go:345-348`）——**嵌套/子代理角色绕开 gate**。
- ctx 取消时，等待中的 writer 递减 `waitingWriters` + signal（`tool_gate.go:32-39`）。

→ **03 §8/§10 T2 建议**：加一段"并行 gate 语义"：parallel_safe=true → 走 reader 共享；false → writer 独占；writer 有饥饿保护；orchestrator/subagent **不参与 gate**（否则死锁）。这是 P2 之后必踩的坑。

### 6.2 增量：**返回顺序 = 模型请求顺序**（不是完成顺序）

wuu `executeBatch`：并行分支先 `runs[i] = startRunLocked(call[i])`，再 `for i, call: msgs[i] = awaitRunResult(runs[i])`——**按下标写回**（`wuu-main/internal/agent/tool_runtime.go:674-701`）。串行分支同结论。

→ **03 §10 T2** 现在只写"客户端靠 tool_call_id 归组"。**服务端也必须**按模型请求顺序产出 tool_result 序列（否则 provider 会因 `tool_use/tool_result` 配对错位 400）——**这是 01 §2 配对不变式的具体落点**。

### 6.3 增量：激流早启动（streaming eager start）

wuu `ObserveStreamEvent`：`EventToolUseStart/Delta/End` → 累积 args；`finalizeStreamTool` 后 `startReadyStreamPrefixLocked`：从 `runs[0..]` **顺序扫**，遇到 `!streamSafe` 立即停；否则 `startRunLocked(ctx, run, streamStarted=True)`（`wuu-main/internal/agent/tool_runtime.go:120-143、222-269`）。`streamSafe = ReadOnly && ConcurrencySafe`（同 884-894）。

配合 `RunContext`：**stream 观察 ctx 一 close 就 cancel**（哪怕成功），但 stream-started 的工具要跑到 final batch，所以 tool 执行 ctx 从 `r.runContext` 派生而非观察 ctx（`tool_runtime.go:76-83、294-297`）。

→ **03 §8 建议**：可作为 P2+ 优化点标出："对**只读+可并行**的工具，args 完整即可提前起，不等 turn 收尾"；关键约束：**tool 执行 ctx ≠ stream 观察 ctx**（否则流关闭即工具中断）。

### 6.4 增量：**账本 settle 必须脱离取消链**

wuu `finish()` 里 `r.ledger.Settle(context.WithoutCancel(runCtx), invocationID, result)`（`wuu-main/internal/agent/tool_runtime.go:329`）。原文语义：run ctx 已取消时，**settle 仍要落账**（不然 §2 配对不变式、§5 账本都会撕裂）。

→ **03 §5/§8 建议**：**加一句硬约束**："取消/超时瞬间，账本落账必须以**脱离取消链**的 ctx 写入；否则未闭合 tool_use 会撕裂 01 §2 配对不变式。"（对应 C7 reduce 不变式。）

### 6.5 增量：**取消源四类**

wuu `tool_nested.go:38-42` 原文：`// Both the owner and this invocation can cancel a child; neither can keep it alive after the other has ended. **Observation detachment is separate.**`

四类：
1. **owner cancel**（父 run/turn 结束）；
2. **invocation cancel**（本次调用超时/被拒）；
3. **user cancel**（Cancel Command，见 C7）；
4. **observation detach**（SSE 观察断开、但**任务不终止**——后台继续跑）。

DeepCode `McpConnection.call_tool` 的 `asyncio.wait_for` 只处理 invocation timeout；`close()` 才 cancel 所有 active calls（`DeepCode-main/core/mcp/connection.py:98-114、120-125`）——把"观察 detach vs invocation cancel"分得很开。

→ **03 §8 建议**：明确取消四类，尤其"**观察 detach 不终止执行**"这条对桌面/IM 通道断连的场景是硬需求；02 §5 的 Cancel Command 也应区分 `reason ∈ {user, timeout, safety, owner}`。

### 6.6 增量：嵌套调用的**边界与身份**（为 01 §3 subagent 预留）

wuu `nestedToolScope.Invoke`：
- `depth >= 8` 拒（`tool_nested.go:35-37`）；
- **call ID 复用要 `(name, args, kind)` 三元一致**，否则"nested call ID reused with different arguments"（同 60-64）；
- per-scope `len(s.calls) >= 1024` 上限（同 66-70）；
- **绝不信任 child 的本地 key**：global ID 重生成 `"nested-" + rand.Text()`（同 71-73）；
- child run 从 `s.ctx` 派生，父/子 cancel 各自挂 `context.AfterFunc`。

→ **03 §6 建议**：v1 subagent 只预留结构；把"深度上限 / ID 复用检测 / 本地 key 不可信"作为 subagent 编排落 P8 时的**硬边界清单**贴进去。

### 6.7 增量：barrier tool（同 batch 独占）

wuu `rejectBarrierToolBatch`：一批 calls 里若含 barrier 工具，整批拒（"must be called alone"）；当前 `isBarrierTool = false`（stub），但机制在（`tool_runtime.go:467-553`）。

→ **03 §8 建议**：ToolSpec 可选加 `barrier: bool = false`；v1 stub，P2 若有此类工具（如 `undo_checkpoint`）启用。

---

## 7. 工具实现接口（03 §2）的小校准

### 7.1 `ToolResult{status, result, display}` 与三家一致

CowAgent 明确注释："`result` is what the model reads, so it is written for a model: JSON, exit codes, whatever parses cleanly. `display` is the same outcome written for a person"（`CowAgent-master/agent/tools/base_tool.py:12-19`）——03 §2 的 result/display 拆分与参考实现完全对齐。

wuu `toolresult.Result` 有 `TextProjection()`（给模型）与 `Clone()`（避免共享）；`executeToolResult` 出口调 `result.Validate()`——**结果也需一次结构校验**（`wuu-main/internal/agent/tool_runtime.go:726-745、849-851`）。

→ **03 §2 建议**：加一句"`ToolResult` 出工具前须通过结构 self-validate；`result`/`display` 分道由 Harness 保证"。

### 7.2 ctx 只给受控能力：`tool_call_id / cwd / progress / event / is_cancelled / StorePort`

CowAgent `BaseTool.tool_call_id / cwd / progress_callback / cancel_event / event_callback`（`base_tool.py:93-102`）——**per-call 由 agent loop 注入**，与 03 §2 一致。

wuu `toolctx.WithStepIndex / WithNestedCall / WithNestedExecutor`（`tool_runtime.go:300、343-348`）—— **ctx 是 typed keys 的 context**，工具只能拿声明的字段。

→ **03 §2 建议**：明确 `ctx` 提供 `tool_call_id`（emit_event 归属）与 `cwd`（相对路径解析）——03 现在只列了 workspace 根。

### 7.3 Panic/exception **不能带崩进程**（C10）

wuu `executeToolResult` 的 `defer recover()`：`err = tool panicked: %v; result = toolresult.FromErrorText(errorJSON(err))`（`wuu-main/internal/agent/tool_runtime.go:833-838`）；`KeyboardInterrupt/SystemExit` 例外**不吞**（DeepCode MCP adapter 同 `DeepCode-main/core/mcp/tools.py:91-92`）。

CowAgent `execute_tool`：`except Exception → ToolResult.fail(f"Error: {type(e).__name__}: {e}")`（`base_tool.py:182-191`）——异常转 fail，绝不冒泡。

→ **03 §2/§8 建议**：把"工具异常/panic 一律转 error ToolResult，键盘中断/系统退出例外"写进 §2 契约（与 HARD-CONSTRAINTS C10 呼应）。

---

## 8. 缺口清单（03 现在**没覆盖**、实现期一定会撞）

按优先级：

- **G1（阻断级）shell 命令解析层**（详见 §3.4）：arg-key 词典 + shlex 切段 + wrapper unwrap + flag 簇展开 + redirect 抽取 + unparsable fail-closed。**03 只写了"denylist 不可覆盖"，没写"如何可靠命中 denylist"**。
- **G2（阻断级）子进程 env 处理**（§4.6）：默认 scrub / 显式 forward / 审计。**03 完全没有这一节**。
- **G3（高）评估次序与 rules 数据结构**（§2.3、§3.2）：sensitive-path → read-only 上限 → rules(last-wins) → mode 兜底；rules 是 `(permission, pattern, action)` 二维通配。**03 §3/§4 只写了"三态+denylist"两概念**。
- **G4（高）并行 gate 语义**（§6.1）：reader/writer 槽、writer 饥饿保护、orchestrator 绕 gate。**03 §8/§10 T2 只说"parallel_safe"一个 bool**。
- **G5（高）账本落账脱离取消链**（§6.4）。**03 §5/§8 未提**。
- **G6（中）MCP 进程模型 7 条验收**（§5.1）。**03 §6 只一句"DeepCode 式"**。
- **G7（中）沙箱后端能力矩阵**（§4.1、§4.2）：fences_writes/fences_network/isolates_process_tree 三个探针 + 绝对路径调用后端。**03 §4 只列了后端名单**。
- **G8（中）审批回复不得提权**（§3.2 wuu HardDenyReason）+ **mode aliases**（§3.7）。
- **G9（中）approval_policy=never → ASK 降 DENY**（§2.4，headless fail-closed）。
- **G10（低）streamSafe 激流早启动**（§6.3）+ **barrier tool**（§6.7）——P2+ 优化。
- **G11（低）ToolSpec description 长度上限 + untrusted sanitize**（§1.3、§5.2）。
- **G12（低）嵌套/子代理的 depth/ID/calls 上限**（§6.6）——P8 预留。

---

## 9. 建议落到 03 的**补丁段**（可直接抄改；本节只列**新增/改写**，未列的段落不动）

### 9.1 §1 ToolSpec 字段增补

```
ToolSpec {
  name, description,               # description 有 max_chars 上限（MCP 类 8000）
  params: JSON-Schema,
  capability: readonly|write|exec|network|memory,
  risk: low|medium|high,
  read_only: bool,                 # 权威布尔；缺 metadata 视作 false（fail-closed）
  parallel_safe: bool = false,
  orchestrator: bool = false,      # 嵌套/子代理角色；不参与 gate
  barrier: bool = false,           # 同 batch 独占（P2 可选）
  approval_mode: auto|approve|prompt|writes? = None,   # MCP 类工具的"再收紧"位；只能加严不能加宽
  available(): bool,
  lifecycle.close()?,              # 释放句柄（对齐 C10）
}
```

### 9.2 §2 ctx 增补与 self-validate

- `ctx.tool_call_id`（emit_event 归属）；`ctx.cwd`（相对路径解析）；`ctx.declare_env_passthrough(name)`（见新 §11）。
- `ToolResult` 出工具前**必须 self-validate**；Harness 视作 error ToolResult。
- 工具异常/panic → 一律转 error ToolResult；**KeyboardInterrupt / SystemExit 例外**（透传）。

### 9.3 §3 拆五层校验（替换现有两条）

1. **JSON 合法性**：args 非合法 JSON → 直接拒绝（不进工具、不进业务校验）。
2. **schema 校验**：按 `params` JSON-Schema 校形状/类型；可选**一层通用 coerce**（整数写成字符串的常见情形）。
3. **参数字典抽取**（Harness 侧）：按 `_PATH_ARG_KEYS / _SHELL_TOOL_KEYS / _ACTION_ARG_KEYS` 与 apply_patch 类"结构化 envelope 里的路径"，抽出路径/命令/动作三段。词典属 L0 contracts。
4. **权限判定**：见 §4 求值次序。
5. **业务校验**：**在工具 execute 内**，纯函数、不下沉沙箱（保留现有铁律）。

### 9.4 §4 权限求值次序（新小节）

```
1. 提权拦截         → 审批回复不得携带 mode 提权字段；命中即 DENY
2. sensitive-path denylist → 规范化路径(realpath+expanduser+evalsymlink)匹配、不可被 rules/mode 覆盖
3. roots 内二次保护 → mcp.json/config.json/credentials 类，即使命中 workspace 也 DENY
4. read-only 上限    → enforce_read_only=True 时 mutating 工具 DENY
5. rules last-match-wins → 二维通配 fnmatch(permission × argument-pattern)
6. mode 默认         → {default: mutating ask; plan: mutating deny; full_auto: allow}
7. approval_policy=NEVER 时 ask 视作 deny（headless fail-closed）
8. MCP approval_mode 组合：只能把 allow 收紧为 ask/deny，不得放宽；unknown → DENY
```

`reason` 面向模型可读：给出"为什么拒 + 合法替代路径"；**不重试同一 call** 是 reason 的一部分。

### 9.5 §4 沙箱：能力矩阵 + deny-default

`SandboxPort` 增探针：`fences_writes() / fences_network() / isolates_process_tree() -> bool`；`describe_backend() -> str`。

后端**必须**用绝对路径或 verified lookup 调二进制（防 PATH 注入）；策略基线 **deny-default + 显式 regrant**，禁 allow-default。

**降级矩阵**（替换 §10 T4）：

| backend | write-fence | net | proc-tree | 上层降级 |
|---|---|---|---|---|
| seatbelt | ✅ | ✅ | — | 按 capability 表 |
| bwrap | ✅ | ✅ | ✅ | 按 capability 表 |
| job (Windows) | ❌ | ❌ | ✅ | write 类**加严走 ask**；readonly 允许 |
| none | ❌ | ❌ | ❌ | exec/high → **deny**（T4）；write → ask+warn；readonly → allow(workspace) |

### 9.6 §5 账本：`permission_decision` 结构 + settle 铁律

`ToolCall.permission_decision = {decision, reason, decided_by: rule|denylist|mode|user, at}`（对齐 01 §6）；`ToolCall.env_scrubbed: list[str]?`（见新 §11）。

**落账铁律**（新加）：取消/超时/panic 时，账本 settle **必须用脱离取消链的 ctx** 写入，保证 `tool_use/tool_result` 配对不变式（对应 C7 reduce 不变式）。

### 9.7 §6 MCP 适配验收清单（P5）

进程模型 7 条（对齐 §5.1）：
1. 一 server 一专属 task 拥有 transport；tool 调用走独立 child task（单独 timeout/取消）。
2. transport 三绑 stdio / sse / streamable-http；plugin 源不跟 redirect。
3. env 是**白名单装配**（字面 / 转发 / 必需 / 凭据引用四类），非继承父进程。
4. 占位符 `${workspace}/${configDir}`（plugin 加 `${PLUGIN_ROOT}/${PLUGIN_DATA}`）；未识别占位符抛错。
5. plugin 的 `command`/`cwd` 必须 containment 在 plugin 目录内，逃逸即拒。
6. stderr 落盘到独立日志；发现上限 256（tools/resources/prompts），超限拒接。
7. 映射到同一 ToolSpec：`read_only`=annotation 是 hint 非 grant（缺省视作 mutating）、`parallel_safe` 由 server 声明、`approval_mode` 只收紧不放宽、命名 `mcp_<server>_<tool>` 且 rules 按 **suffix** 匹配。

**账本**：MCP 调用**必须**走同一 Harness 工具路由写 `ToolLedger`；`observability.log_mcp_call` 是补充非替代。

### 9.8 §8 并行 gate 语义 + 取消四源

- **gate**：`parallel_safe=true` → reader 共享（上限 capacity）；`false` → writer 独占；**writer 饥饿保护**（排队 reader 不再插队）；**orchestrator/subagent 不 acquire gate**（否则 await 子节点死锁）。
- **无 gate 支持时降级**：`parallel_safe` 一律视作 false → 串行（对齐 §4.4 降级同 philosophy）。
- **返回顺序**：服务端产出 tool_result 序列**=模型请求顺序**（不是完成顺序），保证 01 §2 配对。
- **取消四源**：owner / invocation（本次超时或被拒）/ user（Cancel Command）/ observation-detach（SSE 断开但后台续跑）。02 §5 `Cancel.reason` 补 `owner`。

### 9.9 §10 落地补充：把 T4 与 §3.2/§4.1 缝合并存

现 T4 "exec/high 无沙箱直接 deny" 保留，但**注明比 DeepCode approval-first 更严的理由**（桌面 RCE 面）；Windows Job（有 proc-tree 无 write-fence）按 §9.5 表格"write 加严走 ask"，不套用 exec-deny。

### 9.10 新增 §11 子进程环境（env）

- **默认 scrub**：exec/write 类工具 spawn 的子进程，剥离 credential-shaped env（`KEY|PASSWORD|SECRET|TOKEN` 正则），保留 `PATH/HOME/locale/proxy`。
- **显式 forward**：工具经 `ctx.declare_env_passthrough(name)` 主动申报；Harness 记 `ToolCall.env_scrubbed` 供审计。转发凭据=deliberate act。
- **provider 凭据**：**永不**默认给 exec 子进程继承（防 stdout→prompt→第三方 relay 明文泄漏）。
- **MCP server 例外**：其 env 走 §9.7 第 3 条白名单装配，与本节 scrub 是两个方向（MCP 需要凭据时经 `credential_env` 显式取）。

---

## 10. 保留待定（v0 后锁，对齐 03 §9）

- shell 命令解析层（G1）落 L0 还是 L2：词典进 `contracts`、解析器进 `kernel`；denylist 命中策略随能力矩阵定。
- `capability` 与 `read_only` 布尔是否冗余：建议 capability 保留（分类/默认风险档），`read_only` 作权威布尔覆盖，二者不冲突（DeepCode 即如此）。
- `barrier`/`orchestrator` 是否 v1 就进 ToolSpec：orchestrator v1 只占位（对齐 01 §3 subagent）；barrier 可推迟 P2。
- env scrub 的默认开关：桌面 vs CLI 不同；Copilot 场景 `gh` 需 env token，是否默认 opt-in（学 DeepCode）。

---

## 附录 A · 文件行号速查（证据锚点）

**DeepCode-main**
- `core/harness/permissions.py:26-30` 评估次序 · `:49-59` 三态/三 mode · `:66-89` sensitive 清单 · `:92、151、93-98` arg-key/shell/patch 前缀 · `:123-138` 二维通配 last-wins · `:201-208` MCP suffix 匹配 · `:232-242、141-148` 路径规范化 · `:269-309` MCP 只收紧不放宽 · `:318-323` reason 面向模型 · `:384-404` NEVER→deny
- `core/harness/policy.py:41-54` mode 解析 env>config>default · `:132-174` describe_security_posture(unattended 判定) · `:204-210` Full Access 同关沙箱+denylist
- `core/harness/approval.py:49-107` TerminalApprover(y/n/always、非交互 fail-closed)
- `core/harness/sandbox.py:1-38` 三后端边界 · `:48-49` 绝对路径防 PATH 注入 · `:90-213` deny-default seatbelt · `:291-352` wrap argv/shell · `:416-425` fences_writes 能力矩阵 · `:428-436` describe_backend
- `core/harness/windows_sandbox.py:1-30、122-186` Job Object KILL_ON_JOB_CLOSE 仅进程树
- `core/harness/command_guard.py:1-34` "screen 不是边界、沙箱才是" · `:58、147-160` 切段+shlex · `:61-129` flag 簇分类 · `:132-162` unparsable 交沙箱 · `:445-500` egress · `:578-654` typosquat/edit-distance
- `core/harness/env_sanitize.py:1-33、50-58` credential-shaped scrub · `:75-111` extra_env 后置合并
- `core/mcp/connection.py:33-42、92-114、116-205` task 拥有 transport/child-call/close · `:206-296` transport 三绑+env 白名单 · `:360-392` 上限 256 · `:395-457` plugin containment · `:487-506` instructions 截断+stderr 落盘
- `core/mcp/tools.py:23-123` McpToolAdapter 字段映射 · `:56` approval_mode · `:70-74` read_only hint-not-grant · `:80-84` 不暴露 raw args · `:146-166` log_mcp_call 遥测

**wuu-main**
- `internal/agent/tool_gate.go:8-20` RW gate/writer 饥饿 · `:9-12` orchestrator 不 acquire · `:26-65` acquire 主体
- `internal/agent/tool_runtime.go:27-45` toolRun 字段 · `:76-83` RunContext 解耦观察 ctx · `:120-143、222-269` 激流早启动 · `:329` settle WithoutCancel · `:349-354` gate acquire · `:434-465、674-701` 返回=请求顺序 · `:467-553` barrier · `:579-643` registerFinalCalls 孤儿取消 · `:820-853` JSON 校验+panic recover+result.Validate
- `internal/agent/tool_nested.go:35-37` depth≤8 · `:60-64` ID 复用检测 · `:66-70` 1024 上限 · `:71-73` 不信 child key · `:38-49` owner/invocation cancel 双向
- `internal/approvefor/review.go:62-85` NeedsReview(shell 一律 review，read-only 非保证) · `:88-101` HardDeny(凭据/mode 提权/sensitive 写) · `:121-141` EvalSymlinks 二次判定

**CowAgent-master**
- `agent/tools/base_tool.py:12-34` result/display 分道 · `:57-67` is_available err-toward-offer · `:70-81` renders_own_cards · `:86` stage pre/post · `:93-108` tool_call_id/cwd/parallel_safe 注入 · `:133-166` is_cancelled/report_progress/emit_event · `:182-207` 异常转 fail + 整数 coerce
- `agent/permission/policy.py:39-64` 三 mode + aliases · `:109-140` 工具分类/_MUTATING_NAME_RE · `:149-276` shell 白名单/写形态/git/escalation · `:292-397` 切段+backtick+process-subst · `:413-436` wrapper unwrap · `:439-475` redirect/positional · `:482-527` realpath/protected · `:553-588` deny+switch_hint · `:630-664` read-only 判定(unparsable=deny) · `:667-693` workspace-write(roots 内仍保护) · `:787-832` git 细分 · `:929-982` describe_mode prompt
