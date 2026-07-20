.PHONY: help sync format format-check lint test probe-console smoke-compose-api \
	smoke-local-llm run-api run-console validate-docs finalization-check \
	prepare-runtime-dirs docker-build docker-up docker-down \
	docker-shell docker-logs docker-clean ui-console ui-console-test check-usertest-env \
	install-hooks clean hook-commit hook-push test-unit test-integration

export PYTHONPATH := src
export HOST_UID ?= $(shell id -u)
export HOST_GID ?= $(shell id -g)

LOCAL_LLM_SMOKE_TARGET ?= tests/smoke/jung/test_local_llm.py
LOCAL_LLM_SMOKE_PYTEST_ARGS ?= -q
CONSOLE_E2E_TEST := tests/e2e/test_console_v1_workflow.py
PROBE_OUTPUT_DIR ?= logs/workflow-probes/console-v1
PROBE_ABS_OUTPUT_DIR := $(abspath $(PROBE_OUTPUT_DIR))

help:
	@echo "Native uv workflow (canonical):"
	@echo "  sync                 - uv sync --locked"
	@echo "  format / format-check / lint"
	@echo "  test                 - unit + integration (not real_llm)"
	@echo "  probe-console        - deterministic console E2E once"
	@echo "  validate-docs"
	@echo "  run-api / run-console"
	@echo "  finalization-check   - native release gate + runtime Compose smoke"
	@echo "  smoke-local-llm      - manual local-model smoke"
	@echo "  smoke-compose-api    - runtime-image Compose health smoke"
	@echo ""
	@echo "Docker packaging helpers:"
	@echo "  docker-build docker-up docker-down docker-shell docker-clean"

prepare-runtime-dirs:
	@mkdir -p data logs logs/workflow-probes
	@if [ "$${CI:-}" = "true" ]; then \
		chmod -R a+rwX data logs; \
	else \
		chmod -R u+rwX,g+rwX data logs; \
	fi

sync:
	uv sync --locked

format:
	uv run --locked ruff format .

format-check:
	uv run --locked ruff format --check .

lint:
	uv run --locked ruff check .

test:
	uv run --locked pytest -m "not real_llm" tests/unit tests/integration

probe-console: prepare-runtime-dirs
	@mkdir -p "$(PROBE_ABS_OUTPUT_DIR)"
	PROBE_OUTPUT_DIR="$(PROBE_ABS_OUTPUT_DIR)" \
		uv run --locked pytest $(CONSOLE_E2E_TEST) -v

validate-docs:
	uv run --locked python scripts/validate_docs_metadata.py

run-api:
	uv run --locked jung-api

run-console:
	uv run --locked jung-console --api-url http://127.0.0.1:8000

smoke-compose-api: prepare-runtime-dirs
	@set -eu; \
	smoke_data="$$(mktemp -d)"; \
	export JUNG_HOST_DATA_DIR="$$smoke_data"; \
	export ENV_FILE="$${ENV_FILE:-.env.example}"; \
	export COMPOSE_PROJECT_NAME=jung-compose-smoke; \
	cleanup() { \
		status=$$?; \
		trap - EXIT; \
		if [ "$$status" -ne 0 ]; then \
			docker compose -f docker-compose.yml logs --no-color api || true; \
		fi; \
		docker compose -f docker-compose.yml down --remove-orphans || true; \
		rm -rf "$$smoke_data"; \
		exit "$$status"; \
	}; \
	trap cleanup EXIT; \
	docker compose -f docker-compose.yml up \
		--build \
		--force-recreate \
		--remove-orphans \
		--wait \
		--wait-timeout 120 \
		api

smoke-local-llm:
	uv run --locked pytest $(LOCAL_LLM_SMOKE_TARGET) \
		-m real_llm --no-mocks \
		-o asyncio_mode=strict \
		$(LOCAL_LLM_SMOKE_PYTEST_ARGS)

# Final native-first gate. Compose smoke is the only Docker-required step.
finalization-check: prepare-runtime-dirs
	uv sync --locked
	uv run --locked ruff format --check .
	uv run --locked ruff check .
	$(MAKE) validate-docs
	$(MAKE) test
	$(MAKE) probe-console
	$(MAKE) smoke-compose-api

docker-build:
	docker compose build api

docker-up: prepare-runtime-dirs
	docker compose up --build --remove-orphans api

docker-down:
	docker compose down

docker-shell:
	docker compose exec api bash

docker-logs:
	docker compose logs -f $(SERVICE)

docker-clean:
	docker compose down --volumes --rmi local

test-unit:
	uv run --locked pytest tests/unit

test-integration:
	uv run --locked pytest tests/integration

ui-console: prepare-runtime-dirs
	docker compose up --build --wait -d api
	uv run --locked jung-console --api-url http://127.0.0.1:8000

# Same runtime image as api, parameterized for usertest data isolation.
ui-console-test: prepare-runtime-dirs check-usertest-env
	COMPOSE_PROJECT_NAME=jung-usertest \
	JUNG_HOST_DATA_DIR=./data \
	JUNG_DATA_DIR=/app/data/usertest \
	JUNG_API_HOST_PORT=8001 \
	ENV_FILE=.env.usertest \
		docker compose up --build --wait -d api
	uv run --locked jung-console --api-url http://127.0.0.1:8001

check-usertest-env:
	@if [ ! -f .env.usertest ]; then \
		echo ".env.usertest is missing."; \
		exit 1; \
	fi
	@set -a && . ./.env.usertest && set +a && \
	if [ -z "$${LLM_BASE_URL:-}" ] || [ "$${LLM_BASE_URL}" = "your_llm_base_url_here" ]; then \
		echo "LLM_BASE_URL is not configured in .env.usertest."; \
		exit 1; \
	fi && \
	if [ -z "$${MODEL_NAME:-}" ] || [ "$${MODEL_NAME}" = "your_model_name_here" ]; then \
		echo "MODEL_NAME is not configured in .env.usertest."; \
		exit 1; \
	fi

hook-commit: lint
hook-push: hook-commit

install-hooks:
	@./scripts/install-hooks.sh

clean:
	@rm -rf __pycache__ .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info 2>/dev/null || true
