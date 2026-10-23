# surfaces — Agent Contract

职责：只放面向 renderer 的传输适配器：`channels/`（飞书 / QQ）。
不负责：产品群策略在 `src/questor/gateway`，进程宿主在 `src/questorharness/bootstrap/hosts`。
公开入口：`channels/__init__.py` 导出 BaseChannel / ChannelManager / MessageBus / InboundMessage / OutboundMessage。
拥有的数据：入站/出站消息、channel 生命周期。
允许依赖：`contracts` + `config` + `platform`（叶子）；由 `surfaces-are-thin` 契约守住，禁止 import kernel / runtime / capabilities / providers / engine / commands / plugins / bootstrap。
不变式：查询入口由外部注入（`ChannelBridge(query_runner=...)`）；本层不持有业务状态、不装配运行时而只消费注入的端口。
禁止：不要把产品策略（群规则、通知）装进 surfaces；不要把进程宿主搬回这里——宿主属于 `bootstrap/hosts/`，因为它必须装配组合根。
测试：`uv run pytest tests/unit/test_channels -q`
关键文件：`channels/__init__.py`、`channels/impl/manager.py`、`channels/bus/queue.py`
