# providers — L5 adapters: every Port implementation, not just model vendors

The name is kept deliberately and is easy to misread (STRUCTURE **S1**): here "providers"
means **the implementations behind the L5 ports**, i.e.

- LLM — `litellm_adapter.py`, `fake.py`
- Store — `store_sqlite.py` (event sourcing + checkpoint), `artifact_store.py` (ADR-0019)
- Process execution — `process_runner.py` (ADR-0018), `_win_job.py`
- Sandbox / environment — `sandbox.py`, `env_safety.py`

It is **not** a registry of model vendors.

This is the only package allowed to import third-party infrastructure SDKs — ruff
`banned-api` grants it an exemption; everywhere else must reach infrastructure through a Port
declared in `contracts/`.

Upper layers get these by **injection**: `kernel` never imports a concrete adapter
(HARD C1/C14, enforced by `.importlinter` + `scripts/check_layering_ast.py`, cold import via
`scripts/verify_p0.py`).

A future split into `{llm, store, exec, sandbox}` subpackages is worth considering — but only
once each cluster can carry its own enforceable import-linter contract; a subpackage that adds
no boundary is just extra depth.
