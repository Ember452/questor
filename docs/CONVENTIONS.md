# Repository Conventions — Questor Operating Rules

本文件是根 `AGENTS.md` §0–§6 的**完整原文**，2026-10-23 由计划 01（W7 文档三层）整段迁出。
迁移用脚本完成（`scratch/w7_apply.py`），源文本取自 `git show HEAD:AGENTS.md`，逐段 sha256 比对，
未改写任何一条规则；后续行为守则只在这里维护。根 `AGENTS.md` 保留文件头指针与路由。

<!-- sha256(rulebook region in HEAD/AGENTS.md) = f6bd42eaa46e92b9 -->

## 勘误（写在本节之外、正文之前，不改写守则原文）

下文 §0–§6 是逐字迁移，因此它引用的仍是 Phase 1 前的文档树。那些路径已不存在于活动文档区，
现行对应关系：

| 守则里写的 | 现状 |
|---|---|
| `docs/ROADMAP.md`、`docs/VISION.md`、`docs/design/`、`docs/pitfalls.md`、`docs/plan-archive/` | 旧版自 W10 起不在仓内：110 个文件搬到仓外 `../questor-archive/docs-pre-reset-v1/`（仓内 `docs-pre-reset-v1/README.md` 只是指针，如 `.../VISION.md`、`.../design/HARD-CONSTRAINTS.md`、`.../pitfalls.md`）；活动文档为 `docs/ARCHITECTURE.md`、`docs/adr/`、`docs/architecture/`、`docs/guides/`、`docs/operations/`、`docs/plan/` |
| `CONTRIBUTING.md` | 仍在仓库根，但本文里的写法是 `./CONTRIBUTING.md`（从仓库根算），搬进 `docs/` 后需要手工补一层 `../` |

所以读到 §5.5「Living Docs」时按上表把路径换成活路径；规则本身不变。守门用下面这行机器可读的
`known-stale-refs` 记录这些已知坏链：它只能**收缩**，某条链接被修好后若不再报错，守卫会要求把它
从清单里删掉。

<!-- known-stale-refs: docs/ROADMAP.md, docs/VISION.md, docs/design/, docs/pitfalls.md, docs/plan-archive/, CONTRIBUTING.md -->

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

## 4.5 Self-reliance — build on our own contracts
Questor is built from scratch on its own layered contracts. Implement a capability by designing it
against **our** `contracts/` Ports and layer boundaries (HARD-CONSTRAINTS C1/C14) — do not gate or
steer implementation on external/reference projects. If you consult an outside implementation for
inspiration, it stays inspiration: the merged code carries no external source/license/attribution
marker, and the plan records only *our* design decision and where it lives.

## 5. Quality Bar (Definition of Done) — never "looks done", only "verifiably works"
A change is done only when, as applicable: it **compiles + passes tests + lints clean + cold-imports
(`uv run python -c "import <mod>")` + violates no HARD-CONSTRAINT boundary**, and the relevant
**DoD in [ROADMAP](./docs/ROADMAP.md) or the active plan** is met (a manually reproducible behavior, not a vague claim).
- Follow the design contracts in `docs/design/`; any deviation → update the doc + (order/scope changes)
  file an ADR (ROADMAP §5). New fields/params: additive only (HARD-CONSTRAINTS C6/C11).
- Enforce the red lines with *mechanism*, not discipline: single-writer, read-only state view (COW),
  only `Command` mutates, events append-only & internal-not-stored-as-external, permission/sandbox
  live in the Harness (C1–C20).
- **A change is not done until its implied doc updates are made** (see §5.5).

## 5.5 Living Docs — maintain `docs/` as you code, don't defer
Docs are the source of truth the *next* session reads; stale docs cause wrong work. Update or add
**the moment reality changes**, not "later", and ship the doc edit in the same change:
- **Hard-to-reverse decision taken** → add/update an **ADR** (`docs/adr/`) with rationale + rejected options.
- **A contract changes** (layering / state / event / tool / loop) → update `docs/design/*` (keep the
  locked-vs-draft markers honest).
- **New engineering red-line discovered** → add a `C…` entry to `HARD-CONSTRAINTS.md`.
- **Architectural trap that will bite again** (cross-subsystem + high comprehension cost + recurring
  trigger) → add it to the right section of [`docs/pitfalls.md`](./docs/pitfalls.md): 现象 / 触发条件 /
  为什么容易复发 / 纪律 / 关联. **Ordinary bugs do NOT go here** — they go to a GitHub Issue labelled
  `bug`, fixed by a commit whose body says `Fixes #N` (auto-closed on merge to `main`). If a pitfall has
  a one-line enforceable rule, that rule belongs in `HARD-CONSTRAINTS.md` (a `C…` entry), not in pitfalls.
- **Reality diverges from plan** → follow the reality-wins principle and **write the deviation back**;
  update the active `docs/plan/NN-*.md` (archived phase plans in `docs/plan-archive/` are history — don't edit them back).
- **Structural/irreversible change** (contract, layering, phase order) → record an **ADR first**, then edit
  `ROADMAP.md` (ROADMAP §5); implementation-detail-only changes go to the active plan, not ROADMAP.
- `CLAUDE.md` stays a thin pointer — only touch it when the doc *map* changes.
> "Code merged, docs stale" = not done.

## 5.6 Code Comments — standardized, **in Chinese**
Identifiers, log messages and API names stay English, but **all code comments and docstrings are written in
Chinese**. Detailed conventions live in [`CONTRIBUTING.md`](./CONTRIBUTING.md)（注释规范）; minimum bar:
- **File/module header**: one-line responsibility + which layer (L0–L7) it belongs to + what it may import.
- **Docstring (Chinese) on every public class / Port / function**: what it does, how to use it, dependencies,
  invariants / pre-post conditions, and **failure semantics**.
- **Explain *why*, not *what*** at non-obvious decisions. Cite **our own** artifacts inline: `ADR-0005`,
  `HARD C2`, `docs/design/02-event-protocol.md §10`.
- **Mandatory comments** at: permission checks, fail-closed branches, cancel/rollback paths, event-persistence
  boundaries, and concurrency/gate/lease code.
- **No bare `TODO`**: every TODO/FIXME carries context + owning plan/ADR/Issue; `NotImplementedError` states what
  implements it (plan/ADR/issue).
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
