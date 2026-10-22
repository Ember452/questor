# Operations

Operational notes for installing, running, and validating Questor.

## Entrypoints

```text
questorharness  engine CLI
oh              engine CLI alias
openh           engine CLI alias
questor         product app CLI
```

## CI

See [CI](ci.md) for the GitHub Actions jobs and the local guard commands.

## Installation

Use the repository install scripts:

```bash
bash scripts/install.sh
```

```powershell
.\scripts\install.ps1
```

The `--with-channels` / `-WithChannels` flags are deprecated compatibility
flags. Feishu and QQ channel dependencies are installed by default.

## End-to-end validation

Set `QUESTOR_RUN_E2E=1` before running the e2e gate. These suites need provider
credentials, a built frontend, or Docker depending on the script:

```bash
QUESTOR_RUN_E2E=1 uv run pytest -m e2e -v
```

## Documentation

Current documentation is in `docs/`. The v1 archive in `docs-pre-reset-v1/` is
read-only and must not be edited during current work.
