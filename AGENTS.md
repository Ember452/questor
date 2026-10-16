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

## 4.5 Reuse proven implementations — scan the sibling repos before you build
When writing or executing any phase plan (`docs/plan/NN-*.md`), **before implementing a capability, scan
the **actual set of sibling repos currently under `project-main/`** — this is the source of truth, new
additions auto-join, don't work off a hard-coded list. As of last refresh (2026-10-15) this covers 12
repos: hermes-agent, wuu, DeepCode, CowAgent, MetaGPT, cordis, EvoFlow, autogen, crewAI, OpenManus,
GenericAgent, Agent-S. **Re-list `project-main/` at plan time** (new repos appear over time):
- **Scan thoroughly — all relevant repos, not a cursory few** (§0 applies). A feature often already exists,
  battle-tested, in one of them.
- **If a peer has a proven / better implementation, adapt and reuse it** rather than writing fresh — lower
  bug risk. **Do not trim scope or cut corners to save code volume** (volume is explicitly not a concern).
- Guardrails: keep it behind the correct layer / port (HARD-CONSTRAINTS C1/C14); respect each project's
  **license + attribution** — when actually porting code, mark provenance in-file (never present others'
  code as our original); prefer adapting to our contracts over verbatim copy.
- Record it in the plan, per capability: which repos scanned, `file:line`, verdict (reuse / adapt / write-fresh + why).
- **Frontend especially:** for the desktop/web UI (React/Svelte + TS, Tauri), strongly prefer **adapting
  existing UI code from the reference repos** over writing fresh — chat/streaming render, SSE event-subscribe
  client, settings/permission panels, code highlight/diff, sidecar-lifecycle UI mostly already exist and are
  battle-tested. **Same-stack first choices: DeepCode (`desktop/web` React + `src-tauri` Rust Tauri v2) and
  EvoFlow (`evopanel` Tauri + pnpm)**; GenericAgent desktop (tauri); Cow/wuu/hermes Electron frontends adaptable
  to Tauri; hermes `web/`/`ui-tui/` and wuu `clients/` for reference. Re-check the repo list at plan time —
  new UI-bearing repos may appear. Still keep the iron rule:
  **UI is a thin client that only consumes the event protocol — never sink business/state/validation into the
  shell** (C14/ADR-0007); preserve license + attribution.

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
- **Peer-scan gate** (§4.5): before implementing any capability, the corresponding row in the phase's
  `docs/plan/NN-*.md` §0 table must be filled (repos scanned + `file:line` + verdict). Unfilled = not ready
to code. Template: `docs/plan/_TEMPLATE.md`.

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

## 5.6 Code Comments — standardized, **in Chinese**
Identifiers, log messages and API names stay English, but **all code comments and docstrings are written in
Chinese**. Detailed conventions live in [`CONTRIBUTING.md`](../CONTRIBUTING.md)（注释规范）; minimum bar:
- **File/module header**: one-line responsibility + which layer (L0–L7) it belongs to + what it may import.
- **Docstring (Chinese) on every public class / Port / function**: what it does, how to use it, dependencies,
  invariants / pre-post conditions, and **failure semantics**.
- **Explain *why*, not *what*** at non-obvious decisions. Cite references inline: `ADR-0005`, `HARD C2`,
  `参照 wuu internal/loopdriver/contract.go:14-76`.
- **Mandatory comments** at: permission checks, fail-closed branches, cancel/rollback paths, event-persistence
  boundaries, concurrency/gate code, and anywhere code was adapted from a reference repo (**must note source +
  license**, §4.5).
- **No bare `TODO`**: every TODO/FIXME carries context + owning Phase/ADR; `NotImplementedError` states which
  phase implements it.
- Don't comment self-evident lines (§2); **when behavior changes, update its comment** — a stale comment is a
  doc defect (§5.5).
Non-compliant comments = the change is **not done** (§5).

## 6. Git — English, and NEVER without permission
- **Commit / push messages in English**, Conventional Commits (`feat/fix/refactor/chore/docs/test/spike:`);
  describe the real engineering action; **do not fabricate timestamps or authorship**.
- **Never run `git commit` or `git push` without the user's explicit, in-turn permission.** Staging and
  preparing are fine; committing/pushing require an ask-and-yes every time (§3.2 of the repo rules).
- Never `--no-verify`; never force-push to a shared branch unless explicitly requested.
- **Branch policy** (ADR-0012, switched to plan **B** on 2026-10-16): everything goes through branch + PR — the
  maintainer no longer pushes `main` directly either. The gate is CI's independent blocking `boundaries` job
  (layering guards / cold import / protocol drift / guard self-tests), not human review. Until `boundaries` is
  marked *required* in GitHub settings and admin bypass is disallowed, "no direct pushes to main" is a
  convention rather than an enforced block — see the ADR's switch record.

---
**These rules are working when:** every diff traces to the request, few rewrites happen from
overcomplication or from under-building, clarifying questions come *before* implementation, nothing
is committed without a yes, and no bug ever traces back to a skimmed read or a skipped check.
