# AGENTS.md — Questor Operating Rules

Behavioral and operating rules for anyone (human or AI) working in this repo. These bias toward
**caution over speed** — for trivial tasks, use judgment.

Authoritative project content lives in `docs/` — this file is the always-on rulebook, not a copy of
the design. **Read the linked docs for the current truth; never work from memory or from this file
alone** (they evolve). Priority: user instruction → §0 + [HARD-CONSTRAINTS](./design/HARD-CONSTRAINTS.md)
→ [VISION](./VISION.md)/[ROADMAP](./ROADMAP.md)/design/adr → elsewhere.

---

## 0. Completeness — no shortcuts when reading or writing

> The most expensive failures here come from *doing less than the task requires to look like progress*.

- **Read fully, don't skim.** When analyzing any project/file/spec, cover the **complete relevant
  scope** — never just "part of the core" and assume the rest. Partial reads hide the coupling,
  edge cases, and call sites that cause subtle bugs. If something is out of scope, say so explicitly;
  don't silently sample.
- **Write fully, don't under-build to save effort.** Do not omit required logic, edge cases,
  error handling, validation, or tests just to write fewer lines. "Concise" means *no throwaway
  complexity* (§2), **not** missing necessary work.
- **Verify, don't assume.** Ground claims in evidence (`file:line`, a run, a test). If you'd have to
  guess, go read/run it instead.
- **§0 vs §2:** §2 = don't add speculative extras; §0 = don't skip what's needed. Both hold —
  the line is *necessary vs gratuitous*, not *more vs less*.

## 1. Think Before Coding
- State assumptions explicitly; if uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name it. Ask.

## 2. Simplicity First — minimum code that solves the problem
- No features beyond what was asked; no abstractions for single-use code.
- No unrequested "flexibility/configurability"; no error handling for impossible scenarios.
- 200 lines that could be 50 → rewrite. Ask: would a senior engineer call this overcomplicated?

## 3. Surgical Changes — touch only what you must
- Don't "improve" adjacent code/comments/formatting; don't refactor what isn't broken; match existing style.
- Unrelated dead code → mention, don't delete. Remove only orphans *your* change created.
- Every changed line traces to the request.

## 4. Goal-Driven Execution — loop until verified
- "Add validation" → tests for invalid inputs, then pass. "Fix bug" → a failing repro, then pass.
  "Refactor X" → tests pass before and after.
- Multi-step: state `step → verify: check`. Strong DoDs let you loop independently.

## 5. Quality Bar (Definition of Done) — never "looks done", only "verifiably works"
A change is done only when, as applicable: it **compiles + passes tests + lints clean + cold-imports
(`uv run python -c "import <mod>")` + violates no HARD-CONSTRAINT boundary**, and the relevant
**Phase DoD in [ROADMAP](./ROADMAP.md)** is met (a manually reproducible behavior, not a vague claim).
- Respect the phase's **prototype scope** (ROADMAP §2.5): e.g. P1 is serial, no parallel/MCP/subagent.
- Follow the design contracts in `docs/design/`; any deviation → update the doc + (order/scope changes)
  file an ADR (ROADMAP §5). New fields/params: additive only (HARD-CONSTRAINTS C6/C11).
- Enforce the red lines with *mechanism*, not discipline: single-writer, read-only state view (COW),
  only `Command` mutates, events append-only & internal-not-stored-as-external, permission/sandbox
  live in the Harness (C1–C13).
- **A change is not done until its implied doc updates are made** (see §5.5).

## 5.5 Living Docs — maintain `docs/` as you code, don't defer
Docs are the source of truth the *next* session reads; stale docs cause wrong work. Update or add
**the moment reality changes**, not "later", and ship the doc edit in the same change:
- **Hard-to-reverse decision taken** → add/update an **ADR** (`docs/adr/`) with rationale + rejected options.
- **A contract changes** (layering / state / event / tool / loop) → update `docs/design/*` (keep the
  locked-vs-draft markers honest).
- **New engineering red-line discovered** → add a `C…` entry to `HARD-CONSTRAINTS.md`.
- **Reality diverges from plan** → follow VISION §0.4 (reality wins) and **write the deviation back**;
  update the active `docs/plan/NN-*.md`.
- **Phase order/scope added/removed/moved or cross-phase shift** → record an **ADR first**, then edit
  `ROADMAP.md` (ROADMAP §5); implementation-detail-only changes go to the phase's `plan/*`, not ROADMAP.
- `CLAUDE.md` stays a thin pointer — only touch it when the doc *map* changes.
> "Code merged, docs stale" = not done.

## 6. Git — English, and NEVER without permission
- **Commit / push messages in English**, Conventional Commits (`feat/fix/refactor/chore/docs/test/spike:`);
  describe the real engineering action; **do not fabricate timestamps or authorship**.
- **Never run `git commit` or `git push` without the user's explicit, in-turn permission.** Staging and
  preparing are fine; committing/pushing require an ask-and-yes every time (§3.2 of the repo rules).
- Never `--no-verify`; never force-push to a shared branch unless explicitly requested.

---
**These rules are working when:** every diff traces to the request, few rewrites happen from
overcomplication or from under-building, clarifying questions come *before* implementation, nothing
is committed without a yes, and no bug ever traces back to a skimmed read or a skipped check.
