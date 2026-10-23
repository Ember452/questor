# surfaces — Agent Contract

职责：传输/宿主层：`channels/`（飞书 / QQ）与 `ipc/`（终端 TUI、stdio backend、React 启动器）。
公开入口：`channels/__init__.py` 导出 BaseChannel / ChannelManager / MessageBus / InboundMessage / OutboundMessage；`ipc/__init__.py` 导出 run_repl / run_print_mode。
拥有的数据：入站/出站消息、channel 生命周期、IPC 会话与命令结果。
允许依赖：`contracts` + `config`；`ipc/` 额外允许 import `bootstrap.runtime`（组合根），这是唯一例外。
不变式：查询入口由外部注入（`ChannelBridge(query_runner=...)`）；`ipc` 不持有业务状态。
禁止：不要把产品策略（群规则、通知）装进 surfaces；不要让 channels 直接驱动引擎内部。
测试：`uv run pytest tests/unit/test_channels tests/unit/test_ui -q`
关键文件：`channels/__init__.py`、`ipc/__init__.py`、`ipc/backend_host.py`
