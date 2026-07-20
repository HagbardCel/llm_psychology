.PHONY: help install dev-install install-uv format lint test test-unit test-integration test-devcontainer test-dev test-validate install-hooks clean run-server
.PHONY: docker-up docker-down docker-test docker-test-isolated docker-test-one docker-shell docker-logs docker-logs-api docker-db-view docker-test-reset docker-clean
.PHONY: ui-console ui-console-test
.PHONY: probe probe-console-deterministic probe-console-v1-deterministic probe-console-intake-notes probe-logs probe-db check-usertest-env
.PHONY: devcontainer-rebuild devcontainer-test devcontainer-open
.PHONY: validate-docs finalization-check
.PHONY: prepare-runtime-dirs test-refactor-fast validate-refactor-phase-1 phase-2-test validate-refactor-phase-2 phase-3-test validate-refactor-phase-3 smoke-refactor-phase-3-local-llm smoke-target-local-llm phase-5-test validate-refactor-phase-5 validate-refactor-phase-6 test-target _phase-5-console-v1 hook-commit hook-push
.PHONY: resolve-compose-config smoke-compose-api _validate-phase-6-cutover-contract _validate-phase-5-external-contract

export PYTHONPATH := src
export HOST_UID ?= $(shell id -u)
export HOST_GID ?= $(shell id -g)
PHASE3_SMOKE_TARGET ?= tests/smoke/jung/test_phase3_local_llm.py
PHASE3_SMOKE_PYTEST_ARGS ?= -q

# Default target
help:
	@echo "Available targets:"
	@echo ""
	@echo "Default (Docker) Development:"
	@echo "  install-uv        - No-op; install uv externally for native workflows"
	@echo "  install           - Build API container (installs backend deps inside Docker)"
	@echo "  dev-install       - Build API container"
	@echo "  format            - Format code with black (Docker)"
	@echo "  lint              - Lint code with ruff (Docker)"
	@echo "  test              - Run the target-runtime test suite (Docker)"
	@echo "  test-dev          - Run the target-runtime test suite (Docker)"
	@echo "  test-validate     - Run the target-runtime test suite (Docker)"
	@echo "  test-unit         - Run target-runtime unit tests"
	@echo "  test-integration  - Run target-runtime integration tests"
	@echo "  test-devcontainer - Run devcontainer setup tests (Docker)"
	@echo "  install-hooks     - Install git pre-commit and pre-push hooks for automated validation"
	@echo "  clean             - Clean up generated files and caches"
	@echo "  requirements      - Generate locked requirements from .in files"
	@echo "  sync              - Rebuild containers from locked requirements"
	@echo "  run-server        - Run HTTP/WebSocket server via Docker"
	@echo "  validate-docs     - Validate docs metadata + canonical active-doc index (Docker)"
	@echo "  finalization-check - Target-runtime release gate (Phase 6)"
	@echo "  test-target         - Complete deterministic Jung test suite once (Phase 6)"
	@echo "  validate-refactor-phase-6 - Validate Phase 6 cutover invariants (Docker)"
	@echo "  smoke-target-local-llm - Manual local-model smoke alias (Phase 6 closure)"
	@echo "  validate-refactor-phase-2 - Validate Phase 2 jung domain/persistence (Docker)"
	@echo "  phase-3-test            - Run Phase 3 LLM and processor tests (Docker)"
	@echo "  validate-refactor-phase-3 - Validate Phase 3 jung llm/phases (Docker)"
	@echo "  smoke-refactor-phase-3-local-llm - Manual local-model smoke for Phase 3 schemas"
	@echo ""
	@echo "jung-console:"
	@echo "  ui-console        - Run jung-console against Compose api"
	@echo "  ui-console-test   - Run jung-console against usertest Compose api"
	@echo "  probe-console-v1-deterministic - Run Phase 5 Jung console deterministic probes"
	@echo "  probe-logs        - Print latest workflow probe summary"
	@echo "  probe-db          - Print rows created by latest workflow probe"
	@echo ""
	@echo "Docker Development:"
	@echo "  docker-up         - Start backend API service"
	@echo "  docker-down       - Stop all Docker containers"
	@echo "  docker-shell      - Shell into API container"
	@echo "  docker-logs       - View logs (usage: make docker-logs SERVICE=api)"
	@echo "  docker-logs-api   - View API logs only"
	@echo "  docker-test       - Run tests in Docker (usually not needed, use 'make test')"
	@echo "  docker-test-one   - Run specific test (usage: make docker-test-one TEST=tests/unit/test_foo.py)"
	@echo "  docker-db-view    - View database at http://localhost:8080 (DB=local|usertest, default: local)"
	@echo "  docker-test-reset - Reset test database"
	@echo "  docker-clean      - Clean up all Docker resources"
	@echo ""
	@echo "DevContainer:"
	@echo "  devcontainer-rebuild - Rebuild devcontainer without cache"
	@echo "  devcontainer-test    - Test devcontainer configuration"
	@echo "  devcontainer-open    - Open project in VSCode devcontainer"

# Prepare run-time dirs
prepare-runtime-dirs:
	@mkdir -p data logs logs/workflow-probes
	@if [ "$${CI:-}" = "true" ]; then \
		chmod -R a+rwX data logs; \
	else \
		chmod -R u+rwX,g+rwX data logs; \
	fi

# Install UV package manager
install-uv:
	@echo "install-uv is a no-op; install uv externally for native workflows."
	@echo "Use 'make requirements' to compile lockfiles in Docker."

# Install runtime dependencies inside Docker
install:
	docker compose build api

# Build dev containers (installs Python deps inside Docker images)
dev-install:
	docker compose build api

# Format code with black (Docker)
format: prepare-runtime-dirs
	docker compose run --rm api black .

# Lint code with ruff (Docker)
lint: prepare-runtime-dirs
	docker compose run --rm api ruff check .

# Run all tests (Docker)
test: test-target

# Run unit tests only (Docker)
test-unit: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		test pytest $(PHASE_6_PYTEST_OPTIONS) \
		tests/unit/jung/ $(TARGET_SUPPORT_TESTS)

# Run integration tests only (Docker)
test-integration: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		test pytest $(PHASE_6_PYTEST_OPTIONS) \
		tests/integration/jung/

TARGET_SUPPORT_TESTS := \
	tests/unit/test_validate_refactor_phase_5.py \
	tests/unit/test_validate_refactor_phase_6.py \
	tests/unit/test_validate_docs_metadata.py \
	tests/unit/test_recording_fake_llm.py \
	tests/unit/test_measure_codebase.py

PHASE_6_PYTEST_OPTIONS := \
	-o trio_mode=false \
	-o asyncio_mode=auto

test-target: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		$(PHASE_6_PYTEST_OPTIONS) \
		-m "not real_llm" \
		tests/unit/jung/ \
		tests/integration/jung/ \
		$(TARGET_SUPPORT_TESTS)

smoke-target-local-llm: smoke-refactor-phase-3-local-llm

resolve-compose-config: prepare-runtime-dirs
	@set -eu; \
	tmp="logs/compose-config.resolved.json.tmp"; \
	trap 'rm -f "$$tmp"' EXIT; \
	rm -f "$$tmp"; \
	ENV_FILE="$${ENV_FILE:-.env.example}" \
		docker compose \
			-f docker-compose.yml \
			--profile '*' \
			config \
			--format json \
			--no-env-resolution > "$$tmp"; \
	mv "$$tmp" logs/compose-config.resolved.json

_validate-phase-6-cutover-contract: resolve-compose-config
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		--entrypoint /usr/local/bin/python \
		--volume "$(CURDIR):/workspace:ro" \
		--workdir /workspace \
		--env PYTHONPATH=/workspace/src \
		test scripts/validate_refactor_phase_6.py --stage cutover \
		--compose-config /workspace/logs/compose-config.resolved.json

_validate-phase-5-external-contract: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		--entrypoint /usr/local/bin/python \
		--volume "$(CURDIR):/workspace:ro" \
		--workdir /workspace \
		--env PYTHONPATH=/workspace/src \
		test scripts/validate_refactor_phase_5.py

validate-refactor-phase-6: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		scripts/validate_refactor_phase_6.py \
		tests/unit/test_validate_refactor_phase_6.py
	$(MAKE) _validate-phase-6-cutover-contract
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		$(PHASE_6_PYTEST_OPTIONS) \
		tests/unit/test_validate_refactor_phase_6.py -q

smoke-compose-api: prepare-runtime-dirs
	@set -eu; \
	export ENV_FILE="$${ENV_FILE:-.env.example}"; \
	export COMPOSE_PROJECT_NAME=jung-phase6c-smoke; \
	cleanup() { \
		status=$$?; \
		trap - EXIT; \
		if [ "$$status" -ne 0 ]; then \
			docker compose -f docker-compose.yml \
				logs --no-color api || true; \
		fi; \
		docker compose -f docker-compose.yml \
			down --remove-orphans || true; \
		exit "$$status"; \
	}; \
	trap cleanup EXIT; \
	docker compose -f docker-compose.yml up \
		--build \
		--force-recreate \
		--remove-orphans \
		--wait \
		--wait-timeout 90 \
		api

finalization-check: prepare-runtime-dirs
	$(MAKE) lint
	$(MAKE) validate-docs
	$(MAKE) test-target
	$(MAKE) _validate-phase-6-cutover-contract
	$(MAKE) _validate-phase-5-external-contract
	$(MAKE) smoke-compose-api
	$(MAKE) probe-console-v1-deterministic

# Fast Phase 1 checkpoint: retained deterministic unit coverage plus real smoke.
test-refactor-fast: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest tests/unit/test_intake_record_merge.py tests/unit/test_intake_slot_evidence_adapter.py tests/unit/test_note_taker_intake_patch.py tests/unit/test_planning_analysis.py tests/unit/test_reflection_plan_snapshot.py tests/unit/test_agent_output_validators.py
validate-refactor-phase-1: prepare-runtime-dirs
	$(MAKE) validate-docs
	docker compose run --rm -v "$(PWD)/scripts:/app/scripts" -v "$(PWD)/docs:/app/docs" -v "$(PWD)/requirements.in:/app/requirements.in:ro" -v "$(PWD)/requirements-dev.in:/app/requirements-dev.in:ro" api python scripts/validate_refactor_phase_1.py
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest tests/unit/test_measure_codebase.py tests/unit/test_validate_refactor_phase_1.py

phase-2-test: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		tests/unit/jung/test_domain_models.py \
		tests/unit/jung/domain/test_plan_content.py \
		tests/unit/jung/test_json_validation.py \
		tests/unit/jung/test_sqlite_support.py \
		tests/unit/jung/test_workflow.py \
		tests/unit/jung/test_import_boundaries.py::test_phase2_packages_have_no_forbidden_imports \
		tests/integration/jung/test_store_chat.py \
		tests/integration/jung/test_store_recovery.py \
		tests/integration/jung/test_store_schema.py \
		tests/integration/jung/test_store_workflow.py \
		-q

validate-refactor-phase-2: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		src/jung/domain \
		src/jung/persistence \
		src/jung/workflow.py \
		tests/unit/jung/test_domain_models.py \
		tests/unit/jung/domain/test_plan_content.py \
		tests/unit/jung/test_json_validation.py \
		tests/unit/jung/test_sqlite_support.py \
		tests/unit/jung/test_workflow.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/integration/jung/test_store_chat.py \
		tests/integration/jung/test_store_recovery.py \
		tests/integration/jung/test_store_schema.py \
		tests/integration/jung/test_store_workflow.py
	$(MAKE) phase-2-test

phase-3-test: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		-o trio_mode=false \
		-o asyncio_mode=auto \
		tests/unit/jung/llm \
		tests/unit/jung/phases \
		tests/unit/jung/test_styles.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/integration/jung/test_processor_store_seams.py \
		tests/unit/jung/smoke/test_smoke_diagnostics.py \
		-q

phase-4-test: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		-o trio_mode=false \
		-o asyncio_mode=auto \
		tests/unit/jung/test_events.py \
		tests/unit/jung/test_supervisor.py \
		tests/unit/jung/test_application_helpers.py \
		tests/unit/jung/test_workflow.py \
		tests/unit/jung/llm/test_structured_output.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/integration/jung/test_application_workflow.py \
		tests/integration/jung/test_application_chat.py \
		tests/integration/jung/test_application_operations.py \
		tests/integration/jung/test_application_recovery.py \
		tests/integration/jung/test_application_composition.py \
		tests/integration/jung/test_application_session_history.py \
		tests/integration/jung/test_application_read_models.py \
		tests/integration/jung/test_store_workflow.py \
		tests/integration/jung/test_store_chat.py \
		tests/integration/jung/test_store_recovery.py \
		tests/integration/jung/test_processor_store_seams.py \
		-q

PHASE_5_PYTEST_OPTIONS := \
	-o trio_mode=false \
	-o asyncio_mode=auto

PHASE_5_CONSOLE_TEST := tests/e2e/test_console_v1_workflow.py

phase-5-test: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		$(PHASE_5_PYTEST_OPTIONS) \
		tests/unit/jung/api/ \
		tests/unit/jung/client/ \
		tests/unit/jung/test_events.py \
		tests/unit/jung/test_application_helpers.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/unit/jung/test_composition_settings.py \
		tests/unit/jung/llm/test_openai_compatible.py \
		tests/integration/jung/test_application_composition.py \
		tests/unit/test_recording_fake_llm.py \
		tests/unit/test_validate_refactor_phase_5.py \
		tests/integration/jung/test_application_chat.py::test_chat_worker_persists_sanitized_error_message \
		tests/integration/jung/test_application_operations.py::test_operation_worker_persists_sanitized_error_message \
		tests/integration/jung/api/ \
		tests/integration/jung/client/ \
		-q
	$(MAKE) _phase-5-console-v1

_phase-5-console-v1: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		$(PHASE_5_PYTEST_OPTIONS) \
		$(PHASE_5_CONSOLE_TEST) \
		-q

.PHONY: probe-console-v1-deterministic

PROBE_V1_OUTPUT_DIR ?= logs/workflow-probes/phase-5-v1
PROBE_V1_ABS_OUTPUT_DIR := $(abspath $(PROBE_V1_OUTPUT_DIR))

probe-console-v1-deterministic: prepare-runtime-dirs
	@mkdir -p "$(PROBE_V1_ABS_OUTPUT_DIR)"
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		-v "$(PROBE_V1_ABS_OUTPUT_DIR):/app/probe-output" \
		-e PROBE_OUTPUT_DIR=/app/probe-output \
		test pytest $(PHASE_5_PYTEST_OPTIONS) $(PHASE_5_CONSOLE_TEST) -v

validate-refactor-phase-5: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		src/jung/api \
		src/jung/client \
		src/jung/composition.py \
		src/jung/_env.py \
		src/jung/llm/openai_compatible.py \
		tests/jung_api_fixtures.py \
		tests/integration/jung/resilience_support.py \
		tests/integration/jung/api \
		tests/integration/jung/client \
		tests/integration/jung/test_application_composition.py \
		tests/unit/jung/test_composition_settings.py \
		tests/unit/jung/llm/test_openai_compatible.py \
		tests/unit/jung/api \
		tests/unit/jung/client \
		scripts/validate_refactor_phase_5.py \
		tests/unit/test_validate_refactor_phase_5.py \
		tests/unit/test_recording_fake_llm.py \
		tests/unit/jung/test_import_boundaries.py
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		--entrypoint /usr/local/bin/python \
		--volume "$(CURDIR):/workspace:ro" \
		--workdir /workspace \
		--env PYTHONPATH=/workspace/src \
		test scripts/validate_refactor_phase_5.py
	$(MAKE) phase-5-test

validate-refactor-phase-4: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		src/jung/application.py \
		src/jung/events.py \
		src/jung/supervisor.py \
		src/jung/composition.py \
		src/jung/llm/structured.py \
		src/jung/domain/commands.py \
		src/jung/domain/errors.py \
		src/jung/domain/models.py \
		src/jung/domain/results.py \
		src/jung/workflow.py \
		src/jung/persistence/sqlite_store.py \
		src/jung/phases/transcript.py \
		tests/unit/jung/test_events.py \
		tests/unit/jung/test_supervisor.py \
		tests/unit/jung/test_application_helpers.py \
		tests/unit/jung/test_workflow.py \
		tests/unit/jung/llm/test_structured_output.py \
		tests/integration/jung/application_fixtures.py \
		tests/integration/jung/assessment_test_data.py \
		tests/integration/jung/scenarios.py \
		tests/integration/jung/test_application_workflow.py \
		tests/integration/jung/test_application_chat.py \
		tests/integration/jung/test_application_operations.py \
		tests/integration/jung/test_application_recovery.py \
		tests/integration/jung/test_application_composition.py \
		tests/integration/jung/test_application_session_history.py \
		tests/integration/jung/test_application_read_models.py \
		tests/integration/jung/test_store_workflow.py \
		tests/integration/jung/test_store_chat.py \
		tests/integration/jung/test_store_recovery.py \
		tests/integration/jung/test_processor_store_seams.py \
		tests/unit/jung/test_import_boundaries.py
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test python scripts/validate_refactor_phase_4.py
	$(MAKE) phase-4-test

validate-refactor-target-all: prepare-runtime-dirs
	$(MAKE) validate-refactor-phase-1
	$(MAKE) validate-refactor-phase-2
	$(MAKE) validate-refactor-phase-3
	$(MAKE) validate-refactor-phase-4
	$(MAKE) validate-refactor-phase-5

validate-refactor-phase-3: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		src/jung/llm \
		src/jung/phases \
		src/jung/styles \
		tests/unit/jung/llm \
		tests/unit/jung/phases \
		tests/unit/jung/smoke \
		tests/smoke/jung \
		tests/unit/jung/test_styles.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/integration/jung/test_processor_store_seams.py
	$(MAKE) phase-3-test

smoke-refactor-phase-3-local-llm: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		-e PHASE3_SMOKE_SERVER \
		-e PHASE3_SMOKE_BASE_URL \
		-e PHASE3_SMOKE_MODEL \
		-e PHASE3_SMOKE_TIMEOUT \
		-e PHASE3_SMOKE_REQUEST_TIMEOUT \
		-e PHASE3_SMOKE_STRUCTURED_MODE \
		-e PHASE3_SMOKE_EXTRA_BODY \
		-e PHASE3_SMOKE_MAX_COMPLETION_TOKENS \
		-e PHASE3_SMOKE_THERAPY_MAX_SECONDS \
		-e PHASE3_SMOKE_ASSESSMENT_MAX_SECONDS \
		-e PHASE3_SMOKE_POST_SESSION_MAX_SECONDS \
		-e PHASE3_SMOKE_STRICT_ACCEPTANCE \
		-e PHASE3_SMOKE_LOG_PROMPT_PREVIEWS \
		test pytest $(PHASE3_SMOKE_TARGET) \
			-m real_llm --no-mocks \
			-o trio_mode=false -o asyncio_mode=strict \
			$(PHASE3_SMOKE_PYTEST_ARGS)

# Fast local validation. Full release validation remains an explicit checkpoint.
hook-commit: lint

hook-push: hook-commit

# Run devcontainer setup tests (Docker)
test-devcontainer: devcontainer-test

# Run the target-runtime test suite.
test-dev: test-target

# Run the target-runtime test suite.
test-validate: test-target

# Install git pre-commit and pre-push hooks for automated validation
install-hooks:
	@echo "🔧 Installing git hooks..."
	@./scripts/install-hooks.sh

# Clean up generated files
clean:
	@echo "Cleaning generated files and caches..."
	@rm -rf __pycache__ */__pycache__ \
		*.pyc */*.pyc \
		*.pyo */*.pyo \
		*.pyd */*.pyd \
		.pytest_cache/ \
		.mypy_cache/ \
		.pytype/ \
		build/ \
		dist/ \
		*.egg-info/ 2>/dev/null || true
	@echo "✓ Cleanup complete"

# Generate locked requirements from .in files with UV
requirements: prepare-runtime-dirs
	docker compose run --rm -v "$(PWD):/app" api uv pip compile requirements.in -o requirements.txt
	docker compose run --rm -v "$(PWD):/app" api uv pip compile requirements-dev.in -o requirements-dev.txt

# Sync environment with locked requirements using UV
sync: dev-install
	@echo "Docker images rebuilt using locked requirements."

run-server: docker-up

# Validate docs metadata and canonical docs index (Docker)
validate-docs: prepare-runtime-dirs
	docker compose run --rm -v "$(PWD)/docs:/app/docs" -v "$(PWD)/scripts:/app/scripts" api \
		env PYTHONPATH=/app/src python scripts/validate_docs_metadata.py

# ============================================
# Docker Development Commands
# ============================================

# Start the backend API service.
docker-up: prepare-runtime-dirs
	docker compose up --build --remove-orphans api

# Stop all Docker containers
docker-down:
	docker compose down

# Run tests in isolated Docker environment
# NOTE: This is usually not needed - use 'make test' for local testing
# Docker tests are mainly for CI/CD or when you need complete isolation
docker-test: test

# Run specific test file
docker-test-one:
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest $(TEST)

# Shell into API container
docker-shell:
	docker compose exec api bash

# View logs (default: all services, or specify SERVICE=api)
docker-logs:
	docker compose logs -f $(SERVICE)

# View API service logs
docker-logs-api:
	@if docker compose ps --services --status running | grep -qx api-usertest; then \
		docker compose logs -f api-usertest; \
	else \
		docker compose logs -f api; \
	fi

# Start database viewer for debugging
# Usage:
#   make docker-db-view             # View local DB (default)
#   make docker-db-view DB=usertest # View usertest DB
# Note: The automated test database is stored in the Docker-managed test-data
# volume. It is intentionally not exposed through docker-db-view. Use
# make docker-test-reset to remove it; the next test run recreates it.
docker-db-view:
	@DB_NAME=$${DB:-local}; \
	case $$DB_NAME in \
		local) DB_FILE=local/jung.db ;; \
		usertest) DB_FILE=usertest/jung.db ;; \
		*) echo "❌ Invalid DB. Use: local or usertest"; \
		   echo ""; \
		   echo "Note: The automated test database is stored in the Docker-managed"; \
		   echo "      test-data volume. It is intentionally not exposed through"; \
		   echo "      docker-db-view. Use make docker-test-reset to remove it;"; \
		   echo "      the next test run recreates it."; \
		   echo ""; \
		   echo "Example: make docker-db-view DB=usertest"; \
		   exit 1 ;; \
	esac; \
	if [ ! -f "data/$$DB_FILE" ]; then \
		echo "❌ Database file not found: data/$$DB_FILE"; \
		echo ""; \
		echo "Available databases:"; \
		ls -1 data/local/*.db data/usertest/*.db 2>/dev/null || echo "  (none)"; \
		echo ""; \
		echo "💡 Tip: Run the app to create databases:"; \
		echo "   - Local: make ui-console"; \
		echo "   - Usertest: make ui-console-test"; \
		exit 1; \
	fi; \
	if [ ! -s "data/$$DB_FILE" ]; then \
		echo "⚠️  Warning: Database file is empty (0 bytes): data/$$DB_FILE"; \
		echo ""; \
		echo "💡 This database hasn't been initialized yet. Run the app to create tables:"; \
		echo "   - Local: make ui-console"; \
		echo "   - Usertest: make ui-console-test"; \
		echo ""; \
		read -p "Continue anyway? (y/N) " -n 1 -r; \
		echo ""; \
		if [[ ! $$REPLY =~ ^[Yy]$$ ]]; then \
			echo "Cancelled."; \
			exit 1; \
		fi; \
	fi; \
	echo "🔍 Starting database viewer for $$DB_NAME database..."; \
	echo "📁 Database file: data/$$DB_FILE"; \
	echo "🌐 Access at: http://localhost:8080"; \
	echo ""; \
	DB_FILE=$$DB_FILE docker compose --profile debug up db-viewer

# Reset test database (removes test data volume)
docker-test-reset:
	docker compose -f docker-compose.yml --profile test down --volumes --remove-orphans

# Clean up all Docker resources
docker-clean:
	docker compose down --volumes --rmi local
	docker system prune -f

# ============================================
# jung-console Commands
# ============================================

# jung-console against the Compose API.
ui-console: prepare-runtime-dirs
	docker compose up --build --wait -d api
	docker compose exec api \
		jung-console --api-url http://127.0.0.1:8000

# jung-console against the usertest Compose API.
ui-console-test: prepare-runtime-dirs check-usertest-env
	docker compose --profile usertest-console \
		up --build --wait -d api-usertest
	docker compose --profile usertest-console exec api-usertest \
		jung-console --api-url http://127.0.0.1:8000

# Local full-stack diagnostic probe. This is intentionally not a CI gate.
probe: prepare-runtime-dirs
	@./scripts/probe_local_llm.sh

probe-console-deterministic: prepare-runtime-dirs
	@./scripts/probe_deterministic.sh

probe-console-intake-notes: prepare-runtime-dirs
	@./scripts/probe_intake_notes.sh

probe-logs:
	@if [ -f logs/workflow-probes/latest/summary.md ]; then \
		cat logs/workflow-probes/latest/summary.md; \
	else \
		echo "No workflow probe summary found at logs/workflow-probes/latest/summary.md"; \
		exit 1; \
	fi

probe-db:
	@if [ -f logs/workflow-probes/latest/created_rows.json ]; then \
		cat logs/workflow-probes/latest/created_rows.json; \
	else \
		echo "No workflow probe database artifact found at logs/workflow-probes/latest/created_rows.json"; \
		exit 1; \
	fi

# ============================================
# DevContainer Commands
# ============================================

# Rebuild devcontainer without cache
devcontainer-rebuild:
	@echo "🔄 Rebuilding devcontainer..."
	@echo "This will rebuild the container from scratch without using cache."
	@echo ""
	@if command -v devcontainer > /dev/null 2>&1; then \
		devcontainer build --workspace-folder . --no-cache; \
	else \
		echo "❌ devcontainer CLI not found."; \
		echo "Install it with: npm install -g @devcontainers/cli"; \
		echo ""; \
		echo "Alternative: Rebuild from VSCode:"; \
		echo "1. Open Command Palette (Ctrl+Shift+P)"; \
		echo "2. Run 'Dev Containers: Rebuild Container'"; \
		exit 1; \
	fi

# Test devcontainer configuration
devcontainer-test:
	@echo "✅ Testing devcontainer setup..."
	@test -f .devcontainer/devcontainer.json && echo "✓ .devcontainer/devcontainer.json exists"
	@test -f .vscode/settings.json && echo "✓ .vscode/settings.json exists"
	@test -f .vscode/extensions.json && echo "✓ .vscode/extensions.json exists"
	@test -f .vscode/launch.json && echo "✓ .vscode/launch.json exists"
	docker compose --profile devcontainer config --quiet
	@echo "✓ Docker Compose devcontainer profile is valid"

# Open project in VSCode devcontainer
devcontainer-open:
	@echo "🚀 Opening project in VSCode devcontainer..."
	@if command -v code > /dev/null 2>&1; then \
		code --folder-uri vscode-remote://dev-container+$(shell pwd | sed 's/\//\%2F/g')/app; \
	else \
		echo "❌ VSCode CLI not found."; \
		echo ""; \
		echo "Manual steps:"; \
		echo "1. Open this folder in VSCode"; \
		echo "2. Press Ctrl+Shift+P"; \
		echo "3. Run 'Dev Containers: Reopen in Container'"; \
	fi
check-usertest-env:
	@if [ ! -f .env.usertest ]; then \
		echo "❌ .env.usertest is missing."; \
		echo "   Copy .env.usertest.template to .env.usertest and configure LLM_BASE_URL and MODEL_NAME."; \
		exit 1; \
	fi
	@set -a && . ./.env.usertest && set +a && \
	if [ -z "$${LLM_BASE_URL:-}" ] || [ "$${LLM_BASE_URL}" = "your_llm_base_url_here" ]; then \
		echo "❌ LLM_BASE_URL is not configured in .env.usertest."; \
		exit 1; \
	fi && \
	if [ -z "$${MODEL_NAME:-}" ] || [ "$${MODEL_NAME}" = "your_model_name_here" ]; then \
		echo "❌ MODEL_NAME is not configured in .env.usertest."; \
		exit 1; \
	fi
