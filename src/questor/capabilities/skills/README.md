# capabilities/skills — skill loading (P5, implemented)

Discovers `<dir>/SKILL.md` (YAML frontmatter via a strict, dependency-free parser —
no pyyaml dependency), validates `name`/dir-name, and **isolates per-file failures**
(bad `SKILL.md` → WARNING + skip, never aborts the batch; HARD C6). Progressive
disclosure METADATA→INSTRUCTIONS→RESOURCES keeps bodies out of context until needed.
Discovered skills render into the agent system prompt as a bounded catalog (wired in
`surfaces/cli.py` via `build_skill_catalog`). See `docs/plan/05-p5-skills-mcp.md`.
