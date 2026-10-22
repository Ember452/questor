# ADR-0046: 能力热插拔宿主（薄生命周期 + 熔断隔离，非 cordis 容器）

- 状态：✅（2026-10-18，P9 已实现并验证；实现见 [`../plan-archive/09-p9-openai-plugin-host.md`](../plan-archive/09-p9-openai-plugin-host.md) T1/T5/T9）
- 背景：ROADMAP §1 P9 目标含"cordis 式 DI/热插拔"；[`00-layering`](../design/00-layering.md) 把"横向 DI/插件宿主(cordis 式 Fiber 生命周期)"列为横切设施、"能力热插拔=不动 loop"；[`HARD-CONSTRAINTS`](../design/HARD-CONSTRAINTS.md) **C10** 定"策略/能力插件有 init/load/unload/异常隔离；插件 panic→Harness 捕获、回滚 Domain_State、发 error 事件、绝不带崩进程"。peer-scan（§0）：cordis `registry.ts:125-214`（按 callback 键的 `RegistryService` + 可 dispose 的 `Fiber`）是 **TypeScript**（cosmokit/装饰器/proxy），字面移植违 AGENTS §2；DeepCode `core/plugins/host.py:44-49`（inert discovery："发现≠执行"、snapshot+listener+monitor）+ `registry.py`（原子注册、错误三分）是 MIT 可借形状。**关键现状**：本仓已有可热插的注册点——`capabilities/tools/registry.py`（`register/unregister` 只影响**下一次 `freeze_for_run`**、活 run 面不变、first-writer-wins 冲突守卫）、`capabilities/skills/catalog.py`、`capabilities/mcp/manager.py`；`kernel/loop.py:389-395` 已隔离 policy 抛错。**矛盾**：P9 要真做通用 DI 容器，还是薄宿主？"能力可热插拔不崩内核"的可证伪判据是什么？
- 决策：
  1. **不移植 cordis 容器**（不做通用 Fiber/Reflect/`@Inject` DI 框架）：questor 现有**手动构造注入 + 组合根**（`__main__.py`）已够用；引通用容器 = 单用途抽象 + 投机基建（AGENTS §2/C12）。cordis/DeepCode 只取**形状**（按 id 注册、可 dispose 生命周期、inert discovery、错误二分）。
  2. **薄 `PluginLifecycle` 协议 + `PluginHost` 编排器**：定义统一生命周期（`id`/`init()`/`teardown()`），`PluginHost` 把**已存的** tools/skills/mcp 注册点纳入统一 register/deregister 面；宿主落 `capabilities/_host.py`（L3）或新 `plugin_host/`（横向）——`check_layering_ast` 钉：**✗ surfaces/providers 具体实现**，只 import `contracts` + 各能力注册表。
  3. **每插件调用一律包熔断护栏（C10）**：`init`/`teardown`/（策略）`propose_action`/（工具）execute 入口包 try/except → **捕获异常、回滚 Domain_State 到最近 checkpoint、发 error/warning 事件、内核继续**；**绝不吞 `CancelledError`/`KeyboardInterrupt`/`SystemExit`**（承 `loop.py:389-395` + ADR-0028 BaseException 纪律）。
  4. **热插只影响下一次 `freeze_for_run`、活 run 面不变**：直接复用 `tools/registry.py:97-104` 现成 freeze 语义（模型不会看到中途变化的工具面）；skills/MCP 同构接入 host 的 generation 计数。
  5. **`tools_changed` = live-only 告警事件（钉死发射语义，plan §4.3 M1）**：新增 `EventType.TOOLS_CHANGED`（additive、**不 bump `v`**），`data.domain ∈ {tools,skills,mcp,plugins,settings}`；**入 `LIVE_ONLY` 集、不占 durable seq、不入库**（承 C13/design-02 X2）。因能力增删发生在 loop 之外、且活 run 面已冻结，若当 durable 会陷入"host 直 `bus.emit` 违 reduce-purity / 或无 run 可挂"——故定为 **live-only 告警，由 loop 自身**在检测到能力名册 `generation` bump 后的安全点发一条（通知外部观察者"名册已变、下次 freeze 生效"），**活 run 面不变**；host **只 bump `generation`、不碰 bus**（避免第二发射者，承 C2/C13/C16）。
  6. **发现边界**：进程内 register/deregister（含 ADR-0045 的组合根固定名册）；**无磁盘扫描/HMR 运行时加载**（同 ADR-0045 决策 5，防投机基建）。inert-discovery 纪律借 DeepCode `host.py:44-49`：发现/注册**不执行**插件代码副作用。
- 后果：
  - 正面：DoD"能力可热插拔不崩内核"有**可证伪判据**（① 拔插工具/技能/MCP 前后 turn 循环稳定、活 run 面不变、发 live-only `tools_changed`；② 插件 `init`/`propose_action` panic 被熔断、内核继续、发 error 事件）；协议只增（`tools_changed` additive、`v` 不 bump）；不养通用 DI 容器、不为远程序列化（C12）。
  - 代价 / 需持续守：`tools_changed` 不进 `projection._DATA_KEYS`（C20）；`loop` 需一个注入的 generation 读数（经 Port/回调，不破 C1）来判是否发 live-only 事件；host 不得演化成第二事件真相载体。
- 备选(被否)：
  1. 移植 cordis TS Fiber/Reflect DI → 否（跨语言字面搬、单用途抽象、违 §2/C12）。
  2. 现在就做磁盘发现/HMR 热重载用户插件 → 否（投机基建 + IO/信任/崩溃面；DoD 不需）。
  3. `tools_changed` 当 durable 事件、host 直发 bus → 否（违 reduce-purity + 无 loop 外写者、破 C2/C13/C16）。
  4. 让热插改活 run 已冻结的工具面 → 否（模型看到中途变化的面，违 `tools/registry.py` freeze 不变式）。
  5. 熔断护栏里 `except Exception` 连 `CancelledError` 一起吃 → 否（重演 ADR-0028 取消被吞的坑）。
- 关联：HARD-CONSTRAINTS C1/C10/C12/C13/C14/C15/C20；design/00 横向 DI；design/02 §7（`tools_changed`/MCP 热增生长场景）/§10（domain 字段）；`ADR-0045`（策略 registry，registry 与本宿主正交）；`ADR-0028`/`loop.py:389-395`（BaseException 纪律）；`tools/registry.py:60-104`（freeze + first-writer-wins 现成）；peer：cordis `registry.ts`/`fiber.ts`（MIT，取形状）、DeepCode `plugins/host.py`（MIT，inert-discovery）。
