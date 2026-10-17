# capabilities/mcp — MCP client (P5, implemented)

MCP servers map to the same `ToolSpec` and pass through the same permission/sandbox
gate (design/03 §6). Remote tool naming: `mcp_<server>_<tool>`, matched by suffix for
permission rules. Transport uses the official `mcp` SDK (pinned v1) in `connection.py`
only (ADR-0030); the SDK owns the child process tree + env.

NOTE (C17): remote tools are `capability=NETWORK`, and `apply_capability_floor` denies a
NETWORK tool **fail-closed unless the run's sandbox reports `fences_network`**. So an MCP
server's tools are only *callable* under a network-fenced sandbox — `full_auto` cannot
widen this (proven by `tests/integration/test_mcp_loop_integration.py`). Config lives in
workspace `mcp.json` (`PROTECTED_IN_ROOTS`: the agent cannot rewrite its own MCP surface).
Per-run stderr + `run_id` association: `docs/plan/05-p5-skills-mcp.md` §16.4 / `providers/mcp_stderr.py`.
