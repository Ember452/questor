# hosts/terminal — 终端瘦客户端的呈现层

- 职责：把 serve 的 wire 帧（13 kind）与 `/history` 快照渲染成终端界面；提供输入层
  （prompt_toolkit，可回退裸 input）、斜杠/文件补全、审批与提问卡片、alt-screen 覆盖层
  （transcript 浏览与搜索）。渲染原语与配色取自 `../serve/terminal_theme.py`。
- 不负责：不执行业务、不持有会话事实、不写会话存储、不解析命令语义（命令归
  `commands/registry.py`）、不实现第二套状态投影、不改 wire 契约（契约在
  `protocol/app-wire.schema.json`）。
- 公开入口：`__init__.py` 的 `__all__`（`UNSUPPORTED` / `badge_text` / `badge_reason`）；
  门面 `../terminal_client.py` 对产品暴露 `run_terminal_repl` 等符号，本包不自任入口。
- 拥有的数据：无持久化状态。唯一静态真源是 `unsupported.py`（未实现徽标登记，id 与
  `docs/plan/mapping/terminal-coding.md` 双向断言）。
- 允许依赖：`rich`、`prompt_toolkit`（仅本包与门面，见 `scripts/guards/check_layout.py`）、
  `questorharness.bootstrap.hosts.serve`、`questorharness.themes`、标准库。
- 不变式：帧只能经 `wire_view` 变成视图模型后再进卡片；除 `input_session` / `overlay`
  外不得直接写终端；未知 kind 与单卡渲染异常必须降级为可见行，不得中断事件消费。
- 禁止：在包内写形态判断（`if mode == ...`）或硬编码 `profile_id`；自造色值/图标；
  新增中文文案不进 `strings.py`；把 `TerminalRenderer` 的旧路径复制回来。
- 测试：`tests/unit/bootstrap/hosts/terminal/`（逐模块 + 快照，`Console` 参数钉死）；
  `tests/ci/test_unsupported_badges.py`（映射表双向）；`scripts/check.py` 全绿。
- 关键文件：`wire_view.py`（帧→VM）、`cards.py`（七种对话图元）、`app.py`（回合状态机 +
  单一写终端出口）、`overlay.py`（alt-screen 唯一 owner）、`unsupported.py`（徽标真源）。
