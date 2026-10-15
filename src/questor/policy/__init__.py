"""L4 Policy — pluggable Agent strategies implementing ``PolicyPort``.

Read-only view → single-step intent. Owns prompts/algorithms, NOT model routing,
approval, sandbox, or persistence (design/05). Injected into the kernel."""
