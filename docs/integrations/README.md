# 集成

Questor 对外接入能力都走同一条原则：**外部能力以工具形式进入，受同一套权限裁决**。

| 集成 | 文档 | 说明 |
| --- | --- | --- |
| MCP 服务器 | [MCP](mcp.md) | stdio / HTTP / WebSocket 三种传输 |
| 渠道 | 见 [架构说明](../ARCHITECTURE.md) 的 Channels 一节 | 飞书与 QQ 为内置渠道 |
| OpenAI 兼容 API | 见 [架构说明](../ARCHITECTURE.md) 的客户端拓扑 | 外部客户端可接入本地宿主 |

插件与技能同样属于"扩展层"，但它们改变的是引擎内部行为，不是对外集成，规则见
[AGENTS.md](../../AGENTS.md) 的依赖铁律。
