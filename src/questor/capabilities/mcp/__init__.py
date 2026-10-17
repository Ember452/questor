"""L3 capabilities/mcp — MCP 客户端（P5，见 docs/plan/05）。

远程工具映射到同一 `ToolSpec`、走同一 permission/sandbox gate（`capabilities/mcp/README.md` 钉死）；
命名 `mcp_<server>_<tool>`、suffix 匹配。transport 采用官方 `mcp` SDK（ADR-0030），只在 `connection.py`
内 import；kernel 不持 SDK 句柄。本包不得 import providers/store/surfaces 实现（HARD C1/C14）。"""
