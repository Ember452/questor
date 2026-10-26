# serve/catalog — 只读内省目录

- 职责：把"面板要显示的列表"以**一个路由、按 kind 分发**的方式暴露出去
  （`GET /rt/r1/catalog/{kind}`）；每个 kind 一个纯函数，只读既有注册表。
- 不负责：不写任何状态、不做命令语义、不发 wire 帧（响应是普通 HTTP body，
  **绝不进 `ServerFrame` 联合**，否则会要求 `apps/web` 的 `cardSlots` 补槽位）、
  不新增存储、不做鉴权（鉴权在 serve 传输层）。
- 公开入口：`KINDS`、`PROVIDERS`、`CatalogContext`、`build()`。
- 拥有的数据：无。所有数据来自 `session_storage`、`AuthManager`、skills bundled 清单、
  `settings.mcp_servers`、`load_cron_jobs`、`get_task_manager()`、`git` 只读命令。
- 允许依赖：`platform`、`config`、`providers`、`capabilities`、`runtime`、标准库；
  不得依赖 `bootstrap/hosts/terminal`（终端是消费者，不是被依赖者）。
- 不变式：未知 kind 必须由 `build()` 返回 `None`，由路由翻成 404；
  **任何情况下不得用空表冒充"没有这个 kind"**；provider 内部读取失败返回空表并在
  终端显示空态（空与不可用是两件事，前者是数据、后者是故障）。
- 禁止：伪造连接状态/费用/额度；把 provider 写成有副作用的函数；绕过既有注册表自读文件。
- 测试：`tests/unit/bootstrap/hosts/serve/catalog/test_providers.py`（逐 kind + 404 + 空目录）；
  `tests/ci/test_catalog_coverage.py`（schema kind 枚举 == provider 注册表，含自证）。
- 关键文件：`providers.py`（唯一实现文件，新增 kind = 加一个函数 + 改 schema 枚举 + 加面板）。
