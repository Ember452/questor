# capabilities/mcp — reserved stub (empty until P5)

MCP servers map to the same `ToolSpec` and pass through the same permission/
sandbox gate (design/03 §6; DeepCode-style "tool = separate server process").
Kept empty in P0/P1 (no process isolation yet). Naming convention for rules:
`mcp_<server>_<tool>`, matched by suffix.
