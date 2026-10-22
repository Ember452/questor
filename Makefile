.PHONY: sync unit integration test e2e guards lint precommit ci

sync:
	uv sync --extra dev

unit:
	uv run pytest -m unit

integration:
	uv run pytest -m integration

test:
	uv run pytest -m "unit or integration"

e2e:
	QUESTOR_RUN_E2E=1 uv run pytest -m e2e -v

guards:
	uv run python scripts/guards/_guard_kit.py --self-test
	uv run python scripts/guards/check_thread_leak.py --self-test
	uv run python scripts/guards/check_secret_projection.py --self-test
	uv run python scripts/guards/check_doc_cross_refs.py --self-test
	uv run python scripts/guards/check_thread_leak.py --fail-on-empty
	uv run python scripts/guards/check_secret_projection.py --fail-on-empty
	uv run python scripts/guards/check_doc_cross_refs.py --fail-on-empty
	uv run lint-imports

lint:
	uv run pre-commit run --all-files

precommit:
	uv run pre-commit run --all-files

ci: guards lint test
