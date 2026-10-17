# CLAUDE.md — Index

This repo's operating rules and design live in dedicated files. **Start at `AGENTS.md`, then the docs
below.** This CLAUDE.md is only a pointer (kept for tools that read `CLAUDE.md` by default).

## Read first
1. **[AGENTS.md](./AGENTS.md)** — always-on behavioral + operating rules (completeness/no-shortcuts,
   think-before-coding, simplicity, surgical, goal-driven, quality bar, **git: English + never
   commit/push without explicit permission**).
2. **[docs/VISION.md](./docs/VISION.md)** — what we're building + north star.
3. **[docs/ROADMAP.md](./docs/ROADMAP.md)** — phases P0–P10, each with a verifiable DoD, v1 scope,
   release milestones, change rules.
4. **[docs/design/HARD-CONSTRAINTS.md](./docs/design/HARD-CONSTRAINTS.md)** — non-negotiable red lines C1–C20.
5. **[docs/STRUCTURE.md](./docs/STRUCTURE.md)** — reference repo layout (advisory, not binding; only the layering/dependency discipline is).

## Design contracts (`docs/design/`)
- `00-layering.md` — 8-layer architecture + dependency inversion.
- `01-state-model.md` — L1 core state (working draft).
- `02-event-protocol.md` — Command/Event, envelope, internal↔external projection, versioning.
- `03-tool-interface.md` — ToolSpec, two-layer validation, sandbox, permission.
- `04-turn-loop.md` — phase pipeline + `LoopState`（只读视图/verdict）+ guards.
- `05-policy.md` — L4 策略契约（PolicyPort/注册/热替换/AB；04 的纵深、非第六接缝）.
- `06-memory.md` — 三层记忆 + 混合检索 + 蒸馏 + 压缩↔记忆桥（P4 地基）.
- per-phase detailed plans: `docs/plan/NN-*.md` (written just before that phase), always start from
  [`docs/plan/_TEMPLATE.md`](./docs/plan/_TEMPLATE.md) whose **§0 peer-repo scan table must be filled before coding** (AGENTS §4.5).

## Decision history
- `docs/adr/` — ADR-0001…0028 (why each hard-to-reverse choice was made; **0027** is the logging
  foundation). Index: [`docs/adr/README.md`](./docs/adr/README.md).

## Recurring architectural traps
- **[docs/pitfalls.md](./docs/pitfalls.md)** — only cross-subsystem, high-comprehension-cost, likely-to-resurface
  traps (现象 / 触发条件 / 为什么容易复发 / 纪律 / 关联), grouped by area. **Ordinary bugs are not here**: they are
  GitHub Issues labelled `bug`, closed by a commit body `Fixes #N` on merge to `main`. Check it before touching
  a subsystem you don't fully own (store/persistence, event protocol, process boundaries).

## Precedence
User instruction > `AGENTS.md §0` + `HARD-CONSTRAINTS` > `VISION`/`ROADMAP`/`design`/`adr` > this file.
Docs are the source of truth and change faster than this pointer — **read them live, don't work from
memory or from a summary.**
