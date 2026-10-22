# surfaces — Agent Contract

职责：传输层（当前只有 `channels/`：飞书 / QQ 的 bus 与 adapter）。
公开入口：`channels/__init__.py` 导出 BaseChannel / ChannelManager / MessageBus / InboundMessage / OutboundMessage。
拥有的数据：入站/出站消息、channel 生命周期、媒体根目录（由产品注入）。
允许依赖：目标只认 `contracts` + 注入的 facade；当前 `channels/adapter.py` 仍 import `engine.*`（Phase 2 修）。
不变式：不 import `capabilities` / `providers`；不持有业务状态。
禁止：不要把产品策略（群规则、通知）装进 surfaces；不要让 adapter 直接驱动引擎内部。
测试：`uv run pytest tests/unit/test_channels tests/integration/test_questor -q`
关键文件：`channels/__init__.py`、`channels/bus/queue.py`、`channels/impl/manager.py`
