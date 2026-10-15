# R07 · 插件宿主 / 端口抽象 / Sidecar 进程边界（外部参考扫描）

> **用途**：为打磨 [`../STRUCTURE.md`](../STRUCTURE.md)（§2 providers、§3 desktop sidecar、§7-S5 进程边界）与 [`../design/00-layering.md`](../design/00-layering.md)（§2 L5 Ports + 横向"DI/插件宿主(cordis式 Fiber)"、§3 可插拔注册点表）供证据。
> **只提增量与缺口**，不重述 questor 已定内容。读全三家：`cordis-main`（core fiber·registry·context·events + hmr·loader·include）、`DeepCode-main`（desktop/ sidecar + app_server 协议 + providers）、`wuu-main`（internal/providers + packages/plugin-go + cmd）。
> **一切结论带 `文件:行号`**；行号为扫描时快照，作定位用，不作契约。三家均为 TS/Python/Go 异栈，**借鉴的是机制模型，不是逐行照搬**。

---

## 0. 一页结论

| 主题 | 三家给的成熟做法 | questor 现状 | 本报告建议 |
|---|---|---|---|
| **providers 端口抽象** | 最小口 + 可选能力接口（wuu）/ 抽象基类 + 三态能力旗标 + 前置校验（DeepCode） | 00 §2 L5 只写 `ProviderPort→LiteLLM`；03 只覆盖 ToolSpec | contracts 定形：基础推理口 + 声明式 capability flags + 可选能力子接口 + provider 元数据注册表（含信任分类、fail-closed） |
| **能力热插拔生命周期** | cordis Fiber 6 态 + `effect` 作用域反向 dispose + 依赖驱动自动重载 + HMR 三段"先验证后交换" | 00 §3 表有一行"能力热插拔(后期) cordis式 Fiber"；C10 只给"故障隔离+回滚边界" | 把 Fiber 语义落成 questor 插件生命周期契约（init/load/unload/reload + 依赖图重挂载）；HMR 三段回滚补进 C10；ROADMAP P9 落地口径 |
| **Python↔Rust sidecar 进程边界与打包** | DeepCode：PyInstaller **onedir** + 隔离 build venv + 构建期 `_verify_bundle`（导入探针 + initialize/shutdown RPC smoke）+ SidecarPhase 状态机 + 分层 launch-spec + generation-guard 重连 + 两级优雅关闭；stdio newline-JSON-RPC | ADR-0007 定 **HTTP+SSE**；STRUCTURE §3/§7-S5 只写"sidecar + 只经 HTTP+SSE、禁进程内直调" | §3 补"打包+构建期自检+生命周期"清单；§7-S5 补"sidecar 定位顺序 / 端口分配+就绪探测+token / 崩溃重连续传"；把 stdio-JSON-RPC 作**备选并说明取舍** |

**一句话**：questor 的分层纪律没问题；缺的是**端口形状、插件生命周期状态机、sidecar 进程边界与打包这三处"可落地的具体语义"**。三家恰好把这三块各自做到了工业级，直接抄模型、改栈即可。

---

## 1. cordis —— 能力热插拔生命周期（DI / 生命周期 / 热重载）

cordis 是"服务声明依赖 + 生命周期 + 可热重载"的宿主层，与 agent 逻辑正交（见 00 §1 表 cordis 行）。以下把 questor 需要的**插件生命周期语义**扒成可移植模型。

### 1.1 Fiber = 每插件的生命周期状态机
- 显式 6 态：`PENDING / LOADING / ACTIVE / FAILED / DISPOSED / UNLOADING` —— [`fiber.ts:78-85`]。questor 的"策略/能力插件 init/load/unload/异常隔离"（C10）可**直接对齐成这张状态机**，而非散落的布尔开关。
- 状态跃迁只在 ACTIVE↔非 ACTIVE 跨越时通知依赖者：`_updateState` → `emit('internal/status')` + 对受影响服务 `reflect.notify([name])` —— [`fiber.ts:355-369`]。
- **依赖驱动的自动重载**（核心）：每个 fiber 的 `epoch` 是"它注入的每个依赖的 provider-fiber uid 拼出的串"（[`fiber.ts:385-397`]）。任一依赖被替换/失效 → epoch 变 → `_setEpoch` 触发 `_unload()` 再 `_reload()`（[`fiber.ts:399-415`]）。缺依赖则 epoch=`INACTIVE`、fiber 挂起不自启（[`fiber.ts:390-392`]）。**这就是"能力热插拔不动 loop"的机制内核**：换实现，靠依赖图让下游自动重挂载。

### 1.2 `effect` —— 作用域资源 + 反向 dispose
- `fiber.effect(execute, label)` 支持 返回 disposable / 同步迭代器 / 异步可迭代器；注册的清理**逆序执行**（[`fiber.ts:275-340`]，逆序在 [`fiber.ts:283`]）。
- **事件监听器注册本身包在 `effect` 里**：插件卸载即自动摘掉它的所有 handler（[`events.ts:134-141`]）。这是热重载不泄漏监听的根因，questor 插件宿主必须有等价保证。
- `Service.provide` / `accessor` / `mixin` 也一律包进 `fiber.effect`（[`reflect.ts:177-205`、`231-267`]）—— 服务暴露随插件生死。

### 1.3 Registry —— 按实现身份去重的插件表
- `Plugin` 三形态：函数 / 构造器 / `{apply}`，统一带 `Base{name, Config(schema), inject, provide}`（[`registry.ts:63-100`]）。
- `RegistryService.plugin()` 以 **callback 函数身份** 去重，一个 runtime 挂多个 fiber 实例（[`registry.ts:193-213`]）；`delete(plugin)` 会 dispose 该 runtime 的**全部 fiber**（[`registry.ts:162-171`]）。→ questor "策略/MCP 经注册表挂进 kernel"（§7-S3）可参考"按实现身份登记 + 一对多实例"。
- `@Inject('loader')` 装饰器声明类/方法依赖（[`registry.ts:17-40`]）；`class Hmr extends Service` + `@Inject('loader') @Inject('timer')`（[`hmr/index.ts:80-82`]）即"声明式依赖 + 提供能力"。

### 1.4 Context —— 作用域 / 隔离域 / 配置拦截
- 4 个内建服务 events/logger/reflect/registry；`ctx` 是 Proxy，属性访问经 `ReflectService.handler` 做**响应式依赖解析**（[`context.ts:36-49`]、[`reflect.ts:62-135`]，沿 fiber 父链在 `fiber.store` 找注入实现 [`reflect.ts:84-95`]）。
- `extend()` 派生子作用域（原型链）；`isolate(name,label)` 建隔离域；`intercept(name,cfg)` 让下游作用域覆盖某服务配置并按原型链 merge（[`context.ts:55-77`]、[`service.ts:51-67`]）。→ 对应 questor "多会话/多租户各一份 provider/工具实例但共享代码"的潜在需求（`isolate.ts:25-85` Realm 模型，realm 空了 GC [`isolate.ts:151-168`]）。

### 1.5 声明式条目清单 + commit-diff
- `EntryOptions{id, name, config, group, disabled, inject, isolate?, intercept?}`（[`entry.ts:8-15`]、扩展 [`isolate.ts:5-14`]）。
- `EntryTree.create/remove/update` 都产一条 `EntryChange`（create/update/remove/move 用 legacy/options 是否存在区分 [`tree.ts:16-22`、`94-129`]），落给 `commit()`。`Entry.update` 对 old/new 做 diff，无变化直接 return、disabled 就 dispose、变了才 `_patchContext→fiber.update`（[`entry.ts:100-134`]）。→ questor 插件/Skill/MCP 配置可采"**声明式条目 + diff 增量应用**"，别整表重建。

### 1.6 HMR —— 三段原子重载 + 回滚边界（最值得抄的安全模型）
- 文件变更分类：**externals（框架本体）→ 全进程重启** `loader.exit()`；**loadCache 内 → 部分重载**（[`hmr/index.ts:167-189`]，debounce 合并 [`hmr/index.ts:160`、`188`]）。
- `analyzeChanges`：把改动沿模块依赖图传播成 accepted/declined（[`hmr/index.ts:240-293`]）。
- `partialReload` **三段**：
  1. **Stage 1 先重导入并校验插件形状**（all-or-nothing），此时唯一被改的是模块缓存，**没碰任何实例**（[`hmr/index.ts:389-407`]）；
  2. Stage 2 卸载：`registry.delete(plugin)`（不阻塞），快照 fiber，**过滤掉"祖先已在本次批次内失效"的 fiber** 避免双重建（[`hmr/index.ts:409-443`]、祖先判定 [`hmr/index.ts:72-78`]）；
  3. Stage 3 重载：以同 config/同父 `registry.plugin(replacement, fiber.config)` 重建（[`hmr/index.ts:445-465`]）。
- **回滚**：ESM+CJS 模块缓存 backup/restore（[`hmr/index.ts:359-387`]）仅回滚 Stage 1；Stage 3 **无回滚**——"加载失败就留在失败态，和冷启动一样，下次改该文件再重试"（[`hmr/index.ts:459-464`]）。
- `include` 把配置当**文件即真源**：journal 记录未落盘 diff + 原子 rename，Windows 对被占文件的 `EACCES/EPERM/EBUSY` 做**有界重试**（[`include/index.ts:44-70`]）。
- **对 questor 的意义**：C10"插件 panic→捕获→回滚 Domain_State→发 error 事件、不带崩"可补一条硬语义——**能力交换走"先验证新实现可用，再卸旧挂新"**；Python 栈落地可用 `importlib.reload` 或**子进程重启该插件**替代 JS 的 module-cache 魔法（见 §6 差异）。

---

## 2. DeepCode —— Python↔Rust sidecar 进程边界与打包（最关键）

DeepCode = Tauri v2 Rust 壳 + React web + **Python App Server 作为 sidecar**（与 questor 同构）。Rust 侧实现在 [`desktop/src-tauri/src/sidecar.rs`]，Python 侧在 [`app_server/`]。

### 2.1 Rust 壳如何拉起并管理 sidecar（`sidecar.rs`）
- `RpcBridge{process, pending: Map<id→发送端>, next_id, generation, status}`（[`sidecar.rs:107-114`]）。`SidecarPhase{Starting,Ready,Stopping,Stopped,Crashed}` 状态机镜像给前端（[`sidecar.rs:74-82`]、`emit('deepcode://sidecar-state')` [`sidecar.rs:535-537`]）。**questor sidecar 生命周期应显式建模这套**，并进事件协议（02）。
- `start()`：`Command::new` 把 stdin/stdout/stderr **全 piped**（[`sidecar.rs:149-157`]）→ spawn → 取三个管道（缺任一即 kill+wait [`sidecar.rs:170-182`]）→ 起 stdout/stderr reader 线程（[`sidecar.rs:194-195`]）→ **发 `initialize` 握手（带 protocolVersion + clientInfo），STARTUP_TIMEOUT=45s**；成功→Ready+server_info，失败→Crashed+`force_kill`（[`sidecar.rs:197-224`]）。超时/请求常量集中 [`sidecar.rs:18-23`]。
- **传输 = newline-framed JSON-RPC 2.0 over stdio**：`request_with_timeout` 造 `{jsonrpc,id,method,params}` 写 stdin+`\n`+flush，在 `sync_channel` 上 `recv_timeout`（[`sidecar.rs:313-395`]）。Python 侧编解码同规格：newline-framed、`MAX_MESSAGE_BYTES=1MiB`、`ensure_ascii=False`+`allow_nan=False` 定序编码、严格校验 id/method/params（[`app_server/protocol/codec.py:1-56`]）。
- **stdout 分流 = Command 响应 vs Event 广播**：有 `id` → 是响应，路由回 pending（[`sidecar.rs:463-469`]）；只有 `method` → 是**服务端主动通知**，`emit('deepcode://rpc-notification')` 转给 webview（[`sidecar.rs:471-473`]）。stderr → `emit('deepcode://sidecar-log')`（[`sidecar.rs:432-450`]）。**印证 questor C5 Command/Event 二分**，并给"webview 不直连 Python、Rust 只做 broker"的活样板。
- **崩溃/断连**：generation 号防上一代 reader 污染新连接（[`sidecar.rs:416`、`557-559`]）；stdout 关闭 → `handle_stdout_closed` 把 pending 全部 fail（[`sidecar.rs:476-502`]），按 phase 决定记 Stopped 还是 Crashed。
- **优雅关闭两级**：`shutdown()` 先发 `shutdown` RPC（3s）→ 轮询 `child.try_wait()` 到 `SHUTDOWN_EXIT_GRACE=35s` → `force_kill` → fail_all → Stopped（[`sidecar.rs:241-285`]、`restart=shutdown+start` [`sidecar.rs:236-239`]）。
- **launch-spec 分层解析**（[`sidecar.rs:589-666`]）：`DEEPCODE_APP_SERVER_PATH`（诊断覆盖）→ debug 优先仓库 `.venv` 跑 `-m app_server`（免每次重打 PyInstaller [`sidecar.rs:650-666`]）→ **release 用打包资源 `resource_dir/app-server/deepcode-app-server[.exe]`**（[`sidecar.rs:618-626`]）→ debug 源构建产物；binary 名按平台（`.exe` [`sidecar.rs:605-609`]）。
- Tauri 装配：`RpcBridge` 作 managed state，`.setup()` 里 `spawn_blocking` 启动（[`desktop/src-tauri/src/lib.rs:82-91`]）；暴露给 webview 的 command：`rpc_request`（代理任意 RPC 方法）、`sidecar_status`、`sidecar_restart`、`export_diagnostics`、`open_path`（[`lib.rs:10-66`、`75-81`]）；`RunEvent::Exit → bridge.shutdown()`（[`lib.rs:95-101`]）。

### 2.2 Python 打包为 sidecar（`build-sidecar.py` + `app_server/__main__.py`）
- **PyInstaller `--onedir`，且刻意不用 onefile**：onefile 每次启动解到新临时目录，逼 macOS 重校验所有内嵌库；onedir 持久资源目录冷启动快、无需系统 Python（[`build-sidecar.py:1-7`]、命令 [`build-sidecar.py:154-171`]）。
- **隔离打包环境**：`setup:sidecar` 建 `build/sidecar/.venv`，装 `sidecar-requirements.lock` 锁定依赖 + PyInstaller，**不依赖仓库 venv**（[`../desktop/README.md`] 第 301-324 行）。builder python 解析 `env→sidecar venv→repo venv→sys.executable`，**每个都用探针导入 `REQUIRED_IMPORTS` 并强校验版本==3.12，fail-closed**（[`build-sidecar.py:85-147`]）。
- **精简与数据文件**：`EXCLUDED_MODULES`（PIL/numpy/pydantic.v1/setuptools，每个附"为何可排"[`build-sidecar.py:53-64`]）；非代码资源经 `--add-data` 显式打包（web_assets/goal_prompts/skills.builtin/mcp.presets.json [`build-sidecar.py:24-38`、`174-177`]）。`target_triple()` 从 `rustc -vV` 取，对齐 Rust target（[`build-sidecar.py:67-82`]）。
- **构建期自检 `_verify_bundle`**（这是 questor P7 最该抄的一条）：
  1. 跑冻结产物 `--verify-runtime`，断言打包的 Agent/provider/MCP/skills 懒导入全通过、资源齐全（[`build-sidecar.py:191-206`]、入口 `--verify-runtime` 分派 [`app_server/__main__.py:80-84`]）；
  2. **隔离的 `initialize → shutdown` RPC smoke**：临时 HOME/DB，喂两行 JSON-RPC，断言恰好两条响应且 `protocolVersion==1.0`（[`build-sidecar.py:208-268`]）；
  3. `finally` 无论成败都 `--service stop --cancel-running` 清理（[`build-sidecar.py:289-317`]）。
- **Python 入口的 stdio 卫生**：`isolate_protocol_streams()` **把原 stdout buffer 留给 RPC，所有 print/logging 改走 stderr**（[`app_server/__main__.py:114-120`]、logging→stderr [`app_server/__main__.py:85-89`]）——任何走 stdio 的 sidecar 必备纪律，否则一句 stray print 就撕裂 JSON-RPC 帧。

### 2.3 App Server 服务端协议与投影（`app_server/`）
- `__main__.py` 一入口多形态：`--service`（后台服务管理）/ `--serve`（loopback Web 服务）/ `--web` / `--managed-config`（监督器启动）/ `--database` / `--verify-runtime`（[`app_server/__main__.py:25-58`]）；默认 `serve_relay` 把 stdio 桥到共享后台服务（[`app_server/__main__.py:91-100`]）。
- `ServiceHost`：**拥有应用直到显式关闭（哪怕 0 客户端）**；transport 各管自己的 I/O 与鉴权；一个 peer 的 `shutdown` 只结束该 peer（[`app_server/host.py:17-22`]）。
- `ServiceHost.start()` 订阅内部子系统变更 → 投影成对外通知：`app.skills.subscribe_changes→SKILLS_CHANGED`、`app.plugins.subscribe_changes→PLUGINS_CHANGED`、`app.mcp.subscribe_changes→MCP_CHANGED`、`ConfigFileWatcher→SETTINGS_CHANGED`，每个 subscribe 都在 `ExitStack` 里配对 unsubscribe（[`app_server/host.py:50-85`]、fan-out `_publish` [`host.py:143-147`]、`notification_capacity=256` 背压 [`host.py:29`]）。→ questor 02"内外分层投影 + 只增不改"具体化：能力热更就发 `skills_changed/plugins_changed/mcp_changed`（对齐 03 §6 `tools_changed`）。
- **协议面即"方法名单一真源"**：`protocol/methods.py` 平铺全部 RPC（`initialize/shutdown`、`turn/start|steer|interrupt|retry`、`thread/context/compact`、`event/replay`、`provider/test|discover`、`skills/reload`、`plugins/set-enabled`、`mcp/probe|set-enabled` 等 [`app_server/protocol/methods.py:3-109`]）；`protocol/app-server.schema.json` 是 8312 行的规范 schema，前端类型由它生成、CI 校验（`generate:protocol`/`check:protocol` [`../desktop/README.md`] 第 313、331-335 行）。→ 印证 questor C6"外部契约带版本、只增不改、快照测试"的可行强度。

---

## 3. providers 端口抽象（DeepCode `core/providers/` + wuu `internal/providers/`）

两块互补：DeepCode 给**运行时基类 + 注册表**，wuu 给**最小口 + 可选能力接口 + 准入控制**。

### 3.1 DeepCode：抽象基类 + 冻结元数据注册表
- `LLMProvider` ABC 统一 `chat / chat_stream / chat_with_retry`，后端 `OpenAICompatProvider`/`AnthropicProvider`（[`core/providers/__init__.py:1-34`]）。`LLMResponse` 归一化（content/tool_calls/usage/**error_status_code/error_kind/error_type/error_code/error_should_retry** 稳定错误契约，reasoning/summary/provider_state 三者分离 [`core/providers/base.py:104-137`]）；`ToolCallRequest.to_openai_tool_call` 做 provider-neutral→wire 序列化（[`base.py:64-93`]）。
- **能力声明 = 三态旗标 + 前置校验**：`input_modalities / tool_calling / reasoning_supported`（None=未知、False=显式不支持 [`base.py:277-279`]）；`validate_request_capabilities()` 在发请求前拒掉"要工具/图像但声明不支持"（→`ProviderCapabilityError` [`base.py:281-296`]）。→ questor ProviderPort 该有同款"能力旗标 + 请求前置校验"。
- **元数据注册表（单一真源）**：`@dataclass(frozen=True) ProviderSpec{backend, endpoint_class, default_api_base, supports_prompt_caching, thinking_style, is_oauth, is_local…}`（[`core/providers/registry.py:101-135`]）；`PROVIDERS` 元组、**顺序即匹配优先级**（[`registry.py:185-353`]）；`find_by_name/find_by_model` 按前缀/关键字路由（[`registry.py:356-402`]）。
- **`endpoint_class` 信任分类**：`first_party/gateway/aggregator/local/unknown`，理由是"**api_base 就是信任边界**——终止 TLS 者可读所有 prompt/tool result、可改写 tool call"（[`registry.py:13-48`]）；`resolve_endpoint_class` 未分类/被改指向别处时 **fail-closed 到 unknown**（[`registry.py:140-182`]）。→ questor provider+egress/审计 应带这维（配 C9 权限、S1 providers README）。
- **重试/退避/错误分类/脱敏**：`(1,2,4)` 退避 + 持久上限 60s（[`base.py:155-157`]）；瞬时错误标记集 + 可重试状态码 `{408,409,429}`（[`base.py:159-178`]）；**429 再细分** `insufficient_quota…`（不可重试）vs `rate_limit_exceeded/overloaded`（可重试）（[`base.py:179-230`]）；`is_context_window_error` 靠消息标记触发（驱动压缩 [`base.py:19-50`]）；`redact_error` 把回显凭据从错误/可观测里抹掉（[`base.py:252-275`]）；`aclose()` 释放 transport（[`base.py:246-247`]）。

### 3.2 wuu：最小口 + 可选能力接口 + 跨 provider 准入控制
- **端口分层**：`Client{ Chat(ctx, req) }` 是最小口（[`internal/providers/types.go:510-513`]）；**能力靠独立小接口按类型断言获取**——`StreamClient{ StreamChat → chan StreamEvent }`（[`types.go:795-799`]）、`NativeCompactor`（原生压缩 [`types.go:814-817`]）、`SessionPrewarmer`（预热鉴权/传输 [`types.go:822-824`]）、`QuotaReader`（不推断读配额、失败也绝不造假 [`quota.go:17-21`]）、`MediaInputResolver`（媒体能力/预算 [`media_policy.go:25-29`]）、`InferenceJournal`（**事件溯源式** durable op/attempt/submission，禁含 prompt/凭据/body [`inference_journal.go:20-45`]）、`InferenceRequestPreparer`/`InferenceRecoveryApplier`（哈希前规范化 / 恢复动作 [`attempt_executor.go:9-16`、`110-116`]）。→ **questor contracts 建议采同款**：基础 `ProviderPort` + 可选能力子协议，Kernel 用能力探测而非"全家桶基类"。
- **`ProviderCoordinator` 跨 provider 准入控制**（questor 04 循环/可观测可借）：`ProviderScope = HMAC-SHA256(origin, credential, organization)`——稳定限流域但**不留存/不外泄凭据**（防离线猜 key [`provider_coordinator.go:17-34`、`59-62`]）；`ProviderPriority{BestEffort..Critical}` 由 workload profile 映射（[`provider_coordinator.go:72-94`]）；`MaxInFlight=6` + **ReservedInteractiveSlots（给交互留 1 槽不被子 agent 饿死）** + 熔断阈值/时长 + `MaxRateLimitCooldown` **给 Retry-After 封顶**（防代理回 86400 冻死全域 [`provider_coordinator.go:96-125`]）+ 老化（anti-starvation [`provider_coordinator.go:107`]）+ per-scope 在途/失败/cooldown/waiters 状态（[`provider_coordinator.go:161-179`]）。

---

## 4. wuu —— 进程隔离插件宿主 + 治理（对齐 questor C10 与 MCP/subagent）

### 4.1 每个能力=独立二进制 + JSON-lines 双工宿主代理
- 插件本体极薄：`cmd/wuu-goal-plugin/main.go` 只 `pluginapi.Serve(ctx, goal.Handler())`（[`cmd/wuu-goal-plugin/main.go:11-16`]）；同款还有 memory/dream/automation/subagent/todo/peers/ask-user 各一二进制 → **进程级故障隔离**（插件崩不带崩宿主，questor C10 的天花板解）。
- `pluginapi`（[`packages/plugin-go/runtime.go:1-6`]）：**multiplexed JSON-lines、host↔plugin 全双工单通道**、双向请求可同时在飞；`Serve→ServeIO(os.Stdin, os.Stdout)`（[`runtime.go:1070-1074`]）；帧 `{id, method, params}`（[`runtime.go:1043-1047`]）；**版本化**`CapabilityProtocolVersion=3 / RuntimeLifecycleVersion=1`（[`runtime.go:23-24`]）。
- **Harness 代理访问的活样板**（对应 questor"工具/存储访问须 Harness 代理"+ C4/C8）：插件调宿主服务经 `CallService`，且"**必须在 Definition.RequiredServices 声明、由 host 授权并路由**"（[`runtime.go:731-741`]）；`Caller` 携带 host 认证的插件身份（[`runtime.go:173-179`]）；host 暴露的服务面是受控的 storage/session/workspace/settings + `security.authorize`/`sandbox.process`/`host.artifact.import`（[`runtime.go:44-79`]），含 CAS `host.storage.compare_exchange`（[`runtime.go:67`]）。**插件拿不到裸句柄**。
- **跨进程的热插拔信号**：host→plugin `service.invoke` 投递调用、`service.changed` 通知"某服务解析结果变了"（[`runtime.go:30-35`]）；`execution.cancel` 走**带外通道**以抢占正在执行的调用、ack 丢弃（[`runtime.go:36-40`]）→ 对齐 questor C7（终止走命令、不硬杀）在跨进程下的等价物。

### 4.2 插件生命周期治理（两阶段提交 + 指纹 + 变更锁）
- 子命令 `inspect/install/update/list/approve/reject/enable/disable/remove/create/validate/build/test/pack/dev`（[`cmd/wuu/plugin.go:49-71`]）。
- **暂存 + 审批门**：install/update 若插件已存在则 `StagePackageUpdate`，"**已装代际保持 active 直到 approval**"（[`plugin.go:111-121`、`161-170`]）；`ApprovalRequired=true` 才激活（[`plugin.go:125-133`]）。→ questor 能力热更的**安全默认**：新实现先验证/暂存，旧的继续服务，批准后才换（与 cordis HMR "先验证后交换"同构）。
- **权限与指纹**：`Fingerprint / RequestedPermissions vs EffectivePermissions / UnsupportedFields / ActiveFingerprint / Pending`（[`plugin.go:23-47`、`116-120`]）。
- **变更锁**：`beginPluginCLIMutation/release`（defer `errors.Join`）串行化并发插件变更（[`plugin.go:106-110`、`156-160`]）；`Discover(root,home)` 跨项目+用户目录发现（[`plugin.go:193`]）。
- **dev 热重载**：fsnotify + 300ms 防抖 + 忽略 `dist/.git/node_modules`（防重建回环）+ attempted≠published 快照分离（失败等下次编辑、lease 忙则重试不要求重存）（[`cmd/wuu/plugin_dev_watch.go:15-60`]）。
- **子进程信号/退出码纪律**：`signal.NotifyContext(SIGINT/SIGTERM)` + 单独接 `SIGPIPE` 让写断开的 stdout 返 EPIPE、由 Run 收敛上报而非进程猝死（[`cmd/wuu/exec_lifecycle.go:13-25`]）；stdin 读取放 goroutine、`select` on `ctx.Done()` 以便取消（[`exec_lifecycle.go:37-49`]）；`ExitInterrupted/ExitTimeout` 退出码（[`exec_lifecycle.go:64-70`]）。

---

## 5. 对照 questor：可直接落 STRUCTURE / 00 的增量（逐条给改点）

### 5.1 providers 端口抽象 → 改 `00-layering.md §2 L5` + `03-tool-interface.md` + `STRUCTURE.md §7-S1`
- **A1**（改 00 §2 L5 行）：`ProviderPort` 从"→LiteLLM"升级为"**基础推理口(chat/stream) + 声明式 capability flags(streaming/tool_calling/input_modalities/reasoning) + 可选能力子协议(压缩/预热/配额/媒体)**"——形状取 wuu `Client`/`StreamClient`/`NativeCompactor`… + DeepCode 三态旗标（§3）。Python 侧用 Protocol/ABC + `validate_request_capabilities` 前置拒（[`base.py:281-296`]）。
- **A2**（改 00 §2 L5 / `contracts` 说明）：加 **StorePort/Clock/Id 同属"基础设施 Port"，实现不进 contracts**（已 S4，但补一句"能力靠子协议暴露、Kernel 用探测"）。
- **A3**（改 STRUCTURE §7-S1 providers README）：providers 目录除 LiteLLM 外，配一份 **ProviderSpec 冻结元数据（backend/endpoint_class/default_base/capability flags），单一真源、顺序即优先级、未分类 fail-closed**（[`registry.py:101-182`、`185-353`]）；显式记 **`api_base` 即信任边界**（§3.1）。
- **A4**（改 04/01 错误栈）：provider 侧采 **归一化错误契约（error_kind/code/retryable）+ 429 细分（quota 不可重试 vs rate 可重试）+ context-window 标记触发压缩**（[`base.py:19-50`、`155-230`]）+ **ProviderCoordinator 式熔断/优先级/保留交互槽/Retry-After 封顶**（[`provider_coordinator.go:72-125`]），scope 用 **HMAC 摘要不外泄凭据**（[`provider_coordinator.go:17-34`]）。

### 5.2 能力热插拔生命周期 → 改 `00-layering.md §3 表 + 横向` + `HARD-CONSTRAINTS C10` + `ROADMAP P9`
- **B1**（改 00 §3 表"能力热插拔(后期)"行 → 补具体机制）：questor 插件宿主 = **cordis Fiber 模型**——每插件一个状态机 `pending/loading/active/failed/unloading/disposed`（[`fiber.ts:78-85`]）+ **依赖声明式**（inject/provide）+ **依赖变更自动重挂载**（epoch/notify [`fiber.ts:385-415`、`reflect.ts:207-229`]）+ **effect 作用域、卸载即摘 handler/服务**（[`events.ts:134-141`]）。
- **B2**（给 C10 补硬语义）：把"故障隔离+回滚"细化成 **HMR 三段——① 先加载/验证新实现（不碰在跑的）② 卸旧 ③ 挂新；Stage1 失败可回滚、Stage3 失败留失败态下次重试**（[`hmr/index.ts:389-465`]）；再叠 wuu 的 **两阶段提交（暂存→旧代际继续服务→审批才换）**（[`plugin.go:111-121`]）。回滚边界仍守"只回 Domain_State、已发 Event 不撒回"（C10 原文）。
- **B3**（改 STRUCTURE §2 capabilities / §7-S2/S3）：插件/Skill/MCP 用 **声明式条目 `{id, enabled, config, inject/provides}` + commit-diff 增量应用**（[`entry.ts:8-15`、`100-134`]、[`tree.ts:94-129`]），不是整表重建；注册表**按实现身份去重、一对多实例**（[`registry.ts:193-213`]）。
- **B4**（ROADMAP P9 落地口径）：P9"cordis 式 DI/热插拔"注明**进程内(轻、零拷贝、同崩溃域) vs 子进程隔离(强隔离、需代理授权) 两档**；v1 内置工具走进程内，MCP/第三方插件走子进程 + **host 代理授权访问 store/session**（wuu RequiredServices [`runtime.go:731-741`]），呼应"能力热插拔不崩内核"。

### 5.3 Python↔Rust sidecar 进程边界与打包 → 改 `STRUCTURE.md §3 + §7-S5` + `02` + `ROADMAP P7`
- **C1**（STRUCTURE §3 desktop 补"打包与自检"清单）：① **PyInstaller onedir（非 onefile）**，附 macOS 冷启动理由（[`build-sidecar.py:1-7`]）；② **独立 build venv 从 lock 文件**，不依赖仓库 venv（README 301-324）；③ `--add-data` 显式带资源、`--exclude-module` 精简（每个记原因 [`build-sidecar.py:24-64`]）；④ **构建期 `_verify_bundle`：冻结产物 import 探针 + initialize/shutdown RPC smoke，fail 即阻断发布**（[`build-sidecar.py:191-317`]）。这条是 questor 目前**完全没有**的硬缺口。
- **C2**（STRUCTURE §3 补"sidecar 定位顺序"）：定 `env 覆盖 → 开发态源码(.venv) → 发布态资源目录 app-server/`，**发布态绝不回退系统 Python**（[`sidecar.rs:589-666`]）；binary 名按平台。
- **C3**（§7-S5 进程边界细化）：questor 已定 HTTP+SSE（ADR-0007）——补三点纪律：(a) **端口分配 + 就绪探测 + 会话 token**（本地 loopback 也要，DeepCode 用 `--port 0`/`runtime_probe`/`web_surface`/`service_state` 那套 [`build-sidecar.py:234`]）；(b) **sidecar 状态机（Starting/Ready/Stopping/Stopped/Crashed）进事件协议**（02）供 UI 呈现（[`sidecar.rs:74-82`、`535-537`]）；(c) 断连用 **generation 防陈旧连接 + 重连 `after_seq` 续传**（questor 已定 C6/C13，配 [`sidecar.rs:416`、`557-559`]）；崩溃则 pending 全 fail（[`sidecar.rs:476-502`]）。
- **C4**（§7-S5/03 加一句 stdio 备选与取舍）：明确 **"webview 永不直连 Python，Rust 只做 broker/代理"**（DeepCode `rpc_request` 代理 + notification 转发 [`lib.rs:10-26`]、[`sidecar.rs:471-473`]）；并记 **stdio newline-JSON-RPC 是更简单（无端口/无鉴权/天然单父）但单面、难中途重连** 的备选；**若选它，必须 `isolate_protocol_streams`：stdout 只留协议帧、print/log 全转 stderr**（[`app_server/__main__.py:114-120`]、[`codec.py:1-56`]）。
- **C5**（02 事件协议补"投影层"）：能力/配置热更走内部变更→**外部只增不改投影事件**（`skills_changed/plugins_changed/mcp_changed/settings_changed`），宿主用 ExitStack 对称订阅退订（[`host.py:50-85`]）；`Command→响应` 与 `Event→通知` 二分到两条通道（[`sidecar.rs:463-473`]），落实 C5。
- **C6**（03 §2 ctx 受控能力对齐 Harness 代理）：工具/插件的 `ctx` 只给"声明并被 grant 的 Port 视图"，**经 host 代理路由、带 caller 身份**（wuu CallService [`runtime.go:731-741`]），强化 C4/C8。

---

## 6. 冲突与需走 ADR 的分叉（别当免费）

- **F1 传输层：stdio-JSON-RPC vs 已定 HTTP+SSE**。三家两个用 stdio（DeepCode sidecar、wuu plugin-go），questor 选 HTTP+SSE（ADR-0007）。这是**已定决策**，本报告不改；但 sidecar **打包/定位/生命周期/崩溃重连**的纪律与传输无关，可直接采纳（C1/C2/C3）。仅当 questor 想给桌面首启加一条"无端口的 stdio 兜底"时才需新 ADR。
- **F2 Python 无 JS 式 module-cache 热替换**。cordis HMR 靠清 ESM/CJS 缓存重导入（[`hmr/index.ts:359-387`]）；Python `importlib.reload` 对已持有旧引用的对象无效、易脏。→ questor 的"能力热插拔"**对进程内插件只应做"依赖重挂载 + 幂等 setup/teardown"，真正换码优先走子进程重启该插件**（wuu 模型）。机制名（三段交换/回滚边界）可移植，实现别照搬。
- **F3 进程隔离插件宿主是 P9+ 重活**。跨进程引入 序列化/鉴权/新鲜度/部分失败/租约（00 天花板、C12/C13）。MCP（P5）已是"独立 server 进程 + 适配器映射同一 ToolSpec"（03 §6），可作进程隔离插件的**先导形态**；通用插件宿主别在 P1-P4 提前序列化一切（C12）。
- **F4 状态不可变叠加**。cordis/wuu 靠结构共享 + 逆序 dispose；questor C2 已定 COW + reduce 产新实例 + 不可变集合。插件"重挂载"产生的新视图实例须遵 C2，不得原地改共享子对象。

---

## 7. 未覆盖 / 存疑（诚实）

- DeepCode **后台 service 监督**（`launchd.py`/`systemd_user.py`/`windows_task.py`/`service_state.py`/`stdio_relay.py`/`websocket.py`）与 `app_server/dispatcher.py`(1761 行)未逐行读；若 questor 要"关窗仍在跑的常驻服务 + 多客户端连一个后端"（DeepCode 的共享服务模型），这是另一份扫描。
- DeepCode `providers/catalog*.py`（模型目录发现）、`profiles.py`/`credentials.py`/`egress.py`/`oauth.py` 只抽查接口，未全读；questor 若要"provider 能力发现 + 出站 allow/block + 凭据隔离"细节需补扫。
- wuu `inference_execution.go`(939)/`retry.go`(558)/`reliable_stream.go`(468)/各 `client.go` 具体实现未读全；`clients/native/` 是测试客户端非生产传输。
- cordis `include/patch.ts`/`journal.ts`、`loader/config/group.ts` 仅按需取；`reflect.ts` 的 Proxy/tracker 深水区只到"依赖解析+notify"粒度。
- 行号为扫描快照，后续以三家仓库 HEAD 为准；本报告不产码、未跑任何目标仓库构建/测试。

> **下一步（供决策）**：把 §5 的 A1–A4→00 §2/03/§7-S1；B1–B4→00 §3 表 + C10 + P9；C1–C6→STRUCTURE §3/§7-S5 + 02。F1/F3 若采纳需先记 ADR。
